import copy
import json
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session
from apps.api.database import Base,Race,Snapshot,SystemState
from ml.ingestion.race_results import normalize,load
from ml.ingestion.openf1_sessions import match_session
from ml.live.baselines import attach
from ml.live.reportcards import race_card,overall
from ml.live.operations import inspect
from scripts.backup import backup,restore,verify

UTC=timezone.utc
RAW={'season':'2026','round':'18','date':'2026-10-25','time':'20:00:00Z','Circuit':{'circuitId':'test','Location':{'country':'USA'}}}
NOW=datetime(2026,10,26,tzinfo=UTC)
SESSION={'year':2026,'session_key':10,'meeting_key':20,'session_name':'Race','country_name':'United States','date_start':'2026-10-25T20:00:00Z','date_end':'2026-10-25T22:00:00Z'}
ENTRIES=[{'driver_id':str(i),'abbreviation':f'D{i}','name':f'Driver {i}','number':i,'constructor_id':'team','team':'Team'} for i in range(1,21)]
DRIVERS=[{'session_key':10,'meeting_key':20,'driver_number':i,'name_acronym':f'D{i}'} for i in range(1,21)]
RESULTS=[{'session_key':10,'meeting_key':20,'driver_number':i,'position':i,'dnf':i>18,'dns':False,'dsq':False,'number_of_laps':56 if i<19 else 40} for i in range(1,21)]

def final(): return normalize(RAW,ENTRIES,SESSION,DRIVERS,RESULTS,NOW)

class ReleaseTests(unittest.TestCase):
    def test_published_result_adapter_does_not_infer_retirement_order(self):
        import pandas as pd
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from ml.ingestion.race_results import fastf1
        records=pd.DataFrame([{'Abbreviation':f'D{i}','DriverNumber':str(i),'Position':float(i),'GridPosition':float(21-i),'Status':'Retired' if i==20 else 'Finished','Laps':40 if i==20 else 56} for i in range(1,21)])
        session=MagicMock(); session.results=records
        provider=SimpleNamespace(get_session=MagicMock(return_value=session),Cache=SimpleNamespace(disabled=MagicMock()))
        with patch.dict('sys.modules',{'fastf1':provider}):
            result=fastf1(RAW,ENTRIES,NOW)
            self.assertEqual(result['Results'][-1]['position'],'20')
            self.assertEqual(result['Results'][-1]['grid'],'1')
            session.load.assert_called_once_with(laps=False,telemetry=False,weather=False,messages=False)
            session.results.loc[19,'Position']=float('nan')
            with self.assertRaises(ValueError): fastf1(RAW,ENTRIES,NOW)

    def test_final_race_mapping_and_unknown_grid_are_not_finish_order(self):
        r=final(); self.assertEqual(len(r['Results']),20); self.assertEqual(r['Results'][0]['grid'],'0'); self.assertEqual(r['Results'][-1]['status'],'Retired')
        self.assertEqual(match_session([SESSION],RAW,'R',NOW)['session_key'],10)
        with self.assertRaises(ValueError): match_session([SESSION],RAW,'R',datetime(2026,10,25,22,10,tzinfo=UTC))
        with self.assertRaises(ValueError): match_session([{**SESSION,'session_name':'Sprint'}],RAW,'R',NOW)

    def test_partial_duplicate_wrong_event_and_unknown_entries_rejected(self):
        for kind in ['partial','duplicate','wrong','unknown','unclassified']:
            rows=copy.deepcopy(RESULTS)
            if kind=='partial': rows.pop()
            elif kind=='duplicate': rows[1]['position']=1
            elif kind=='wrong': rows[0]['meeting_key']=99
            elif kind=='unknown': rows[0]['driver_number']=999
            else: rows[-1]['position']=None
            with self.subTest(kind=kind),self.assertRaises(ValueError): normalize(RAW,ENTRIES,SESSION,DRIVERS,rows,NOW)

    def test_empty_primary_fallback_then_outage_preserves_cache(self):
        with tempfile.TemporaryDirectory() as tmp,patch('ml.ingestion.race_results.openf1',return_value=final()) as source:
            first=load(RAW,ENTRIES,cache=tmp,now=NOW); self.assertEqual(first['source'],'OpenF1'); source.assert_called_once()
            with patch('ml.ingestion.race_results.openf1',side_effect=ValueError('outage')),patch('ml.ingestion.race_results.fastf1',side_effect=ValueError('outage')):
                cached=load(RAW,ENTRIES,cache=tmp,now=NOW); self.assertIn('last complete',cached['refresh_warning'])
            corrected=copy.deepcopy(first); corrected['Results'][0]['status']='Revised'
            second=load(RAW,ENTRIES,primary=corrected,cache=tmp,now=NOW)
            self.assertEqual(second['source'],'Jolpica'); self.assertEqual(second['Results'][0]['status'],'Revised')
            with self.assertRaises(ValueError): load(RAW,ENTRIES,cache=tmp,now=NOW-timedelta(days=2))

    def test_prospective_baselines_use_only_frozen_evidence_and_match_cohorts(self):
        p={'race_id':'2026-18','race_start':'2026-10-25T20:00:00Z','cutoff':'2026-10-24T20:00:00Z','is_demo':False,'stage':'FP1','model_version':'test',
           'drivers':[{'driver_id':str(i),'name':str(i),'probability':.05,'podium_probability':.15,'top10_probability':.5,'observations':{'recent_average_finish':i}} for i in range(1,21)]}
        cutoff=datetime(2026,10,24,20,tzinfo=UTC); attach(p,RAW,[],cutoff)
        b=p['baselines'][0]; self.assertAlmostEqual(sum(r['probability'] for r in b['drivers']),1); self.assertAlmostEqual(sum(r['top10_probability'] for r in b['drivers']),10)
        race={'race_id':'2026-18','name':'Race','scheduled_at':RAW['date']+'T'+RAW['time']}
        result={'results':[{'driver_id':str(i),'name':str(i),'position':i} for i in range(1,21)]}
        card=race_card(race,[p],result); old=copy.deepcopy(card); old['race_id']='old'; old['stages'][0]['baselines']=[]
        groups=overall([card,old])['baseline_groups']; self.assertEqual(len(groups),3)
        self.assertTrue(all(g['model_metrics']['races']==g['baseline_metrics']['races']==1 for g in groups))
        self.assertTrue(all(g['race_ids']==['2026-18'] for g in groups))

    def test_backup_restore_integrity_and_nonempty_restore_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); source=create_engine('sqlite:///'+(folder/'source.db').as_posix()); Base.metadata.create_all(source)
            with Session(source) as db:
                db.add(Race(race_id='real',season=2026,round=18,scheduled_at='2026-10-25T20:00:00Z',is_demo=False,payload={'test':True})); db.commit()
            output=folder/'backup'; manifest=backup(output,engine=source,include_models=False); self.assertEqual(manifest['rows']['races'],1)
            url='sqlite:///'+(folder/'restored.db').as_posix(); counts=restore(output,url); self.assertEqual(counts['races'],1)
            with self.assertRaisesRegex(ValueError,'empty'): restore(output,url)
            with (output/'serving.jsonl').open('a') as stream: stream.write('tamper')
            with self.assertRaisesRegex(ValueError,'integrity'): verify(output)
            source.dispose()

    def test_readiness_blocks_stale_worker_and_reports_backup_warning(self):
        e=create_engine('sqlite:///:memory:'); Base.metadata.create_all(e)
        with Session(e) as db:
            db.add(SystemState(key='refresh',payload={'status':'ok','last_attempt':(NOW-timedelta(hours=1)).isoformat(),'interval_seconds':300})); db.commit()
            state=inspect(db,NOW,models=False); self.assertFalse(state['ready']); self.assertTrue(state['warnings'])
            row=db.get(SystemState,'refresh'); row.payload={'status':'ok','last_attempt':NOW.isoformat(),'interval_seconds':300}; db.commit()
            self.assertTrue(inspect(db,NOW,models=False)['ready'])
        e.dispose()

if __name__=='__main__': unittest.main()
