import copy
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
from ml.ingestion.openf1_sessions import match_session,filtered_summary
from ml.live.refresh import practice_inputs_signature,load_practice
from ml.ingestion.openf1_sessions import ROOT

UTC=timezone.utc
RAW={'season':'2026','round':'18','Circuit':{'Location':{'country':'USA'}},
    'FirstPractice':{'date':'2026-10-23','time':'17:30:00Z'}}
SESSION={'session_key':1,'meeting_key':2,'year':2026,'country_name':'United States','session_name':'Practice 1',
    'date_start':'2026-10-23T17:30:00Z','date_end':'2026-10-23T18:30:00Z','is_cancelled':False}
NOW=datetime(2026,10,23,19,30,tzinfo=UTC)


def fixture():
    def record(**extra): return {'session_key':1,'meeting_key':2,**extra}
    data={'drivers':[record(driver_number=i,name_acronym=str(i),first_name='Driver',last_name=str(i),full_name='Driver '+str(i),team_name='Team',team_colour='ffffff') for i in (1,2)],
        'laps':[],'stints':[],'pit':[],'race_control':[record(date='2026-10-23T17:30:00Z',category='Flag',scope='Track',sector=None,flag='GREEN')],
        'session_result':[record(driver_number=i,duration=90+i) for i in (1,2)]}
    for driver in (1,2):
        data['stints'].append(record(driver_number=driver,stint_number=1,lap_start=1,lap_end=10,compound='MEDIUM',tyre_age_at_start=0))
        for lap in range(1,9):
            duration=90+driver+lap*.1
            start=datetime(2026,10,23,17,30,tzinfo=UTC)+timedelta(seconds=100*lap)
            data['laps'].append(record(driver_number=driver,lap_number=lap,date_start=start.isoformat(),lap_duration=duration,
                duration_sector_1=30,duration_sector_2=30,duration_sector_3=duration-60,is_pit_out_lap=lap==1,
                segments_sector_1=[2048],segments_sector_2=[2049],segments_sector_3=[2051]))
    return data


class OpenF1Tests(unittest.TestCase):
    def test_primary_import_failure_still_uses_free_fallback(self):
        data={'race_id':'2026-18','type':'FP1','source':'OpenF1','drivers':[{'driver_id':'a','best_lap_ms':90000}]}
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory,patch('ml.live.refresh.CACHE',Path(directory)),patch.dict('sys.modules',{'fastf1':None}),patch('ml.ingestion.openf1_sessions.load_practice',return_value=data) as fallback:
            result=load_practice(RAW,'FP1')
            fallback.assert_called_once(); self.assertEqual(result['source'],'OpenF1')

    def test_provider_outage_keeps_last_good_data_and_retries_expired_cache(self):
        raw={**RAW,'date':'2026-10-25','time':'20:00:00Z'}
        cached={'race_id':'2026-18','type':'FP1','summary_version':'practice-stats-v1','source':'OpenF1',
            'quality_policy':'published-best-v2','observed_at':'2026-10-23T19:00:00+00:00',
            'drivers':[{'driver_id':'a','best_lap_ms':90000}]}
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            path=Path(directory)/'2026-18-FP1.json'; path.write_text(json.dumps(cached))
            with patch('ml.live.refresh.CACHE',Path(directory)),patch('ml.live.refresh.now_utc',return_value=NOW),patch('ml.ingestion.openf1_sessions.load_practice',side_effect=ValueError('upstream outage')) as source:
                result=load_practice(raw,'FP1')
                source.assert_called_once()
                self.assertEqual(result['drivers'],cached['drivers']); self.assertIn('last successful',result['refresh_warning'])
                self.assertEqual(json.loads(path.read_text()),cached)

    def test_forecast_refresh_depends_on_changed_eligible_inputs(self):
        sessions={'FP1':{'source':'OpenF1','observed_at':'old','quality_policy':'v1','drivers':[{'best_lap_ms':90000}]}}
        first=practice_inputs_signature(sessions,'FP1')
        sessions['FP1']['observed_at']='new'
        sessions['FP2']={'drivers':[{'best_lap_ms':1}]}
        self.assertEqual(first,practice_inputs_signature(sessions,'FP1'))
        sessions['FP1']['drivers'][0]['best_lap_ms']=91000
        self.assertNotEqual(first,practice_inputs_signature(sessions,'FP1'))

    def test_matches_race_stage_and_time_not_latest_session(self):
        self.assertEqual(match_session([SESSION],RAW,'FP1',NOW),SESSION)
        for changes in [{'country_name':'Bahrain'},{'session_name':'Practice 2'},{'year':2025},{'date_start':'2026-10-20T17:30:00Z'},{'is_cancelled':True}]:
            with self.assertRaises(ValueError): match_session([{**SESSION,**changes}],RAW,'FP1',NOW)
        with self.assertRaises(ValueError): match_session([SESSION,SESSION],RAW,'FP1',NOW)

    def test_does_not_request_paid_live_window(self):
        with self.assertRaises(ValueError): match_session([SESSION],RAW,'FP1',datetime(2026,10,23,18,59,tzinfo=UTC))
        match_session([SESSION],RAW,'FP1',datetime(2026,10,23,19,tzinfo=UTC))

    def test_real_summaries_preserve_units_and_missing_accuracy_flags(self):
        data=fixture(); summary=filtered_summary(RAW,'FP1',SESSION,data,NOW)
        self.assertEqual(summary['source'],'OpenF1'); self.assertEqual(summary['race_id'],'2026-18')
        self.assertEqual([r['lap_count'] for r in summary['drivers']],[7,7])
        self.assertEqual(summary['drivers'][0]['best_lap_ms'],91000)
        self.assertEqual(summary['drivers'][0]['representative_lap_ms'],91500)
        self.assertIn('accuracy flags are unavailable',summary['notice'])
        self.assertEqual(summary['observed_at'],NOW.isoformat())

    def test_pit_deleted_inconsistent_and_non_green_laps_excluded(self):
        data=fixture()
        data['pit'].append({'session_key':1,'meeting_key':2,'driver_number':1,'lap_number':3})
        data['race_control'].append({'session_key':1,'meeting_key':2,'date':'2026-10-23T18:20:00Z','category':'Other',
            'message':'CAR 1 (ONE) TIME 1:31.200 DELETED - TRACK LIMITS LAP 2'})
        data['laps'][3]['duration_sector_3']=1
        summary=filtered_summary(RAW,'FP1',SESSION,data,NOW)
        one=next(d for d in summary['drivers'] if d['abbreviation']=='1')
        self.assertEqual(one['lap_count'],4); self.assertEqual(one['best_lap_ms'],91000)
        yellow=copy.deepcopy(data)
        yellow['race_control'].append({'session_key':1,'meeting_key':2,'date':'2026-10-23T17:30:01Z','category':'Flag','scope':'Track','sector':None,'flag':'RED'})
        with self.assertRaises(ValueError): filtered_summary(RAW,'FP1',SESSION,yellow,NOW)

    def test_wrong_session_duplicates_future_laps_and_missing_green_rejected(self):
        for field in ['laps','drivers','pit','stints','race_control','session_result']:
            data=fixture()
            if not data[field]: data[field].append({'session_key':9,'meeting_key':2})
            else: data[field][0]['session_key']=9
            with self.assertRaises(ValueError): filtered_summary(RAW,'FP1',SESSION,data,NOW)
        data=fixture(); data['laps'].append(copy.deepcopy(data['laps'][0]))
        with self.assertRaises(ValueError): filtered_summary(RAW,'FP1',SESSION,data,NOW)
        data=fixture(); data['race_control']=[]
        with self.assertRaises(ValueError): filtered_summary(RAW,'FP1',SESSION,data,NOW)
        data=fixture()
        for lap in data['laps']: lap['date_start']='2026-10-23T20:00:00Z'
        with self.assertRaises(ValueError): filtered_summary(RAW,'FP1',SESSION,data,NOW)


if __name__=='__main__': unittest.main()
