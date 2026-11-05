import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import numpy as np
import pandas as pd
from pydantic import ValidationError
from apps.api.contracts import Forecast
from ml.live.outcomes import constrained_marginals, attach_outcomes
from ml.live.outcomes import ROOT, checksum
from pathlib import Path
from ml.training.outcomes import finishing_labels
from ml.live.analytics import score_forecasts


def forecast():
    return {'race_id':'test','model_version':'test','cutoff':'2026-01-01T00:00:00Z','updated_at':'2026-01-01T00:00:00Z',
        'race_start':'2026-01-02T00:00:00Z','is_demo':False,'calibrated':False,'status':'test',
        'drivers':[{'driver_id':str(i),'name':str(i),'abbreviation':str(i),'number':i,'team':'t','color':'#888','factors':[],
            'probability':.05,'podium_probability':.15,'top10_probability':.5} for i in range(20)]}


class OutcomeTests(unittest.TestCase):
    def test_marginals_are_nested_and_sum_to_finishing_places(self):
        rng=np.random.default_rng(47)
        for n in [10,19,20,22]:
            winner=rng.dirichlet(np.ones(n))
            podium=constrained_marginals(rng.random(n),winner,3)
            top10=constrained_marginals(rng.random(n),podium,10)
            self.assertTrue(np.all(winner<=podium)); self.assertTrue(np.all(podium<=top10))
            self.assertTrue(np.all(top10<=1)); self.assertAlmostEqual(sum(podium),3); self.assertAlmostEqual(sum(top10),10)

    def test_projection_rejects_bad_inputs(self):
        for scores,lower,k in [([np.nan]*20,[.05]*20,3),([1]*2,[.5]*2,3),([-.1]*20,[.05]*20,3),([.5]*20,[.8]*20,3)]:
            with self.assertRaises(ValueError): constrained_marginals(scores,lower,k)

    def test_contract_rejects_partial_non_nested_and_wrong_totals(self):
        Forecast.model_validate(forecast())
        for field,value in [('podium_probability',None),('podium_probability',.04),('top10_probability',.4)]:
            data=forecast(); data['drivers'][0][field]=value
            with self.assertRaises(ValidationError): Forecast.model_validate(data)

    def test_older_winner_only_snapshots_remain_valid(self):
        data=forecast()
        for d in data['drivers']:
            del d['podium_probability']; del d['top10_probability']
        Forecast.model_validate(data)

    def test_finishing_results_join_only_as_labels(self):
        frame=pd.DataFrame([{'race_id':'2025-01','driver_id':str(i),'target':int(i==0),'qualifying_position':20-i} for i in range(20)])
        races=[{'season':'2025','round':'1','Results':[{'Driver':{'driverId':str(i)},'position':str(i+1)} for i in range(20)]}]
        labeled=finishing_labels(frame,races)
        pd.testing.assert_frame_equal(labeled[frame.columns],frame)
        self.assertEqual((labeled.finish_label<=3).sum(),3); self.assertEqual((labeled.finish_label<=10).sum(),10)
        races[0]['Results']=races[0]['Results'][1:]
        with self.assertRaises(KeyError): finishing_labels(frame,races)

    def test_no_bundle_means_no_synthetic_extra_targets(self):
        data=forecast()
        with patch('ml.live.outcomes.ACTIVE') as active:
            active.exists.return_value=False
            self.assertIsNone(attach_outcomes(data['drivers'],pd.DataFrame(),'Q',datetime.now(timezone.utc)))

    def test_future_artifacts_version_mismatch_and_tampering(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            root=Path(directory); artifact=root/'ml/artifacts/test'; artifact.mkdir(parents=True)
            report={'stage':'Q','schema':'race-outcomes-v1','model_version':'outcomes-test','winner_model_version':'winner-test',
                'created_at':'2050-01-01T00:00:00+00:00','trained_until':'2039-01-01T00:00:00+00:00',
                'targets':{'podium':{'selected_model':'uniform'},'top10':{'selected_model':'uniform'}}}
            path=artifact/'report.json'; active=root/'active.json'; cutoff=datetime(2049,1,1,tzinfo=timezone.utc)
            def save():
                path.write_text(json.dumps(report))
                active.write_text(json.dumps({'stages':{'Q':{'report':'ml/artifacts/test/report.json','sha256':checksum(path)}}}))
            save()
            with patch('ml.live.outcomes.ROOT',root),patch('ml.live.outcomes.ACTIVE',active):
                self.assertIsNone(attach_outcomes([],pd.DataFrame(),'Q',cutoff,'winner-test'))
                report['created_at']='2040-01-01T00:00:00+00:00'; save()
                self.assertIsNone(attach_outcomes([],pd.DataFrame(),'Q',cutoff,'another-winner'))
                data=forecast(); frame=pd.DataFrame({'driver_id':[d['driver_id'] for d in data['drivers']]})
                self.assertEqual(attach_outcomes(data['drivers'],frame,'Q',cutoff,'winner-test'),'outcomes-test')
                self.assertAlmostEqual(sum(d['top10_probability'] for d in data['drivers']),10)
                path.write_text('{}')
                with self.assertRaises(ValueError): attach_outcomes([],pd.DataFrame(),'Q',cutoff,'winner-test')

    def test_post_race_scores_all_targets_without_mutating_forecast(self):
        data=forecast(); original=copy.deepcopy(data)
        classification=[{'position':str(i+1),'Driver':{'driverId':str(i)}} for i in range(20)]
        result=score_forecasts([data],classification,'2026-01-02T15:00:00Z')['forecasts'][0]
        self.assertEqual(data,original)
        self.assertAlmostEqual(result['outcomes']['podium']['brier'],.1275)
        self.assertAlmostEqual(result['outcomes']['top10']['brier'],.25)
        classification.pop()
        result=score_forecasts([data],classification,'2026-01-02T15:00:00Z')['forecasts'][0]
        self.assertEqual(result['outcomes']['podium']['status'],'field mismatch')


if __name__=='__main__': unittest.main()
