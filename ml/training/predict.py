"""Publish a forecast only from an explicitly audited pre-race source snapshot.

Inputs are local files; upstream fetches and model training never happen here.
The source fixture schema is documented in docs/data-contract.md.
"""
import argparse
import json
import pickle
from datetime import datetime
from pathlib import Path
import pandas as pd
from ml.features.build import features_for_race, NUMERIC, CATEGORICAL, FEATURE_VERSION
from .evaluate import race_distribution
from apps.api.database import initialize, SessionLocal, Race, save_snapshot
from apps.api.contracts import Forecast


def parse_time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamps must include timezone")
    return result


def validate_source(source, report):
    if source.get("availability_audited") is not True:
        raise ValueError("A pre-race availability audit is required")
    cutoff = parse_time(source["cutoff"])
    if parse_time(source["race"]["scheduled_at"]) <= cutoff:
        raise ValueError("Cutoff must precede race start")
    if parse_time(report["trained_until"]) >= cutoff:
        raise ValueError("Model training extends beyond the forecast cutoff")
    if report.get("created_at") and parse_time(report["created_at"])>cutoff:
        raise ValueError("Model artifact was created after the forecast cutoff")
    if report["feature_version"] != FEATURE_VERSION:
        raise ValueError("Incompatible feature schema")
    for evidence in source.get("evidence", []):
        if parse_time(evidence["available_at"]) > cutoff:
            raise ValueError("Evidence was published after the cutoff")
    if not source.get("evidence"):
        raise ValueError("Evidence provenance is required")
    return cutoff


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--history", type=Path, default=Path("data/processed/history.json"))
    args = parser.parse_args()
    source = json.loads(args.source.read_text())
    report = json.loads(args.report.read_text())
    cutoff = validate_source(source, report)
    history = json.loads(args.history.read_text())["races"]
    rows = features_for_race(source["qualifying_race"], history, cutoff, include_target=False)
    frame = pd.DataFrame(rows)
    if set(frame.driver_id) != {d["driver_id"] for d in source["entries"]}:
        raise ValueError("Feature rows must cover every entered driver exactly once")
    model_name = report["selected_model"]
    if model_name == "grid_baseline":
        scores = frame.qualifying_position.map(lambda p: report["grid_rates"].get(str(p), .05)).to_numpy()
    elif model_name == "logistic":
        with (args.report.parent / "logistic.pkl").open("rb") as stream:
            model = pickle.load(stream)  # Only load locally created trusted artifacts.
        scores = model.predict_proba(frame[NUMERIC + CATEGORICAL])[:, 1]
    else:
        from catboost import CatBoostClassifier
        model = CatBoostClassifier()
        model.load_model(str(args.report.parent / "model.cbm"))
        x = frame[NUMERIC + CATEGORICAL].copy()
        for col in NUMERIC:
            x[col] = x[col].fillna(-999)
        for col in CATEGORICAL:
            x[col] = x[col].fillna("unknown").astype(str)
        scores = model.predict_proba(x)[:, 1]
    probabilities = race_distribution(scores, report["temperatures"][model_name])
    entries = {d["driver_id"]: d for d in source["entries"]}
    drivers = [{**entries[row["driver_id"]], "probability": float(p), "grid": entries[row["driver_id"]].get("grid"),
                "factors": [f"Qualifying P{row['qualifying_position']}", f"Earlier circuit sample: {row['prior_starts']} starts", "Earlier driver/constructor form"]}
               for row,p in zip(rows,probabilities)]
    drivers.sort(key=lambda d: d["probability"], reverse=True)
    payload = {"race_id": source["race"]["race_id"], "model_version": report["model_version"], "cutoff": source["cutoff"],
               "updated_at": source["cutoff"], "race_start": source["race"]["scheduled_at"], "is_demo": False,
               "calibrated": True, "status": "validation-fitted; experimental", "drivers": drivers}
    Forecast.model_validate(payload)
    initialize()
    with SessionLocal() as db:
        race = source["race"]
        db.merge(Race(race_id=race["race_id"], season=race["season"], round=race["round"], scheduled_at=race["scheduled_at"], is_demo=False, payload=race))
        save_snapshot(db, race["race_id"], "prediction", report["model_version"], source["cutoff"], payload)
        db.commit()
    print(f"Saved audited forecast for {payload['race_id']}, {len(drivers)} drivers")


if __name__ == "__main__":
    main()
