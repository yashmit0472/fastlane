import copy
import json
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from apps.api import main
from apps.api.database import Base, Race, SystemState, save_snapshot
from apps.api.contracts import Forecast

FIXTURE=json.loads((Path(__file__).resolve().parents[1]/"data/sample/showcase.json").read_text(encoding="utf-8"))


class ApiTest(unittest.TestCase):
    def test_current_race_and_next_race_are_distinct_while_results_pending(self):
        from datetime import datetime,timezone
        from unittest.mock import patch
        with main.SessionLocal() as db:
            for rid,date,round_number in [('2026-19','2026-11-01T20:00:00Z',19),('2026-20','2026-11-08T17:00:00Z',20)]:
                p={**FIXTURE['race'],'race_id':rid,'scheduled_at':date,'round':round_number,'is_demo':False,'status':'scheduled'}
                db.add(Race(race_id=rid,season=2026,round=round_number,scheduled_at=date,is_demo=False,payload=p))
            db.commit()
        with patch('apps.api.main.datetime') as clock:
            clock.now.return_value=datetime(2026,11,1,21,tzinfo=timezone.utc)
            self.assertEqual(self.client.get('/api/races/current').json()['race_id'],'2026-19')
            self.assertEqual(self.client.get('/api/races/next').json()['race_id'],'2026-20')
            self.assertEqual(self.client.get('/api/races/2026-19').json()['status'],'awaiting_classification')
            self.assertEqual(self.client.get('/api/races/2026-19/prediction').status_code,404)
            with main.SessionLocal() as db:
                race=db.get(Race,'2026-19'); race.payload={**race.payload,'status':'completed'}; db.commit()
            self.assertEqual(self.client.get('/api/races/current').json()['race_id'],'2026-20')

    def test_readiness_distinguishes_liveness_and_model_failure(self):
        from unittest.mock import patch
        with patch('ml.live.operations.inspect',return_value={'ready':False,'status':'unavailable','blockers':['Missing model'],'warnings':[]}):
            self.assertEqual(self.client.get('/health').status_code,200)
            self.assertEqual(self.client.get('/ready').status_code,503)
            self.assertFalse(self.client.get('/api/system/operations').json()['ready'])
        with patch('ml.live.operations.inspect',return_value={'ready':True,'status':'ok','blockers':[],'warnings':[]}):
            self.assertEqual(self.client.get('/ready').status_code,200)

    def test_dead_worker_is_reported_stale_without_rewriting_saved_state(self):
        from datetime import datetime,timedelta,timezone
        with main.SessionLocal() as db:
            db.add(SystemState(key='refresh',payload={'status':'ok','interval_seconds':300,'last_attempt':(datetime.now(timezone.utc)-timedelta(minutes=12)).isoformat()})); db.commit()
        self.assertEqual(self.client.get('/api/system/status').json()['status'],'stale')
        with main.SessionLocal() as db: self.assertEqual(db.get(SystemState,'refresh').payload['status'],'ok')

    def setUp(self):
        self.original=main.SessionLocal
        engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        Base.metadata.create_all(engine)
        main.SessionLocal=sessionmaker(bind=engine)
        self.client=TestClient(main.app)
        with main.SessionLocal() as db:
            race=FIXTURE["race"]
            db.add(Race(race_id=race["race_id"],season=race["season"],round=race["round"],scheduled_at=race["scheduled_at"],is_demo=True,payload=race))
            save_snapshot(db,race["race_id"],"prediction","showcase-v1",FIXTURE["prediction"]["cutoff"],FIXTURE["prediction"])
            db.commit()

    def tearDown(self):
        main.SessionLocal=self.original

    def test_health_unknown_and_missing(self):
        self.assertEqual(self.client.get("/health").status_code,200)
        self.assertEqual(self.client.get("/api/races/unknown/prediction").status_code,404)
        self.assertEqual(self.client.get("/api/races/showcase-singapore/weekend").status_code,404)
        self.assertEqual(self.client.get("/api/model/metrics").json()["status"],"untrained")

    def test_demo_never_labeled_next_real_race(self):
        self.assertEqual(self.client.get('/api/races/current').status_code,404)
        self.assertEqual(self.client.get("/api/races/next").status_code,404)
        self.assertEqual(self.client.get("/api/races").json()["races"],[])
        self.assertEqual(self.client.get("/api/races/showcase-singapore").status_code,404)
        self.assertEqual(self.client.get("/api/races/showcase-singapore/prediction").status_code,404)
        self.assertEqual(self.client.get('/api/races/showcase-singapore/report-card').status_code,404)
        self.assertEqual(self.client.get('/api/races/showcase-singapore/weather').status_code,404)
        self.assertEqual(self.client.get('/api/performance').json()['races_with_scored_forecasts'],0)

    def test_real_future_schedule_preferred(self):
        with main.SessionLocal() as db:
            race={**FIXTURE["race"],"race_id":"future","scheduled_at":"2099-01-01T12:00:00Z","is_demo":False}
            db.add(Race(race_id="future",season=2099,round=1,scheduled_at=race["scheduled_at"],is_demo=False,payload=race))
            db.commit()
        self.assertEqual(self.client.get("/api/races/next").json()["race_id"],"future")

    def test_forecast_contract_and_sum(self):
        value=copy.deepcopy(FIXTURE["prediction"])
        self.assertAlmostEqual(sum(d["probability"] for d in value["drivers"]),1)
        self.assertEqual(len(value["drivers"]),20)
        invalid=copy.deepcopy(value)
        invalid["cutoff"]=invalid["race_start"]
        with self.assertRaises(ValueError):Forecast.model_validate(invalid)

    def test_real_forecasts_history_and_evaluation_waiting(self):
        race={**FIXTURE["race"],"race_id":"real","is_demo":False}
        forecast={**FIXTURE["prediction"],"race_id":"real","is_demo":False,"stage":"FP1"}
        with main.SessionLocal() as db:
            db.add(Race(race_id="real",season=race["season"],round=race["round"],scheduled_at=race["scheduled_at"],is_demo=False,payload=race))
            save_snapshot(db,"real","prediction","test-v1",forecast["cutoff"],forecast);db.commit()
        self.assertEqual(self.client.get("/api/races/real/prediction").status_code,200)
        self.assertEqual(len(self.client.get("/api/races/real/predictions").json()["predictions"]),1)
        self.assertEqual(self.client.get("/api/races/real/evaluation").json()["status"],"waiting")
        card=self.client.get('/api/races/real/report-card')
        self.assertEqual(card.status_code,200)
        self.assertEqual(card.json()['status'],'awaiting classification')

    def test_demo_fact_snapshots_rejected_and_state_visible(self):
        with main.SessionLocal() as db:
            save_snapshot(db,"marina_bay","circuit","demo",FIXTURE["prediction"]["cutoff"],FIXTURE["circuit"]);db.commit()
        self.assertEqual(self.client.get("/api/circuits/marina_bay/history").status_code,404)
        self.assertEqual(self.client.get("/api/system/status").json()["is_demo"],False)
        invalid=copy.deepcopy(FIXTURE["prediction"])
        invalid["drivers"][0]["probability"] = .9
        with self.assertRaises(ValueError):Forecast.model_validate(invalid)

    def test_immutable_idempotent_snapshot(self):
        with main.SessionLocal() as db:
            saved=save_snapshot(db,"showcase-singapore","prediction","showcase-v1",FIXTURE["prediction"]["cutoff"],FIXTURE["prediction"])
            again=save_snapshot(db,"showcase-singapore","prediction","showcase-v1",FIXTURE["prediction"]["cutoff"],FIXTURE["prediction"])
            self.assertEqual(saved.id,again.id)
            with self.assertRaises(ValueError):save_snapshot(db,"showcase-singapore","prediction","showcase-v1",FIXTURE["prediction"]["cutoff"],{"changed":True})

    def test_recorded_performance_scores_one_latest_snapshot_per_stage(self):
        race={**FIXTURE['race'],'race_id':'recorded','is_demo':False}
        p={**copy.deepcopy(FIXTURE['prediction']),'race_id':'recorded','is_demo':False,'stage':'Q'}
        result={'results':[{'driver_id':d['driver_id'],'name':d['name'],'position':i+1} for i,d in enumerate(p['drivers'])]}
        with main.SessionLocal() as db:
            db.add(Race(race_id='recorded',season=race['season'],round=race['round'],scheduled_at=race['scheduled_at'],is_demo=False,payload=race))
            save_snapshot(db,'recorded','prediction','one',p['cutoff'],p)
            save_snapshot(db,'recorded','prediction','two',p['cutoff'],p)
            save_snapshot(db,'recorded','evaluation','result',race['scheduled_at'],result);db.commit()
        card=self.client.get('/api/races/recorded/report-card').json()
        self.assertEqual(card['status'],'scored');self.assertEqual(len(card['stages']),1)
        summary=self.client.get('/api/performance').json()
        self.assertEqual(summary['races_with_scored_forecasts'],1)
        self.assertEqual(summary['groups'][0]['metrics']['races'],1)


if __name__ == "__main__":
    unittest.main()
