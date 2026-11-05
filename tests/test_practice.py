import copy
import unittest
from datetime import datetime,timezone
from unittest.mock import patch
import pandas as pd
from ml.features.practice import features_for_practice,numeric,decode_archive
from ml.training.practice import validate_frame
from ml.live.practice_model import learned_forecast

UTC=timezone.utc
ENTRIES=[{'driver_id':d,'constructor_id':'team','abbreviation':d.upper()} for d in ['a','b']]


def event(year=2025):
    return {'season':str(year),'round':'1','date':f'{year}-05-03','time':'14:00:00Z','Circuit':{'circuitId':'test'},
        'FirstPractice':{'date':f'{year}-05-01'},
        'Results':[{'Driver':{'driverId':d,'code':d.upper()},'Constructor':{'constructorId':'team'},'position':str(i+1),'grid':'1'} for i,d in enumerate(['a','b'])]}


def session(stage='FP1'):
    return {'race_id':'2025-01','type':stage,'observed_at':'2025-05-01T12:00:00Z','ended_at':'2025-05-01T12:00:00Z',
        'drivers':[{'driver_id':d,'best_lap_ms':90000+i*1000,'representative_lap_ms':91000+i*1000,'lap_count':8} for i,d in enumerate(['a','b'])]}


class PracticeTests(unittest.TestCase):
    def test_uniform_top_pick_is_not_leaked_from_result_order(self):
        from ml.training.evaluate import evaluate
        frame=pd.DataFrame({'race_id':['r','r'],'driver_id':['a','b'],'target':[1,0]})
        first=evaluate(frame,[1,1])[0]
        second=evaluate(frame.iloc[::-1].reset_index(drop=True),[1,1])[0]
        self.assertEqual(first['top1_accuracy'],.5)
        self.assertEqual(first,second)

    def test_stage_cannot_read_later_sessions_qualifying_or_outcomes(self):
        race=event(); cutoff=datetime(2025,5,1,13,tzinfo=UTC); sessions={'FP1':session()}
        original=features_for_practice(race,[event(2024)],ENTRIES,sessions,'FP1',cutoff)
        changed=copy.deepcopy(race)
        changed['Results'][0]['position']='2'; changed['Results'][1]['position']='1'
        changed['QualifyingResults']=[{'position':'1'}]
        later=session(); later['observed_at']='2025-05-02T12:00:00Z'; later['drivers'][0]['best_lap_ms']=1000
        sessions.update(FP2=later,FP3=later)
        self.assertEqual(original,features_for_practice(changed,[event(2024),changed,event(2026)],ENTRIES,sessions,'FP1',cutoff))
        self.assertTrue(all(not k.startswith(('fp2_','fp3_')) for k in numeric('FP1')))

    def test_missing_previous_session_remains_missing(self):
        rows=features_for_practice(event(),[],ENTRIES,{'FP2':session('FP2')},'FP2',datetime(2025,5,1,13,tzinfo=UTC))
        self.assertIsNone(rows[0]['fp1_best_gap_pct']); self.assertEqual(rows[0]['fp1_available'],0)
        self.assertEqual(rows[0]['fp2_best_gap_pct'],0)

    def test_observation_and_race_boundaries(self):
        for cutoff in [datetime(2025,5,1,11,tzinfo=UTC),datetime(2025,5,4,tzinfo=UTC)]:
            with self.assertRaises(ValueError): features_for_practice(event(),[],ENTRIES,{'FP1':session()},'FP1',cutoff)
        race=event(); race['Sprint']={}
        race['Sprint']={'date':'2025-05-02'}
        with self.assertRaises(ValueError): features_for_practice(race,[],ENTRIES,{'FP1':session()},'FP1',datetime(2025,5,1,13,tzinfo=UTC))

    def test_incomplete_field_not_replaced_with_synthetic_pace(self):
        data=session(); data['drivers']=data['drivers'][:1]
        with self.assertRaises(ValueError): features_for_practice(event(),[],ENTRIES,{'FP1':data},'FP1',datetime(2025,5,1,13,tzinfo=UTC))

    def test_another_weekends_session_cannot_be_joined(self):
        data=session(); data['race_id']='2025-02'
        with self.assertRaisesRegex(ValueError,'different race'):
            features_for_practice(event(),[],ENTRIES,{'FP1':data},'FP1',datetime(2025,5,1,13,tzinfo=UTC))

    def test_training_rejects_a_qualifying_column(self):
        rows=features_for_practice(event(),[],ENTRIES,{'FP1':session()},'FP1',datetime(2025,5,1,13,tzinfo=UTC),include_target=True)
        frame=pd.DataFrame(rows); validate_frame(frame,'FP1')
        frame['qualifying_position']=[1,2]
        with self.assertRaises(ValueError): validate_frame(frame,'FP1')

    def test_training_excludes_a_later_dns_roster_mismatch(self):
        race=event(); race['QualifyingResults']=[{'Driver':{'driverId':d}} for d in ['a','b','c']]
        with self.assertRaisesRegex(ValueError,'roster'):
            features_for_practice(race,[],ENTRIES,{'FP1':session()},'FP1',datetime(2025,5,1,13,tzinfo=UTC),include_target=True)

    def test_archive_flags_and_seconds_are_checked(self):
        data={'time':[90.,91.,92.,93.],'drv':['A']*4,'lSD':['2025-05-01T11:00:00']*4,
            'iacc':[True,False,True,True],'del':[False,False,True,False],'status':['1','1','1','2'],
            'pin':[None]*4,'pout':[None]*4}
        summary=decode_archive(data,event(),'FP1')
        self.assertEqual(summary['drivers'][0]['best_lap_ms'],90000)
        self.assertEqual(summary['drivers'][0]['lap_count'],1)
        data['time']=[90000.]*4
        with self.assertRaises(ValueError): decode_archive(data,event(),'FP1')

    def test_model_must_exist_before_forecast(self):
        report={'trained_until':'2024-12-01T00:00:00Z','created_at':'2025-05-02T00:00:00Z'}
        race={'scheduled_at':'2025-05-03T14:00:00Z'}
        with patch('ml.live.practice_model.active_report',return_value=(None,report)):
            with self.assertRaisesRegex(ValueError,'created'):
                learned_forecast(race,event(),ENTRIES,{'FP1':session()},[],'FP1',datetime(2025,5,1,13,tzinfo=UTC))


if __name__=='__main__': unittest.main()
