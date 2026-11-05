import copy
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch,Mock
from ml.ingestion.qualifying import normalize_openf1,validate,openf1
from ml.ingestion.openf1_sessions import match_session
from ml.live.refresh import load_qualifying,archived_sessions,qualifying_sessions,qualifying_inputs_signature

UTC=timezone.utc
RAW={'season':'2026','round':'18','Qualifying':{'date':'2026-10-24','time':'21:00:00Z'},'Circuit':{'Location':{'country':'USA'}}}
SESSION={'year':2026,'session_key':10,'meeting_key':20,'session_name':'Qualifying','country_name':'United States','date_start':'2026-10-24T21:00:00Z','date_end':'2026-10-24T22:00:00Z'}
NOW=datetime(2026,10,25,tzinfo=UTC)
ENTRIES=[{'driver_id':str(i),'abbreviation':f'D{i}','name':f'Driver {i}','number':i,'constructor_id':'team','team':'Team'} for i in (1,2)]
DRIVERS=[{'session_key':10,'meeting_key':20,'driver_number':i,'name_acronym':f'D{i}'} for i in (1,2)]
RESULTS=[{'session_key':10,'meeting_key':20,'driver_number':i,'position':i,'duration':[90+i,89+i,88+i]} for i in (1,2)]

def fixture(): return normalize_openf1(RAW,ENTRIES,SESSION,DRIVERS,RESULTS,NOW)


class QualifyingTests(unittest.TestCase):
    def test_blank_unreached_phase_is_missing_instead_of_invalid_time(self):
        q=fixture(); q['QualifyingResults'].append({**copy.deepcopy(q['QualifyingResults'][0]),'position':'3','Driver':{'driverId':'3'},'Q2':'','Q3':''})
        self.assertIs(validate(q,None),q)

    def test_invalid_primary_archive_does_not_replace_verified_phases(self):
        phases=qualifying_sessions(fixture(),NOW.isoformat()); bad=fixture(); bad['QualifyingResults'][1]['position']='1'
        result=archived_sessions({'sessions':[{'type':'Q'}]},bad,phases,NOW.isoformat())
        self.assertEqual(result,phases)
        empty=archived_sessions({'sessions':[{'type':'Q'}]},bad,[],NOW.isoformat())
        self.assertEqual(empty[0]['status'],'archive pending'); self.assertEqual(empty[0]['drivers'],[])

    def test_timestamp_only_refresh_is_idempotent_but_corrections_are_not(self):
        q=fixture(); original=qualifying_inputs_signature(q)
        q['observed_at']='2026-10-25T01:00:00Z'; self.assertEqual(original,qualifying_inputs_signature(q))
        q['QualifyingResults'][0]['Q3']='1:28.000'; self.assertNotEqual(original,qualifying_inputs_signature(q))

    def test_published_primary_can_confirm_replacement_for_provisional_roster(self):
        q=fixture(); q['QualifyingResults'][0]['Driver']['driverId']='replacement'
        primary=Mock(); primary.races.return_value=[q]
        with tempfile.TemporaryDirectory() as directory,patch('ml.live.refresh.CACHE',Path(directory)):
            result=load_qualifying(RAW,ENTRIES,primary,strict_roster=False)
            self.assertEqual(result['QualifyingResults'][0]['Driver']['driverId'],'replacement')
    def test_qualifying_matches_race_and_never_uses_sprint_or_paid_window(self):
        self.assertEqual(match_session([SESSION],RAW,'Q',NOW)['session_key'],10)
        sprint={**SESSION,'session_name':'Sprint Qualifying'}
        with self.assertRaises(ValueError): match_session([sprint],RAW,'Q',NOW)
        with self.assertRaisesRegex(ValueError,'30 minutes'): match_session([SESSION],RAW,'Q',datetime(2026,10,24,22,15,tzinfo=UTC))
        with self.assertRaises(ValueError): match_session([{**SESSION,'date_start':'2026-05-02T21:00:00Z'}],RAW,'Q',NOW)

    def test_real_phase_arrays_preserve_seconds_and_canonical_ids(self):
        q=fixture(); self.assertEqual(q['QualifyingResults'][0]['Q1'],'1:31.000'); self.assertEqual(q['QualifyingResults'][0]['Q3'],'1:29.000')
        self.assertEqual(q['QualifyingResults'][0]['Driver']['driverId'],'1')
        phases=qualifying_sessions(q,NOW.isoformat()); self.assertEqual(phases[-1]['source'],'OpenF1'); self.assertEqual(phases[-1]['drivers'][0]['best_lap_ms'],89000)

    def test_wrong_session_partial_duplicate_and_scalar_times_rejected(self):
        for mutate in ['wrong','partial','duplicate','scalar','invalid','unfinished']:
            rows=copy.deepcopy(RESULTS)
            if mutate=='wrong': rows[0]['session_key']=11
            elif mutate=='partial': rows.pop()
            elif mutate=='duplicate': rows[1]['position']=1
            elif mutate=='scalar': rows[0]['duration']=89
            elif mutate=='invalid': rows[0]['duration'][0]=-1
            else:
                for r in rows: r['duration'][2]=None
            with self.subTest(mutate=mutate),self.assertRaises(ValueError): normalize_openf1(RAW,ENTRIES,SESSION,DRIVERS,rows,NOW)

    def test_delayed_primary_falls_back_and_later_corrections_replace_cache(self):
        with tempfile.TemporaryDirectory() as directory,patch('ml.live.refresh.CACHE',Path(directory)),patch('ml.ingestion.qualifying.openf1',return_value=fixture()) as fallback:
            primary=Mock(); primary.races.return_value=[]
            first=load_qualifying(RAW,ENTRIES,primary); self.assertEqual(first['source'],'OpenF1'); fallback.assert_called_once()
            corrected=fixture(); corrected['QualifyingResults'][0]['Q3']='1:28.000'; primary.races.return_value=[corrected]
            second=load_qualifying(RAW,ENTRIES,primary); self.assertEqual(second['source'],'Jolpica'); self.assertEqual(second['QualifyingResults'][0]['Q3'],'1:28.000')

    def test_outages_preserve_complete_cache_and_empty_response_is_retried(self):
        with tempfile.TemporaryDirectory() as directory,patch('ml.live.refresh.CACHE',Path(directory)),patch('ml.ingestion.qualifying.openf1',side_effect=ValueError('pending')) as fallback,patch('ml.ingestion.qualifying.fastf1',side_effect=ValueError('outage')):
            primary=Mock(); primary.races.side_effect=TimeoutError('outage')
            with self.assertRaises(ValueError): load_qualifying(RAW,ENTRIES,primary)
            self.assertFalse(list(Path(directory).glob('*.json')))
            saved=fixture(); (Path(directory)/'2026-18-Q.json').write_text(json.dumps(saved))
            result=load_qualifying(RAW,ENTRIES,primary); self.assertIn('last complete',result['refresh_warning']); self.assertEqual(fallback.call_count,2)
            self.assertEqual(json.loads((Path(directory)/'2026-18-Q.json').read_text()),saved)

    def test_archiving_retains_fallback_phases_when_primary_is_still_empty(self):
        phases=qualifying_sessions(fixture(),NOW.isoformat())
        result=archived_sessions({'sessions':[{'type':'Q'}]},None,phases,NOW.isoformat())
        self.assertEqual([r['type'] for r in result],['Q1','Q2','Q3']); self.assertEqual(result[-1]['source'],'OpenF1')


if __name__=='__main__': unittest.main()
