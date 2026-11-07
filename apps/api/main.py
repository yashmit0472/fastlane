import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from .database import initialize, SessionLocal, Race, Snapshot, SystemState, utc_timestamp
from .contracts import Forecast
from ml.live.race_window import race_view,focus_race


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(title="FASTLANE API", version="0.1.0", lifespan=lifespan,
              description="Read-only serving API. Ingestion and training run as separate commands.")
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000").split(",") if x.strip()]
if os.getenv("APP_ENV") == "production" and (not os.getenv("CORS_ORIGINS") or "*" in origins):
    raise RuntimeError("Production requires an explicit CORS_ORIGINS allow-list")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={"detail": "Data store unavailable. Please try again shortly."})


def snapshot(entity_id, kind):
    with SessionLocal() as db:
        query = db.query(Snapshot).filter_by(entity_id=entity_id, kind=kind)
        if kind in {"prediction", "weekend", "evaluation"}:
            race = db.get(Race, entity_id)
            if not race or race.is_demo:
                raise HTTPException(404, "Race not found")
            if kind == "prediction":
                query = query.filter(Snapshot.cutoff < race.scheduled_at)
        for value in query.order_by(Snapshot.cutoff.desc(), Snapshot.id.desc()).all():
            if value.payload.get("is_demo") is True:
                continue
            if kind in {"prediction", "weekend", "circuit", "form"} and value.payload.get("is_demo") is not False:
                continue
            return value.payload
        raise HTTPException(404, "No real saved data available for this view")


@app.head("/health", include_in_schema=False)
@app.get("/health")
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "build_version": "0.1.0"}


@app.get("/api/races")
def races():
    with SessionLocal() as db:
        now = utc_timestamp(datetime.now(timezone.utc).isoformat())
        records = db.query(Race).filter(Race.is_demo.is_(False)).all()
        future = sorted([r for r in records if r.scheduled_at > now], key=lambda r:r.scheduled_at)
        past = sorted([r for r in records if r.scheduled_at <= now], key=lambda r:r.scheduled_at, reverse=True)
        current=datetime.now(timezone.utc)
        return {"races": [race_view(r.payload,current) for r in future + past]}


@app.get("/api/races/next")
def next_race():
    now = utc_timestamp(datetime.now(timezone.utc).isoformat())
    with SessionLocal() as db:
        value = db.query(Race).filter(Race.is_demo.is_(False), Race.scheduled_at > now).order_by(Race.scheduled_at).first()
        if value:
            return race_view(value.payload,datetime.now(timezone.utc))
    raise HTTPException(404, "No upcoming race available. Run the schedule ingestion command.")


@app.get('/api/races/current')
def current_race():
    with SessionLocal() as db:
        records=db.query(Race).filter(Race.is_demo.is_(False)).all()
        value=focus_race([r.payload for r in records],datetime.now(timezone.utc))
        if value: return value
    raise HTTPException(404,'No current race available. Run schedule ingestion.')


@app.get("/api/races/{race_id}")
def race(race_id: str):
    with SessionLocal() as db:
        value = db.get(Race, race_id)
        if not value or value.is_demo:
            raise HTTPException(404, "Race not found")
        return race_view(value.payload,datetime.now(timezone.utc))


@app.get("/api/races/{race_id}/prediction", response_model=Forecast)
def prediction(race_id: str):
    return snapshot(race_id, "prediction")


@app.get("/api/races/{race_id}/predictions")
def prediction_history(race_id: str):
    with SessionLocal() as db:
        race = db.get(Race, race_id)
        if not race or race.is_demo:
            raise HTTPException(404, "Race not found")
        values = db.query(Snapshot).filter_by(entity_id=race_id, kind="prediction").filter(Snapshot.cutoff < race.scheduled_at).order_by(Snapshot.cutoff).all()
        return {"race_id": race_id, "predictions": [Forecast.model_validate(v.payload).model_dump(mode="json") for v in values if v.payload.get("is_demo") is False]}


@app.get("/api/races/{race_id}/evaluation")
def evaluation(race_id: str):
    try:
        return snapshot(race_id, "evaluation")
    except HTTPException:
        with SessionLocal() as db:
            race = db.get(Race, race_id)
            if not race or race.is_demo:
                raise HTTPException(404, "Race not found")
        return {"race_id": race_id, "status": "waiting", "winner": None, "forecasts": [], "notice": "Scoring appears after a published race classification is available."}


@app.get("/api/system/status")
def system_status():
    with SessionLocal() as db:
        state = db.get(SystemState, "refresh")
        if not state:
            return {"status": "waiting", "is_demo": False, "notice": "Waiting for the first automatic source refresh.", "interval_seconds": 300}
        payload = dict(state.payload)
        if payload.get("last_attempt"):
            attempted = datetime.fromisoformat(payload["last_attempt"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - attempted).total_seconds() > max(payload.get("interval_seconds",300)*2+60,180):
                payload["status"] = "stale"
                payload["notice"] = "The refresh worker has not checked sources recently. Saved data remains available."
        return payload


@app.get("/api/races/{race_id}/weekend")
def weekend(race_id: str):
    return snapshot(race_id, "weekend")


@app.get('/api/system/operations')
def operations():
    from ml.live.operations import inspect
    with SessionLocal() as db: return inspect(db)


@app.get('/ready')
def readiness():
    status=operations()
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=200 if status['ready'] else 503,content=status)


@app.get("/api/circuits/{circuit_id}/history")
def circuit(circuit_id: str):
    return snapshot(circuit_id, "circuit")


@app.get("/api/drivers/{driver_id}/form")
def form(driver_id: str):
    return snapshot(driver_id, "form")


@app.get("/api/model/metrics")
def metrics():
    try:
        return snapshot("model", "metrics")
    except HTTPException:
        return {"status": "untrained", "model_version": None, "test_window": None, "metrics": None,
                "notice": "No evaluated model report is available yet. Forecasts remain unavailable until real source data passes checks."}


@app.get('/api/model/practice')
def practice_metrics():
    stages={}
    for stage in ['FP1','FP2','FP3']:
        try: stages[stage]=snapshot('model-practice-'+stage,'metrics')
        except HTTPException: pass
    return {'stages':stages,'status':'backtested' if len(stages)==3 else 'waiting'}


@app.get('/api/model/outcomes')
def outcome_metrics():
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[2]/'docs/outcome-model-reports.json'
    if not path.exists(): return {'status':'waiting','stages':{}}
    return {'status':'backtested','stages':json.loads(path.read_text(encoding='utf-8'))}


def saved_report(filename):
    import json
    from pathlib import Path
    path=Path(__file__).resolve().parents[2]/'docs'/filename
    return json.loads(path.read_text()) if path.exists() else {'status':'not run','stages':{},'notice':'Offline validation has not been saved yet.'}


@app.get('/api/model/validation')
def validation_report():
    return saved_report('validation-report.json')


@app.get('/api/model/source-validation')
def source_validation():
    return saved_report('source-validation-report.json')


@app.get('/api/model/conditions')
def conditions_report():
    return saved_report('conditions-model-report.json')


def card_from_db(db,race):
    from ml.live.reportcards import race_card
    forecasts=[v.payload for v in db.query(Snapshot).filter_by(entity_id=race.race_id,kind='prediction').filter(Snapshot.cutoff<race.scheduled_at).all() if v.payload.get('is_demo') is False]
    result=db.query(Snapshot).filter_by(entity_id=race.race_id,kind='evaluation').order_by(Snapshot.cutoff.desc(),Snapshot.id.desc()).first()
    return race_card(race.payload,forecasts,result.payload if result else None)


@app.get('/api/races/{race_id}/report-card')
def report_card(race_id:str):
    with SessionLocal() as db:
        value=db.get(Race,race_id)
        if not value or value.is_demo: raise HTTPException(404,'Race not found')
        return card_from_db(db,value)


@app.get('/api/performance')
def performance():
    from ml.live.reportcards import overall
    with SessionLocal() as db:
        races=db.query(Race).filter(Race.is_demo.is_(False)).all()
        now=utc_timestamp(datetime.now(timezone.utc).isoformat())
        return overall([card_from_db(db,r) for r in races if r.scheduled_at<now])


@app.get('/api/races/{race_id}/weather')
def weather(race_id:str):
    with SessionLocal() as db:
        value=db.get(Race,race_id)
        if not value or value.is_demo: raise HTTPException(404,'Race not found')
    return snapshot(race_id,'weather')
