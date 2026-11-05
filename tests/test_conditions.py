import copy
import unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import pandas as pd
from ml.ingestion.condition_forecasts import parse
from ml.features.conditions import enrich,reliability,nonfinish
from ml.live.conditions import apply
from ml.live.explain import family

UTC=timezone.utc
def race(date='2025-03-16'):
    return {'season':'2025','round':'1','date':date,'time':'05:00:00Z','Circuit':{'circuitId':'test','Location':{'lat':'-37.8','long':'144.9'}}}

def forecast():
    payload={'hourly':{'time':['2025-03-16T05:00'],'temperature_2m_previous_day3':[20.0],'precipitation_previous_day3':[1.0],'wind_speed_10m_previous_day3':[18.0],'relative_humidity_2m_previous_day3':[60.0]}}
    return parse(payload,race(),datetime(2026,10,25,tzinfo=UTC))


class ConditionsTest(unittest.TestCase):
    def test_fixed_lead_is_not_retrospective_actual_weather(self):
        f=forecast(); self.assertEqual(f['precipitation_mm'],1)
        self.assertEqual(f['available_at'],'2025-03-13T11:00:00+00:00')
        self.assertEqual(f['retrieved_at'],'2026-10-25T00:00:00+00:00')
        with self.assertRaises(ValueError): parse({'hourly':{'time':['2025-03-16T05:00']}},race(),datetime.now(UTC))

    def test_future_forecast_wrong_event_and_coordinate_rejected(self):
        frame=pd.DataFrame([{'driver_id':'a','constructor_id':'team','recent_finish':2,'recent_win_rate':.2,'team_recent_finish':3,'qualifying_gap_s':.1}])
        cutoff=datetime(2025,3,15,tzinfo=UTC); f=forecast()
        base=enrich(frame,race(),[],f,cutoff,{})
        wet=copy.deepcopy(f); wet['precipitation_mm']=4
        changed=enrich(frame,race(),[],wet,cutoff,{})
        self.assertNotEqual(base.rain_x_recent_finish.iloc[0],changed.rain_x_recent_finish.iloc[0])
        for key,value in [('available_at','2025-03-17T00:00:00Z'),('race_id','2025-02'),('latitude',50),('model','gfs_global')]:
            bad=copy.deepcopy(f); bad[key]=value
            with self.assertRaises(ValueError): enrich(frame,race(),[],bad,cutoff,{})

    def test_lapped_finishers_are_not_dnfs_and_unknown_remains_unknown(self):
        self.assertEqual(nonfinish({'status_id':'11'},{'11':'+1 Lap'}),0)
        self.assertEqual(nonfinish({'status':'Engine'},{}),1)
        self.assertIsNone(nonfinish({'status_id':'unknown'},{}))

    def test_reliability_cannot_read_target_or_future_results(self):
        def event(date,status):
            r=race(date); r['Results']=[{'Driver':{'driverId':'a'},'Constructor':{'constructorId':'team'},'status':status}]; return r
        cutoff=datetime(2025,3,15,tzinfo=UTC)
        past=event('2025-03-01','Engine'); target=event('2025-03-16','Finished'); future=event('2025-03-30','Engine')
        a=reliability(race(),[past],'a','team',cutoff,{})
        self.assertEqual(a,reliability(race(),[past,target,future],'a','team',cutoff,{})); self.assertEqual(a['driver_status_samples'],1)

    def test_failed_validation_gate_preserves_probabilities(self):
        p={'drivers':[],'model_version':'base'}
        with patch('ml.live.conditions.active',return_value=(None,{'enabled':False,'model_version':'candidate'})):
            self.assertFalse(apply(p,race(),[],[],{},'FP1',datetime(2025,3,15,tzinfo=UTC),None))
        self.assertEqual(p['model_version'],'base'); self.assertFalse(p['conditions_context']['used_by_model'])

    def test_weather_associations_have_their_own_family(self):
        self.assertIn('weather',family('numeric__rain_x_recent_finish').lower())
        self.assertIn('nonfinish',family('numeric__driver_nonfinish_rate').lower())


if __name__=='__main__': unittest.main()
