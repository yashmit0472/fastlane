import copy
import unittest
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from ml.features.build import lap_ms, features_for_race, historical_prior,FEATURE_VERSION
from ml.training.evaluate import race_distribution, evaluate, fit_temperature
from ml.training.train import split,validate_feature_schema
from ml.training.predict import validate_source


def event(date, season, round, winner="a", grid_a=1):
    return {"season": str(season), "round": str(round), "date": date, "time": "14:00:00Z", "Circuit": {"circuitId": "test"},
            "Results": [{"Driver": {"driverId": d}, "Constructor": {"constructorId": "team"}, "grid": str(grid_a if d == "a" else 2), "position": "1" if d == winner else "2"} for d in ["a", "b"]],
            "QualifyingResults": [{"Driver": {"driverId": d}, "Constructor": {"constructorId": "team"}, "position": str(i + 1), "Q3": f"1:20.{i}00"} for i, d in enumerate(["a", "b"])]}


class FeaturesTest(unittest.TestCase):
    def test_old_training_semantics_rejected(self):
        validate_feature_schema(pd.DataFrame({'feature_version':[FEATURE_VERSION]}))
        for frame in [pd.DataFrame({'x':[1]}),pd.DataFrame({'feature_version':['qualifying-history-v1']}),pd.DataFrame({'feature_version':[FEATURE_VERSION,None]})]:
            with self.assertRaisesRegex(ValueError,'Rebuild features'): validate_feature_schema(frame)

    def test_timing_missing_and_invalid(self):
        self.assertEqual(lap_ms("1:23.456"), 83456)
        for value in [None, "", "bad", "nan", "-1", "0"]:
            self.assertIsNone(lap_ms(value))

    def test_target_and_future_outcomes_cannot_change_features(self):
        past = event("2022-01-01", 2022, 1)
        target = event("2023-01-01", 2023, 1)
        future = event("2024-01-01", 2024, 1)
        cutoff = datetime(2022, 12, 31, 20, tzinfo=timezone.utc)
        first = features_for_race(target, [past, target, future], cutoff)
        changed = copy.deepcopy(target)
        changed["Results"][0]["position"] = "20"
        changed["Results"][1]["position"] = "1"
        future["Results"][0]["position"] = "20"
        self.assertEqual(first, features_for_race(changed, [past, changed, future], cutoff))
        self.assertNotIn("target", first[0])
        self.assertEqual(first[0]["recent_finish"], 1)

    def test_missing_session_is_not_zero(self):
        target = event("2023-01-01", 2023, 1)
        target["QualifyingResults"] = []
        self.assertEqual(features_for_race(target, [], datetime(2022, 12, 31, tzinfo=timezone.utc)), [])

    def test_cutoff_rejects_after_race_and_sprint(self):
        target = event("2023-01-01", 2023, 1)
        with self.assertRaises(ValueError):
            features_for_race(target, [], datetime(2023, 1, 2, tzinfo=timezone.utc))
        target["Sprint"] = {"date": "2022-12-31"}
        self.assertEqual(features_for_race(target, [], datetime(2022, 12, 31, tzinfo=timezone.utc)), [])

    def test_small_circuit_prior_uses_earlier_results_only(self):
        cutoff = datetime(2023, 1, 1, tzinfo=timezone.utc)
        prior, starts = historical_prior([event("2022-01-01",2022,1),event("2024-01-01",2024,1)], "test", 1, cutoff)
        self.assertEqual(starts,1)
        self.assertGreater(prior,0)
        self.assertLess(prior,1)


class ProbabilityTest(unittest.TestCase):
    def test_normalization_and_degenerate_scores(self):
        for scores in [[.1,.2,.7],[0,0,0],[1e-300,1,0]]:
            p=race_distribution(scores)
            self.assertAlmostEqual(p.sum(),1)
            self.assertTrue(np.isfinite(p).all())
        for scores in [[],[float("nan"),1],[-1,1]]:
            with self.assertRaises(ValueError): race_distribution(scores)

    def test_metrics_are_race_level(self):
        frame=pd.DataFrame({"race_id":["r1","r1","r2","r2"],"driver_id":["a","b","a","b"],"target":[1,0,0,1]})
        metrics,_=evaluate(frame,[.8,.2,.2,.8])
        self.assertAlmostEqual(metrics["log_loss"],-np.log(.8))
        self.assertAlmostEqual(metrics["brier"],.08)
        self.assertEqual(metrics["races"],2)
        self.assertEqual(metrics["top1_accuracy"],1)

    def test_chronological_groups(self):
        frame=pd.DataFrame({"race_id":["a","a","b","b","c","c"],"season":[2022,2022,2023,2023,2024,2024]})
        train,valid,test=split(frame,2023,2024)
        self.assertEqual(set(train.race_id),{"a"})
        self.assertEqual(set(valid.race_id),{"b"})
        self.assertEqual(set(test.race_id),{"c"})
        with self.assertRaises(ValueError):split(frame,2024,2023)

    def test_publish_requires_audited_earlier_evidence(self):
        source={"availability_audited":True,"cutoff":"2024-01-01T12:00:00Z","race":{"scheduled_at":"2024-01-02T12:00:00Z"},"evidence":[{"available_at":"2024-01-01T11:00:00Z"}]}
        report={"trained_until":"2023-12-01T12:00:00Z","feature_version":FEATURE_VERSION}
        validate_source(source,report)
        source["evidence"][0]["available_at"]="2024-01-01T13:00:00Z"
        with self.assertRaises(ValueError):validate_source(source,report)

    def test_artifact_must_exist_before_forecast_cutoff(self):
        source={"availability_audited":True,"cutoff":"2026-10-13T12:00:00Z","race":{"scheduled_at":"2026-10-14T12:00:00Z"},"evidence":[{"available_at":"2026-10-13T11:00:00Z"}]}
        report={"trained_until":"2023-12-01T12:00:00Z","created_at":"2026-10-13T13:00:00Z","feature_version":FEATURE_VERSION}
        with self.assertRaisesRegex(ValueError,"artifact"):
            validate_source(source,report)
        source["availability_audited"]=False
        with self.assertRaises(ValueError):validate_source(source,report)


if __name__ == "__main__":
    unittest.main()
