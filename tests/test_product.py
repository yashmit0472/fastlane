import copy
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
import numpy as np
import pandas as pd
from ml.features.build import comparable_qualifying
from ml.live.evidence import attach_evidence,confirmed_entries,ROOT
from ml.live.weather import parse_forecast
from ml.live.reportcards import latest_stages,race_card,overall,score_snapshot
from ml.live.explain import linear_terms
from ml.validation.metrics import assess
from ml.inference.linear import LinearModel
from ml.ingestion.entry_list import parse_entries,candidate_documents

UTC=timezone.utc


def prediction(stage='FP1',cutoff='2026-10-23T19:00:00Z'):
    return {'race_id':'2026-18','is_demo':False,'stage':stage,'cutoff':cutoff,'race_start':'2026-10-25T20:00:00Z','model_version':'test',
        'drivers':[{'driver_id':str(i),'name':str(i),'probability':.05,'podium_probability':.15,'top10_probability':.5} for i in range(20)]}


class ProductTests(unittest.TestCase):
    def test_fia_discovery_uses_actual_matching_primary_links(self):
        raw={'season':'2026','raceName':'Test Grand Prix'}
        good='https://www.fia.com/system/files/decision-document/2026_test_grand_prix_-_entry_list.pdf'
        html=f'<a href="{good}">Entry list</a><a href="https://example.com/2026_test_grand_prix_entry_list.pdf">Wrong host</a><a href="/system/files/decision-document/2025_test_grand_prix_-_entry_list.pdf">Wrong year</a>'
        self.assertEqual(candidate_documents(html,raw),[good])

    def test_qualifying_gaps_use_same_phase_and_common_teammate_phase(self):
        q=[{'Driver':{'driverId':'a'},'Q1':'1:20.000','Q2':'1:19.000','Q3':'1:18.000'},
           {'Driver':{'driverId':'b'},'Q1':'1:20.500','Q2':'1:19.500'}]
        a=comparable_qualifying(q,'a','b'); b=comparable_qualifying(q,'b','a')
        self.assertEqual(a['phase'],'Q3'); self.assertEqual(b['phase'],'Q2'); self.assertEqual(b['gap_s'],.5)
        self.assertEqual(a['teammate_phase'],'Q2'); self.assertEqual(a['teammate_gap_s'],-.5)
        self.assertIsNone(comparable_qualifying(q,'missing')['gap_s'])

    def test_calibration_contains_probability_one_and_fractional_ties(self):
        m=assess(['a']*20,[1]+[0]*19,[.05]*20,1)
        self.assertAlmostEqual(m['top_k_recall'],.05); self.assertAlmostEqual(m['ece'],0)
        perfect=assess(['a']*20,[1]+[0]*19,[1]+[0]*19,1)
        self.assertEqual(perfect['brier'],0); self.assertEqual(perfect['reliability'][-1]['n'],1)
        with self.assertRaises(ValueError): assess(['a','a'],[.5,.5],[.5,.5],1)

    def test_report_card_uses_latest_pre_race_revision_only(self):
        old=prediction(); new=prediction(cutoff='2026-10-24T12:00:00Z'); late=prediction(cutoff='2026-10-25T21:00:00Z')
        self.assertEqual(latest_stages([late,new,old])['FP1'],new)
        race={'race_id':'2026-18','name':'Race','scheduled_at':'2026-10-25T20:00:00Z'}
        result={'results':[{'driver_id':str(i),'name':str(i),'position':i+1} for i in range(20)]}
        card=race_card(race,[old,new,late],result); summary=overall([card])
        self.assertEqual(len(card['stages']),1); self.assertEqual(summary['races_with_scored_forecasts'],1)
        self.assertEqual(summary['groups'][0]['metrics']['races'],1)
        self.assertEqual(card['stages'][0]['targets']['podium']['metrics']['top_k_recall'],.15)
        self.assertEqual(race_card(race,[],result)['status'],'no recorded forecast')
        card['stages'][0]['outcomes_model_version']='outcomes-v1'
        other=copy.deepcopy(card); other['race_id']='2026-19'; other['stages'][0]['outcomes_model_version']='outcomes-v2'
        groups=overall([card,other])['groups']
        self.assertEqual(len([g for g in groups if g['target']=='podium']),2)
        self.assertEqual(next(g for g in groups if g['target']=='winner')['metrics']['races'],2)

    def test_bad_field_or_classification_is_not_silently_scored(self):
        p=prediction(); rows=[{'driver_id':str(i),'position':i+1} for i in range(20)]
        self.assertEqual(score_snapshot(p,rows[:-1])['status'],'field mismatch')
        rows[0]['position']=2
        self.assertEqual(score_snapshot(p,rows)['status'],'incomplete classification')

    def test_weather_requires_race_hour_and_pre_race_observation(self):
        raw={'date':'2026-10-25','time':'20:00:00Z','Circuit':{'Location':{'lat':'30.13','long':'-97.64'}}}
        payload={'hourly':{'time':['2026-10-25T20:00'],'temperature_2m':[25],'precipitation_probability':[30],'wind_speed_10m':[10]}}
        result=parse_forecast(payload,raw,datetime(2026,10,24,tzinfo=UTC)); self.assertEqual(result['rain_probability_pct'],30); self.assertFalse(result['used_by_model'])
        with self.assertRaises(ValueError): parse_forecast(payload,raw,datetime(2026,10,26,tzinfo=UTC))
        payload['hourly']['time']=['2026-10-23T20:00']
        with self.assertRaises(ValueError): parse_forecast(payload,raw,datetime(2026,10,24,tzinfo=UTC))

    def test_evidence_excludes_future_results_and_unmatched_compounds(self):
        raw={'season':'2026','round':'18','date':'2026-10-25','time':'20:00:00Z'}
        history=[{'date':'2026-10-01','time':'12:00:00Z','raceName':'Earlier','Results':[{'Driver':{'driverId':'0'},'position':'2'}]},
            {'date':'2026-10-26','time':'12:00:00Z','Results':[{'Driver':{'driverId':'0'},'position':'1'}]}]
        entries=[{'driver_id':str(i),'constructor_id':'team'} for i in range(2)]
        practice={'FP1':{'source':'OpenF1','drivers':[{'driver_id':'0','best_lap_ms':90000,'lap_count':3,'long_run_compound':'SOFT','long_run_lap_ms':91000},
            {'driver_id':'1','best_lap_ms':91000,'lap_count':9,'long_run_compound':'HARD','long_run_lap_ms':92000}]}}
        p=prediction(); attach_evidence(p,raw,history,entries,practice,'FP1',datetime(2026,10,24,tzinfo=UTC))
        obs=p['drivers'][0]['observations']; self.assertEqual(obs['recent_average_finish'],2); self.assertTrue(obs['practice']['small_sample'])
        self.assertIsNone(obs['practice']['teammate_long_run_gap_s']); self.assertIn('provisional',p['input_quality']['roster'])

    def test_linear_associations_describe_raw_score_not_probabilities(self):
        frame=pd.DataFrame({'recent_finish':np.arange(20)+1,'driver_id':['a','b']*10,'constructor_id':['team']*20,'circuit_id':['c']*20})
        model=LinearModel([{'kind':'numeric','name':'numeric','columns':['recent_finish'],'statistics':[10.],
            'indicators':[],'mean':[10.],'scale':[5.]}],[-.5],.2)
        terms=linear_terms(model,frame)
        raw=model.decision_function(frame)-model.named_steps['model'].intercept_[0]
        for i,item in enumerate(terms): self.assertAlmostEqual(sum(s['contribution'] for s in item['signals']),raw[i])
        self.assertIn('not causal',terms[0]['notice'])

    def test_fia_main_entries_exclude_reserves_and_flag_number_conflicts(self):
        raw={'season':'2026','raceName':'Test Grand Prix'}
        reference=[{'driver_id':'a','abbreviation':'AAA','number':1,'name':'Driver A','constructor_id':'team','team':'Team'}]
        text='2026 TEST GRAND PRIX\n11 AAA Driver A GBR Team Constructor\nIn addition to the list of cars and drivers\n99 BBB Reserve B GBR Team Constructor'
        entries,conflicts=parse_entries(text,raw,reference)
        self.assertEqual(len(entries),1); self.assertEqual(entries[0]['number'],1); self.assertEqual(len(conflicts),1)


if __name__=='__main__': unittest.main()
