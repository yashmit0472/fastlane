"""Free, delayed post-session ingestion worker. No training and no demo fallback.

Run separately from FastAPI: python -m ml.live.refresh --loop
"""
import argparse
import hashlib
import json
import logging
import os
import pickle
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from sqlalchemy import select
from apps.api.database import initialize, SessionLocal, Race, Snapshot, SystemState, save_snapshot, utc_timestamp
from apps.api.contracts import Forecast
from ml.live.race_window import recent_unclassified,refresh_targets,race_view
from ml.ingestion.jolpica import Client, normalize_schedule
from ml.ingestion.fastf1_sessions import summarize
from ml.features.build import features_for_race, NUMERIC, CATEGORICAL, race_start, lap_ms
from ml.training.evaluate import race_distribution
from .analytics import earlier, circuit_summary, driver_form, practice_forecast, score_forecasts
from .practice_model import active_report, learned_forecast
from .evidence import EVIDENCE_VERSION

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data/raw/live"
STAGES = {"FirstPractice":"FP1","SecondPractice":"FP2","ThirdPractice":"FP3","Qualifying":"Q","SprintQualifying":"SQ","SprintShootout":"SQ","Sprint":"Sprint"}
log = logging.getLogger("fastlane.refresh")


def now_utc():
    return datetime.now(timezone.utc)


def wait_for_next_check(seconds, clock=now_utc, sleep=time.sleep):
    """Use a wall-clock deadline so waking from sleep cannot add another 15-minute wait."""
    deadline=clock()+timedelta(seconds=seconds)
    while True:
        remaining=(deadline-clock()).total_seconds()
        if remaining<=0: return
        sleep(min(30,remaining))


@contextmanager
def worker_lock():
    """OS lock releases on exit/crash, preventing overlapping local refresh jobs."""
    CACHE.mkdir(parents=True,exist_ok=True)
    with (CACHE/"worker.lock").open("a+b") as lock:
        lock.seek(0,2)
        if lock.tell()==0: lock.write(b"0"); lock.flush()
        lock.seek(0)
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try: yield
        finally:
            lock.seek(0)
            if os.name=="nt": msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(lock.fileno(),fcntl.LOCK_UN)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()[:16]


def schedule_sessions(raw):
    sessions = {}
    for field, stage in STAGES.items():
        value = raw.get(field)
        if value and value.get("date") and value.get("time"):
            start = value["date"] + "T" + value["time"]
            sessions[stage] = {"type":stage,"started_at":utc_timestamp(start),"status":"scheduled"}
    return sorted(sessions.values(), key=lambda s:s["started_at"])


def entries_from(results):
    entries = []
    colors = {"mclaren":"#ff9b42","ferrari":"#ef4444","mercedes":"#55d4bc","red_bull":"#639aff","williams":"#6bbdff",
              "aston_martin":"#64c9a4","haas":"#d2d4dc","alpine":"#ed80bd","rb":"#8b94fa","racing_bulls":"#8b94fa"}
    for row in results:
        driver, team = row["Driver"], row["Constructor"]
        number = row.get("number") or driver.get("permanentNumber")
        if not number or not str(number).isdigit():
            raise ValueError("Entry numbers unavailable; waiting for source metadata")
        entries.append({"driver_id":driver["driverId"],"name":driver.get("givenName","")+" "+driver.get("familyName",""),
                        "abbreviation":driver.get("code") or driver["driverId"][:3].upper(),"number":int(number),
                        "team":team.get("name",team["constructorId"]),"constructor_id":team["constructorId"],
                        "color":colors.get(team["constructorId"],"#a4aaba")})
    if len({e["driver_id"] for e in entries}) != len(entries):
        raise ValueError("Duplicate entry identifiers")
    return entries


def choose_model(path=None):
    if path:
        candidates = [Path(path)]
    else:
        manifest=ROOT/'ml/artifacts/qualifying-active.json'
        if manifest.exists():
            info=json.loads(manifest.read_text()); candidate=(ROOT/info['report']).resolve()
            if info.get('schema')!='qualifying-bundle-v1' or not candidate.is_relative_to(ROOT/'ml/artifacts') or hashlib.sha256(candidate.read_bytes()).hexdigest()!=info['sha256']: raise ValueError('Qualifying manifest/report integrity mismatch')
            for filename,expected in info['artifacts'].items():
                artifact=(candidate.parent/filename).resolve()
                if not artifact.is_relative_to(candidate.parent) or hashlib.sha256(artifact.read_bytes()).hexdigest()!=expected: raise ValueError('Qualifying weights integrity mismatch')
            candidates=[candidate]
        else: candidates = sorted((ROOT / "ml/artifacts").glob("*/report.json"),key=lambda p:p.stat().st_mtime,reverse=True)
    for candidate in candidates:
        report = json.loads(candidate.read_text(encoding="utf-8"))
        name = report.get("selected_model")
        if report.get("status")!="backtested" or report.get("feature_version")!="qualifying-history-v2":
            continue
        artifact = candidate.parent / ("model.cbm" if name=="catboost" else "logistic.pkl")
        if name=="grid_baseline" or artifact.is_file():
            return candidate, report
    return None, None


def qualifying_forecast(race, raw, history, entries, report_path, report, cutoff):
    if cutoff >= datetime.fromisoformat(race["scheduled_at"].replace("Z","+00:00")):
        raise ValueError("Race has started; retrospective forecast publication is prohibited")
    if datetime.fromisoformat(report["trained_until"].replace("Z","+00:00")) >= cutoff:
        raise ValueError("Model training range crosses forecast cutoff")
    if report.get("created_at") and datetime.fromisoformat(report["created_at"].replace("Z","+00:00"))>cutoff:
        raise ValueError("Model artifact was created after forecast cutoff")
    # Timing is audited separately here. Sprint format is flagged as outside the standard-weekend training sample.
    target = {k:v for k,v in raw.items() if k not in {"Sprint","SprintResults"}}
    rows = features_for_race(target,history,cutoff,include_target=False)
    if not rows or {r["driver_id"] for r in rows}!={e["driver_id"] for e in entries}:
        raise ValueError("Qualifying input does not cover the full participant field")
    frame = pd.DataFrame(rows)
    name = report["selected_model"]
    if name=="catboost":
        from catboost import CatBoostClassifier
        model = CatBoostClassifier()
        model.load_model(str(report_path.parent / "model.cbm"))
        x = frame[NUMERIC+CATEGORICAL].copy()
        for col in NUMERIC: x[col]=x[col].fillna(-999)
        for col in CATEGORICAL: x[col]=x[col].fillna("unknown").astype(str)
        scores = model.predict_proba(x)[:,1]
    elif name=="logistic":
        from ml.inference.linear import load_linear
        model=load_linear(report_path.parent/'logistic.pkl')
        scores = model.predict_proba(frame[NUMERIC+CATEGORICAL])[:,1]
    elif name=="grid_baseline":
        scores = frame.qualifying_position.map(lambda p:report["grid_rates"].get(str(p),.05)).to_numpy()
    else:
        raise ValueError("Unsupported evaluated model")
    probabilities = race_distribution(scores,report["temperatures"][name])
    from ml.live.explain import winner_associations
    associations=winner_associations(frame,report_path,report)
    lookup = {e["driver_id"]:e for e in entries}
    drivers = [{**lookup[row["driver_id"]],"grid":row["qualifying_position"],"probability":float(p),
                "factors":[f"Qualifying P{row['qualifying_position']}",f"Earlier circuit sample: {row['prior_starts']} starts","Earlier driver/constructor form"]}
               for row,p in zip(rows,probabilities)]
    for d in drivers: d['model_associations']={'winner':associations[d['driver_id']]} if d['driver_id'] in associations else {}
    drivers.sort(key=lambda d:d["probability"],reverse=True)
    from ml.live.outcomes import attach_outcomes
    outcomes_version = None if raw.get('Sprint') else attach_outcomes(drivers,frame,'Q',cutoff,report['model_version'])
    return {"race_id":race["race_id"],"model_version":report["model_version"],"cutoff":cutoff.isoformat(),"updated_at":cutoff.isoformat(),
            "race_start":race["scheduled_at"],"is_demo":False,"calibrated":True,"stage":"Q","method":f"{name} qualifying/history model",
            "status":"experimental","field_status":"qualifying participants",
            "notice":"Grid column shows qualifying position; later penalties may change the starting grid." + (" Sprint format was excluded from model training; this forecast is outside that coverage." if raw.get("Sprint") else ""),
            "evidence":[{"source":raw.get('source','Jolpica')+" qualifying classification","session":"Q","available_at":raw.get('observed_at',cutoff.isoformat())}],"drivers":drivers,"outcomes_model_version":outcomes_version}


def save_changed(entity, kind, payload, cutoff, version="live-v1"):
    def content(value):
        if isinstance(value,dict): return {k:content(v) for k,v in value.items() if k not in {"cutoff","updated_at","observed_at"}}
        if isinstance(value,list): return [content(v) for v in value]
        return value
    with SessionLocal() as db:
        last = db.query(Snapshot).filter_by(entity_id=entity,kind=kind).order_by(Snapshot.cutoff.desc(),Snapshot.id.desc()).first()
        if last and digest(content(last.payload))==digest(content(payload)):
            return False
        stored_version=version+"-"+digest(content(payload)) if kind in {"circuit","form","weekend","evaluation"} else version
        save_snapshot(db,entity,kind,stored_version,cutoff,payload)
        db.commit()
        return True


def stage_already_saved(race_id, stage, inputs_signature=None):
    with SessionLocal() as db:
        values = db.query(Snapshot).filter_by(entity_id=race_id,kind="prediction").all()
        return any(v.payload.get("is_demo") is False and v.payload.get("stage","Q")==stage
            and (inputs_signature is None or v.payload.get('inputs_signature')==inputs_signature) for v in values)


def practice_inputs_signature(practice,stage,entries=None,condition_weather=None):
    from ml.live.conditions import signature as conditions_signature
    allowed=['FP1','FP2','FP3'][:['FP1','FP2','FP3'].index(stage)+1]
    return digest({'evidence_version':EVIDENCE_VERSION,'conditions_bundle':conditions_signature(),'condition_weather':condition_weather,'entries':entries,'sessions':{name:{k:s.get(k) for k in ['source','session_key','quality_policy','drivers']}
        for name,s in practice.items() if name in allowed}})


def cache_practice(target, data):
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,indent=2),encoding='utf-8'); temporary.replace(target)
    data['drivers_by_id']={d['driver_id']:d for d in data['drivers']}
    return data


def load_practice(raw, stage):
    key = f"{raw['season']}-{int(raw['round']):02d}-{stage}"
    target = CACHE / (key + ".json")
    if target.exists():
        data = json.loads(target.read_text(encoding="utf-8"))
        if data.get('summary_version')=='practice-stats-v1' and data.get('type')==stage and data.get('race_id')==f"{raw['season']}-{int(raw['round']):02d}" and (data.get('source')!='OpenF1' or data.get('quality_policy')=='published-best-v2'):
            data["drivers_by_id"]={d["driver_id"]:d for d in data["drivers"]}
            if data.get('source')!='OpenF1' or race_start(raw)<now_utc() or (now_utc()-datetime.fromisoformat(data['observed_at'])).total_seconds()<300:
                return data
            from ml.ingestion.openf1_sessions import load_practice as openf1_practice
            try: return cache_practice(target,openf1_practice(raw,stage))
            except Exception:
                data['refresh_warning']='OpenF1 refresh is delayed; showing the last successful published data.'
                return data
    cache = CACHE / "fastf1"
    cache.mkdir(parents=True,exist_ok=True)
    try:
        import fastf1
        fastf1.Cache.enable_cache(str(cache))
        # Failed/empty new sessions must be retried instead of caching an empty response.
        with fastf1.Cache.disabled():
            session=fastf1.get_session(int(raw["season"]),int(raw["round"]),stage)
            session.load(telemetry=False,weather=False,messages=True)
        statuses = session.session_status
        if statuses.empty or statuses.sort_values("Time").iloc[-1]["Status"] not in {"Finished","Finalised","Ends"}:
            raise ValueError("Source has not confirmed session completion")
        rows=summarize(session.laps,session.results)
        if not rows or sum(d["best_lap_ms"] is not None for d in rows)<2:
            raise ValueError("Session timing has not been published with usable laps")
        data={"race_id":f"{raw['season']}-{int(raw['round']):02d}","type":stage,"status":"published","source":"FastF1","observed_at":now_utc().isoformat(),"drivers":rows,'summary_version':'practice-stats-v1',
              "notice":"Clean-lap summaries; representative pace is not a fuel/tyre-adjusted long run."}
    except Exception as primary:
        log.warning('%s: FastF1 unavailable; checking free OpenF1 archive (%s)',key,type(primary).__name__)
        from ml.ingestion.openf1_sessions import load_practice as openf1_practice
        try: data=openf1_practice(raw,stage)
        except Exception as fallback:
            raise ValueError(f'Practice timing unavailable from FastF1 and OpenF1: {fallback}') from fallback
    return cache_practice(target,data)


def qualifying_inputs_signature(raw,condition_weather=None):
    from ml.live.conditions import signature as conditions_signature
    return digest({'qualifying':raw['QualifyingResults'],'source':raw['source'],'conditions_bundle':conditions_signature(),'condition_weather':condition_weather,'evidence_version':EVIDENCE_VERSION})


def load_qualifying(raw,entries,client,known=None,strict_roster=True):
    from ml.ingestion.qualifying import validate,openf1,fastf1
    target=CACHE/f"{raw['season']}-{int(raw['round']):02d}-Q.json"
    failures=[]
    def checked(value,authoritative=False):
        if str(value.get('season'))!=str(raw['season']) or int(value.get('round',-1))!=int(raw['round']): raise ValueError('Qualifying response belongs to another race')
        expected=entries
        if authoritative and not strict_roster:
            if len(value.get('QualifyingResults',[]))!=len(entries): raise ValueError('Waiting for a complete qualifying field')
            expected=None
        return validate(value,expected)
    try:
        candidates=([{'season':raw['season'],'round':raw['round'],'QualifyingResults':known}] if known else client.races(f"{raw['season']}/{int(raw['round'])}",'qualifying',refresh=True))
        data=checked(next((r for r in candidates if r.get('QualifyingResults')),{}),authoritative=True)
        data={**data,'source':'Jolpica','observed_at':now_utc().isoformat(),'quality_policy':'published-qualifying-v1'}
    except Exception as exc:
        failures.append('Jolpica: '+str(exc)); data=None
    if data is None:
        for name,loader in [('OpenF1',openf1),('FastF1',fastf1)]:
            try: data=checked(loader(raw,entries)); break
            except Exception as exc: failures.append(name+': '+str(exc))
    if data is not None:
        target.parent.mkdir(parents=True,exist_ok=True); temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(data,indent=2),encoding='utf-8'); temporary.replace(target)
        return data
    if target.exists():
        cached=checked(json.loads(target.read_text(encoding='utf-8')),authoritative=True)
        cached['refresh_warning']='Qualifying sources are delayed; showing the last complete published classification.'
        return cached
    raise ValueError('Qualifying not yet usable from any configured source: '+'; '.join(failures))


def qualifying_sessions(raw, observed):
    phases=[]
    for phase in ["Q1","Q2","Q3"]:
        rows=[]
        for q in raw.get("QualifyingResults",[]):
            e=entries_from([q])[0]
            value=lap_ms(q.get(phase))
            rows.append({**e,"best_lap_ms":value,"representative_lap_ms":None,"lap_count":None,
                         "quality":"published phase result" if value is not None else "no phase time"})
        best=min((r["best_lap_ms"] for r in rows if r["best_lap_ms"] is not None),default=None)
        for row in rows: row["gap_ms"]=row["best_lap_ms"]-best if row["best_lap_ms"] is not None and best is not None else None
        phases.append({"type":phase,"status":"published","source":raw.get('source','Jolpica'),"session_key":raw.get('session_key'),"observed_at":raw.get('observed_at',observed),"drivers":rows})
    return phases


def archived_sessions(race, qualifying, existing, observed):
    """Publish already-fetched qualifying for every archive; preserve real practice."""
    stored={s['type']:s for s in existing if s.get('drivers')}
    if qualifying:
        from ml.ingestion.qualifying import validate
        try: validate(qualifying,None,require_final=False)
        except (KeyError,ValueError) as exc:
            log.warning('Archive qualifying rejected: %s',str(exc)); qualifying=None
    phases=qualifying_sessions(qualifying,observed) if qualifying else [stored[p] for p in ['Q1','Q2','Q3'] if p in stored]
    sessions=[]
    for scheduled in race.get('sessions',[]):
        stage=scheduled['type']
        if stage=='Q' and phases:
            sessions.extend(phases)
        elif stage in stored:
            sessions.append(stored[stage])
        else:
            sessions.append({**scheduled,'drivers':[],
                'status':'not modelled' if stage in {'SQ','Sprint'} else 'archive pending',
                'notice':'Sprint timing is not imported by the current pipeline.' if stage in {'SQ','Sprint'} else 'Archived session timing is queued for import. Race classification is shown separately when published.'})
    if phases and not any(s['type']=='Q' for s in race.get('sessions',[])):
        sessions.extend(phases)
    return sessions


def set_state(payload):
    with SessionLocal() as db:
        existing=db.get(SystemState,"refresh")
        old=existing.payload if existing else {}
        merged={**old,**payload,"is_demo":False}
        if existing: existing.payload=merged
        else: db.add(SystemState(key="refresh",payload=merged))
        db.commit()


def refresh_once(season=None, model_report=None, interval=300, archive_limit=1):
    initialize(); CACHE.mkdir(parents=True,exist_ok=True)
    started=now_utc(); season=season or started.year
    set_state({"status":"refreshing","last_attempt":started.isoformat(),"interval_seconds":interval,"notice":"Checking published source data."})
    client=Client()
    source_cache=CACHE/f"{season}-source.json"
    cached=json.loads(source_cache.read_text(encoding="utf-8")) if source_cache.exists() else {}
    stamp=cached.get("observed_at")
    fresh=stamp and (started-datetime.fromisoformat(stamp)).total_seconds()<interval
    notices=[]
    def source(kind):
        if fresh and kind in cached: return cached[kind]
        try: return client.races(season,refresh=True) if kind=='calendar' else client.races(season,kind,refresh=True)
        except Exception as exc:
            notices.append(f'Jolpica {kind} request delayed; cached data and session fallbacks are being used.')
            log.warning('Jolpica %s unavailable: %s',kind,str(exc)); return cached.get(kind,[])
    calendar=source('calendar'); results=source('results'); qualifying=source('qualifying')
    if not calendar: raise ValueError("Verified schedule unavailable")
    if not fresh or "qualifying" not in cached:
        source_cache.write_text(json.dumps({"calendar":calendar,"results":results,"qualifying":qualifying,"observed_at":now_utc().isoformat()}),encoding="utf-8")
    calendar_by_round={int(r["round"]):r for r in calendar}
    # Retain previously verified fallback results in form/history during primary outages.
    result_rounds={int(r['round']) for r in results}
    from ml.ingestion.race_results import validate as validate_result
    for cached_result in CACHE.glob(f'{season}-*-R.json'):
        try:
            value=json.loads(cached_result.read_text()); number=int(value['round']); raw=calendar_by_round.get(number)
            if raw and number not in result_rounds and race_start(raw)<started:
                results.append(validate_result(value,raw)); result_rounds.add(number)
        except Exception as exc: log.warning('Cached result unavailable: %s',str(exc))
    normalized={}
    for raw in calendar:
        if not raw.get("time"): continue
        payload=normalize_schedule(raw,stamp if fresh else started.isoformat())
        payload["sessions"]=schedule_sessions(raw)
        normalized[payload["race_id"]]=payload
        with SessionLocal() as db:
            existing=db.get(Race,payload["race_id"])
            if existing and existing.payload.get("status")=="completed": payload["status"]="completed"
            payload=race_view(payload,started); normalized[payload['race_id']]=payload
            db.merge(Race(race_id=payload["race_id"],season=payload["season"],round=payload["round"],scheduled_at=payload["scheduled_at"],is_demo=False,payload=payload)); db.commit()
    historical_path=ROOT/"data/processed/kaggle-2018-2025/history.json"
    if not historical_path.exists(): historical_path=ROOT/"data/processed/history.json"
    if not historical_path.exists(): raise ValueError('Historical feature backbone missing; restore the prepared history before forecasting')
    history=json.loads(historical_path.read_text(encoding="utf-8"))["races"]
    indexed={(int(r["season"]),int(r["round"])):r for r in history}
    qualifying_by_round={int(r["round"]):r.get("QualifyingResults",[]) for r in qualifying}
    for raw in results:
        merged={**calendar_by_round.get(int(raw["round"]),{}),**raw}
        merged["QualifyingResults"]=qualifying_by_round.get(int(raw["round"]),[])
        indexed[(int(raw["season"]),int(raw["round"]))]=merged
    history=list(indexed.values())
    # Final results have their own fallback even when the next weekend is already selected.
    primary_results={int(r['round']):r for r in results}
    for raw in calendar:
        if not raw.get('time') or not timedelta(minutes=90)<=started-race_start(raw)<=timedelta(days=7): continue
        rid=f"{raw['season']}-{int(raw['round']):02d}"; expected=None
        try:
            qpath=CACHE/(rid+'-Q.json')
            if qpath.exists(): expected=entries_from(json.loads(qpath.read_text())['QualifyingResults'])
            elif qualifying_by_round.get(int(raw['round'])): expected=entries_from(qualifying_by_round[int(raw['round'])])
            else:
                from ml.live.evidence import confirmed_entries
                verified=confirmed_entries(raw,started)
                if verified: expected=verified[0]
            from ml.ingestion.race_results import load as load_result
            final=load_result(raw,expected,primary_results.get(int(raw['round'])),cache=CACHE,now=started)
            if final.get('refresh_warning'): notices.append(rid+' race: '+final['refresh_warning'])
            if int(raw['round']) in primary_results: results=[r for r in results if int(r['round'])!=int(raw['round'])]
            results.append(final); primary_results[int(raw['round'])]=final
            merged={**raw,**final}; merged['QualifyingResults']=qualifying_by_round.get(int(raw['round']),[])
            indexed[(int(raw['season']),int(raw['round']))]=merged
        except Exception as exc:
            notices.append(rid+' race: '+str(exc)); log.warning('%s race result: %s',rid,str(exc))
    history=list(indexed.values())
    upcoming=sorted([r for r in calendar if r.get("time") and race_start(r)>started],key=race_start)
    completed=sorted([r for r in results if r.get("time") and race_start(r)<started],key=race_start)
    pending=recent_unclassified(calendar,results,started)
    archives=[]
    for raw in completed+pending:
        race_id=f"{season}-{int(raw['round']):02d}"
        race=normalized.get(race_id)
        if not race: continue
        with SessionLocal() as db:
            previous=db.query(Snapshot).filter_by(entity_id=race_id,kind='weekend').order_by(Snapshot.cutoff.desc(),Snapshot.id.desc()).first()
            existing=previous.payload.get('sessions',[]) if previous and previous.payload.get('is_demo') is False else []
        qrows=qualifying_by_round.get(int(raw['round']),[])
        sessions=archived_sessions(race,{'QualifyingResults':qrows} if qrows else None,existing,started.isoformat())
        save_changed(race_id,'weekend',{'race_id':race_id,'is_demo':False,'cutoff':started.isoformat(),
            'updated_at':started.isoformat(),'sessions':sessions,'source':'FastF1 / Jolpica'},started.isoformat(),'published-sessions-v1')
        practice_stages={s['type'] for s in race.get('sessions',[]) if s['type'] in {'FP1','FP2','FP3'}}
        published={s['type'] for s in existing if s.get('drivers') and s.get('status')=='published'}
        needs_qualifying=any(s['type']=='Q' for s in race.get('sessions',[])) and not {'Q1','Q2','Q3'}.issubset(published)
        if practice_stages-published or needs_qualifying: archives.append(calendar_by_round[int(raw['round'])])
    targets=refresh_targets(upcoming,pending,archives,archive_limit)
    report_path,report=choose_model(model_report or os.getenv("MODEL_REPORT_PATH"))
    if report:
        save_changed("model","metrics",report,report["created_at"],report["model_version"])
    for stage in ['FP1','FP2','FP3']:
        practice_report=active_report(stage)
        if practice_report:
            _,value=practice_report
            save_changed('model-practice-'+stage,'metrics',value,value['created_at'],value['model_version'])
    for raw in targets:
        race_id=f"{raw['season']}-{int(raw['round']):02d}"
        race=normalized.get(race_id)
        if not race: continue
        current_start=race_start(raw)
        context_cutoff=min(started,current_start-timedelta(microseconds=1))
        prior=earlier(history,context_cutoff)
        # Archive display uses that event's verified participants. A prior-season
        # Kaggle row may lack car numbers and must not block the first weekend.
        entry_source=((indexed.get((int(raw['season']),int(raw['round'])),{}).get('Results') or qualifying_by_round.get(int(raw['round']),[]))
            if current_start<started else prior[-1].get("Results",[]) if prior else [])
        entries=entries_from(entry_source) if entry_source else []
        from ml.live.evidence import confirmed_entries,attach_evidence
        if current_start>started:
            try:
                from ml.ingestion.entry_list import refresh_entries
                refresh_entries(raw,entries)
            except Exception as exc: log.warning('%s FIA entry verification unavailable: %s',race_id,type(exc).__name__)
        verified_entries=confirmed_entries(raw,now_utc()) if current_start>started else None
        entry_provenance=verified_entries[1] if verified_entries else None
        if verified_entries: entries=verified_entries[0]
        weather_context=None
        condition_weather=None
        if current_start>started:
            try:
                from ml.live.weather import capture
                weather_context=capture(raw)
                if weather_context: save_changed(race_id,'weather',weather_context,weather_context['available_at'],'weather-forecast-v1')
            except Exception as exc: log.warning('%s weather context unavailable: %s',race_id,type(exc).__name__)
            try:
                from ml.live.conditions import prepare
                condition_weather=prepare(raw)
            except Exception as exc: log.warning('%s model weather unavailable: %s',race_id,str(exc))
        circuit=circuit_summary(history,race["circuit_id"],context_cutoff)
        if circuit: save_changed(race["circuit_id"],"circuit",circuit,context_cutoff.isoformat(),"real-history-v1")
        for entry in entries:
            form=driver_form(entry,history,race["circuit_id"],context_cutoff)
            save_changed(entry["driver_id"],"form",form,context_cutoff.isoformat(),"real-form-v1")
        session_views=[]; practice={}
        for scheduled in race.get("sessions",[]):
            stage=scheduled["type"]
            session_start=datetime.fromisoformat(scheduled["started_at"].replace("Z","+00:00"))
            eligible=started >= session_start+timedelta(minutes=100 if stage=="Q" else 75)
            if stage in ["SQ","Sprint"]:
                session_views.append({**scheduled,"drivers":[],"status":"not modelled","notice":"Sprint sessions are not used by the current model."}); continue
            if not eligible:
                session_views.append({**scheduled,"drivers":[],"status":"scheduled" if started<session_start else "awaiting publication"}); continue
            try:
                if stage in ["FP1","FP2","FP3"]:
                    summary=load_practice(raw,stage)
                    if summary.get('refresh_warning'): notices.append(f"{race_id} {stage}: {summary['refresh_warning']}")
                    known={e["driver_id"] for e in entries}
                    by_code={e["abbreviation"].upper():e["driver_id"] for e in entries}
                    for row in summary["drivers"]:
                        if row["driver_id"] not in known and row["abbreviation"].upper() in by_code:
                            row["driver_id"]=by_code[row["abbreviation"].upper()]
                    summary["drivers_by_id"]={d["driver_id"]:d for d in summary["drivers"]}
                    practice[stage]=summary
                    session_views.append({k:v for k,v in summary.items() if k!="drivers_by_id"})
                    cutoff=now_utc()
                    signature=practice_inputs_signature(practice,stage,entries,condition_weather)
                    if cutoff<current_start and not stage_already_saved(race_id,stage,signature):
                        forecast=None if raw.get('Sprint') or raw.get('SprintResults') else learned_forecast(race,raw,entries,practice,history,stage,cutoff)
                        if forecast is None:
                            forecast=practice_forecast(race,entries,practice,history,stage,cutoff)
                            if raw.get('Sprint') or raw.get('SprintResults'):
                                forecast['notice']+=' Sprint format is outside the trained practice models; using the experimental baseline.'
                        if any(s.get('source')=='OpenF1' for s in practice.values()):
                            forecast['notice']+=' Uses OpenF1 filtered-lap fallback; calibration under this source switch is unverified.'
                        forecast['inputs_signature']=signature
                        attach_evidence(forecast,raw,history,entries,practice,stage,cutoff,weather_context,entry_provenance)
                        from ml.live.conditions import apply as apply_conditions
                        apply_conditions(forecast,raw,history,entries,practice,stage,cutoff,condition_weather)
                        from ml.live.baselines import attach as attach_baselines
                        attach_baselines(forecast,raw,history,cutoff)
                        Forecast.model_validate(forecast)
                        save_changed(race_id,"prediction",forecast,cutoff.isoformat(),forecast['model_version'])
                elif stage=="Q":
                    qraw=load_qualifying(raw,entries,client,qualifying_by_round.get(int(raw['round'])),strict_roster=bool(entry_provenance) or current_start<started)
                    if qraw.get('refresh_warning'): notices.append(f"{race_id} Q: {qraw['refresh_warning']}")
                    cutoff=now_utc()
                    session_views.extend(qualifying_sessions(qraw,cutoff.isoformat()))
                    qentries=entries_from(qraw["QualifyingResults"])
                    if cutoff<current_start and entries and len(qentries)<len(entries):
                        raise ValueError("Waiting for qualifying classification to cover the expected participant field")
                    qsignature=qualifying_inputs_signature(qraw,condition_weather)
                    if cutoff<current_start and not stage_already_saved(race_id,"Q",qsignature):
                        if not report: raise ValueError("No evaluated qualifying model artifact found")
                        target={**raw,**qraw}
                        forecast=qualifying_forecast(race,target,history,qentries,report_path,report,cutoff)
                        attach_evidence(forecast,target,history,qentries,practice,'Q',cutoff,weather_context,entry_provenance)
                        from ml.live.conditions import apply as apply_conditions
                        apply_conditions(forecast,target,history,qentries,practice,'Q',cutoff,condition_weather)
                        forecast['inputs_signature']=qsignature
                        from ml.live.baselines import attach as attach_baselines
                        attach_baselines(forecast,target,history,cutoff)
                        Forecast.model_validate(forecast)
                        save_changed(race_id,"prediction",forecast,cutoff.isoformat(),forecast["model_version"])
                    for entry in qentries:
                        save_changed(entry["driver_id"],"form",driver_form(entry,history,race["circuit_id"],context_cutoff),context_cutoff.isoformat(),"real-form-v1")
            except Exception as exc:
                log.warning("%s %s: %s",race_id,stage,str(exc))
                notices.append(f"{race_id} {stage}: {str(exc)}")
                if not any(s["type"] in (["Q1","Q2","Q3"] if stage=="Q" else [stage]) for s in session_views):
                    session_views.append({**scheduled,"drivers":[],"status":"awaiting publication","notice":"Timing is unavailable or failed source validation. The configured free sources are retried automatically."})
        weekend={"race_id":race_id,"is_demo":False,"cutoff":context_cutoff.isoformat(),"updated_at":now_utc().isoformat(),"sessions":session_views,"source":"FastF1 / OpenF1 / Jolpica"}
        save_changed(race_id,"weekend",weekend,now_utc().isoformat(),"published-sessions-v1")
    # Score only forecasts actually recorded before race start; never manufacture past predictions.
    for raw in results:
        race_id=f"{raw['season']}-{int(raw['round']):02d}"
        race=normalized.get(race_id)
        if not race or race_start(raw)>now_utc(): continue
        classification=raw.get("Results",[])
        if not classification or sum(int(r["position"])==1 for r in classification)!=1: continue
        with SessionLocal() as db:
            r=db.get(Race,race_id); r.payload={**r.payload,"status":"completed"}; db.commit()
            records=db.query(Snapshot).filter_by(entity_id=race_id,kind="prediction").filter(Snapshot.cutoff<r.scheduled_at).all()
            predictions=[v.payload for v in records if v.payload.get("is_demo") is False]
            last=db.query(Snapshot).filter_by(entity_id=race_id,kind="evaluation").order_by(Snapshot.cutoff.desc()).first()
            signature=digest({"results":classification,"forecasts":[p["cutoff"] for p in predictions]})
            if last and last.payload.get("classification_signature")==signature: continue
        evaluation=score_forecasts(predictions,classification,now_utc().isoformat())
        evaluation['source']=raw.get('source','Jolpica')+' published classification'
        evaluation['classification_observed_at']=raw.get('observed_at',now_utc().isoformat())
        evaluation['classification_source_url']=raw.get('source_url')
        evaluation.update({"race_id":race_id,"classification_signature":signature,
                           "results":[{"driver_id":r["Driver"]["driverId"],"name":r["Driver"].get("givenName","")+" "+r["Driver"].get("familyName",""),"position":int(r["position"]),"status":r.get("status","")} for r in classification]})
        save_changed(race_id,"evaluation",evaluation,now_utc().isoformat(),"published-result-v1")
    finish=now_utc()
    state={"status":"ok" if not notices else "partial","last_successful_refresh":finish.isoformat(),"last_attempt":started.isoformat(),
           "interval_seconds":interval,"next_check_at":(finish+timedelta(seconds=interval)).isoformat(),"notice":"Free post-session updates: FastF1 with OpenF1 fallback. OpenF1 becomes free 30 minutes after session end; pages refresh every minute. In-session streaming is not configured.","data_mode":"post-session","providers":["FastF1","OpenF1","Jolpica"],
           "pending":notices,"model_version":report.get("model_version") if report else None,"next_race_id":normalized.get(f"{season}-{int(upcoming[0]['round']):02d}",{}).get("race_id") if upcoming else None}
    set_state(state); return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop",action="store_true")
    parser.add_argument("--interval",type=int,default=int(os.getenv("REFRESH_INTERVAL_SECONDS","300")))
    parser.add_argument("--season",type=int)
    parser.add_argument("--model-report",type=Path)
    parser.add_argument("--archive-limit",type=int,default=1,help="Maximum completed weekends to backfill per refresh (default 1)")
    args=parser.parse_args()
    if args.interval<300: parser.error("Use an interval of at least 300 seconds to respect free upstream sources")
    if not 0<=args.archive_limit<=30: parser.error("Archive limit must be between 0 and 30")
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    # Pin the evaluated artifact for the lifetime of this worker; training never occurs here.
    model_path,_=choose_model(args.model_report or os.getenv("MODEL_REPORT_PATH"))
    while True:
        try:
            with worker_lock():
                state=refresh_once(args.season,model_path,args.interval,args.archive_limit)
            print(json.dumps(state),flush=True)
        except Exception as exc:
            initialize()
            set_state({"status":"error","last_attempt":now_utc().isoformat(),"interval_seconds":args.interval,"notice":str(exc)})
            log.exception("Source refresh failed")
            if not args.loop: raise
        if not args.loop: break
        try:
            from scripts.maintenance import run_due
            result=run_due()
            if result.get('status')=='error': log.warning('%s',result['notice'])
            from ml.live.operations import inspect as inspect_operations,record_alerts
            with SessionLocal() as db: record_alerts(db,inspect_operations(db))
        except Exception: log.exception('Maintenance check failed; source refresh will continue')
        wait_for_next_check(args.interval)


if __name__=="__main__":
    main()
