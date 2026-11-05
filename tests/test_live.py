import copy
import unittest
from datetime import datetime,timezone
from ml.live.analytics import practice_forecast,score_forecasts,circuit_summary
from ml.live.refresh import schedule_sessions,qualifying_forecast,wait_for_next_check,archived_sessions

UTC=timezone.utc
RACE={"race_id":"test-race","scheduled_at":"2026-11-01T12:00:00Z"}
ENTRIES=[{"driver_id":d,"name":d,"abbreviation":d.upper(),"number":i+1,"team":"team","color":"#888888"} for i,d in enumerate(["a","b"])]


def session(gap_a,gap_b,date="2026-10-30T12:00:00Z"):
    rows=[{"driver_id":d,"best_lap_ms":90000+g,"gap_ms":g} for d,g in [("a",gap_a),("b",gap_b)]]
    return {"drivers":rows,"drivers_by_id":{r["driver_id"]:r for r in rows},"observed_at":date}


class LiveTests(unittest.TestCase):
    def test_archive_keeps_practice_and_publishes_qualifying(self):
        race={'sessions':[{'type':'FP1'},{'type':'FP2'},{'type':'Q'}]}
        practice={'type':'FP1','status':'published','drivers':[{'driver_id':'a'}]}
        q={'QualifyingResults':[{'position':'1','number':'1','Driver':{'driverId':'a'},'Constructor':{'constructorId':'t'},'Q1':'1:20.000'}]}
        sessions=archived_sessions(race,q,[practice],'2026-11-02T00:00:00Z')
        self.assertEqual([s['type'] for s in sessions],['FP1','FP2','Q1','Q2','Q3'])
        self.assertEqual(sessions[0],practice)
        self.assertEqual(sessions[1]['status'],'archive pending')
        self.assertEqual(sessions[2]['drivers'][0]['best_lap_ms'],80000)
        self.assertIsNone(sessions[3]['drivers'][0]['best_lap_ms'])

    def test_refresh_deadline_recovers_from_clock_jump(self):
        from datetime import timedelta
        current=[datetime(2026,10,13,20,tzinfo=UTC)]
        waits=[]
        def sleep(seconds):
            waits.append(seconds)
            current[0]+=timedelta(hours=8)
        wait_for_next_check(900,clock=lambda:current[0],sleep=sleep)
        self.assertEqual(len(waits),1)
        self.assertLessEqual(waits[0],30)

    def test_after_fp1_cannot_use_fp2_or_fp3(self):
        cutoff=datetime(2026,10,30,13,tzinfo=UTC)
        first=practice_forecast(RACE,ENTRIES,{"FP1":session(0,1000)},[],"FP1",cutoff)
        extra={"FP1":session(0,1000),"FP2":session(10000,0,"2026-10-31T12:00:00Z")}
        second=practice_forecast(RACE,ENTRIES,extra,[],"FP1",cutoff)
        self.assertEqual(first,second)
        self.assertEqual(len(first["evidence"]),1)
        self.assertAlmostEqual(sum(d["probability"] for d in first["drivers"]),1)
        self.assertFalse(first["is_demo"])
        self.assertFalse(first["calibrated"])

    def test_late_source_and_after_race_publication_rejected(self):
        with self.assertRaises(ValueError):
            practice_forecast(RACE,ENTRIES,{"FP1":session(0,1000)},[],"FP1",datetime(2026,11,2,tzinfo=UTC))
        with self.assertRaises(ValueError):
            practice_forecast(RACE,ENTRIES,{"FP1":session(0,1000,"2026-10-31T12:00:00Z")},[],"FP1",datetime(2026,10,30,tzinfo=UTC))

    def test_unusable_session_is_not_a_fake_forecast(self):
        data=session(0,1000)
        for row in data["drivers"]: row["best_lap_ms"]=None
        with self.assertRaises(ValueError):
            practice_forecast(RACE,ENTRIES,{"FP1":data},[],"FP1",datetime(2026,10,30,13,tzinfo=UTC))

    def test_scoring_preserves_original_prediction(self):
        p=practice_forecast(RACE,ENTRIES,{"FP1":session(0,1000)},[],"FP1",datetime(2026,10,30,13,tzinfo=UTC))
        original=copy.deepcopy(p)
        classification=[{"position":"1","Driver":{"driverId":"a","givenName":"Driver","familyName":"A"}},{"position":"2","Driver":{"driverId":"b"}}]
        result=score_forecasts([p],classification,"2026-11-01T15:00:00Z")
        self.assertTrue(result["forecasts"][0]["correct"])
        self.assertEqual(p,original)
        self.assertGreater(result["forecasts"][0]["log_loss"],0)
        empty=score_forecasts([],classification,"2026-11-01T15:00:00Z")
        self.assertEqual(empty["forecasts"],[])
        self.assertIn("No pre-race forecast",empty["notice"])

    def test_calendar_does_not_invent_fp2_on_sprint_weekend(self):
        raw={"FirstPractice":{"date":"2026-10-23","time":"18:00:00Z"},"SprintQualifying":{"date":"2026-10-23","time":"21:00:00Z"},"Qualifying":{"date":"2026-10-24","time":"21:00:00Z"}}
        self.assertEqual([s["type"] for s in schedule_sessions(raw)],["FP1","SQ","Q"])

    def test_qualifying_publication_after_start_is_blocked_before_loading_model(self):
        with self.assertRaises(ValueError):
            qualifying_forecast(RACE,{},[],[],None,{},datetime(2026,11,2,tzinfo=UTC))


if __name__=="__main__": unittest.main()
