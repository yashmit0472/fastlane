"""Reproducible chronological backtest. Does not publish live predictions."""
import argparse
import hashlib
import json
import pickle
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from ml.features.build import NUMERIC, CATEGORICAL, FEATURE_VERSION
from .evaluate import evaluate, fit_temperature, reliability

ROOT = Path(__file__).resolve().parents[2]


def split(frame, valid_season, test_season):
    if valid_season >= test_season:
        raise ValueError("Validation must precede test")
    train = frame[frame.season < valid_season].reset_index(drop=True)
    valid = frame[(frame.season >= valid_season) & (frame.season < test_season)].reset_index(drop=True)
    test = frame[frame.season >= test_season].reset_index(drop=True)
    if any(f.empty for f in (train, valid, test)):
        raise ValueError("Each chronological window needs races")
    if any(set(a.race_id) & set(b.race_id) for a, b in [(train, valid), (train, test), (valid, test)]):
        raise ValueError("Race groups must not cross split boundaries")
    return train, valid, test


def validate_feature_schema(frame):
    if 'feature_version' not in frame or set(frame.feature_version.dropna()) != {FEATURE_VERSION} or frame.feature_version.isna().any():
        raise ValueError(f'Rebuild features with ml.features.build: expected {FEATURE_VERSION}')


def main():
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, default=ROOT / "data/processed/features.csv")
    parser.add_argument("--validation-season", type=int, default=2023)
    parser.add_argument("--test-season", type=int, default=2024)
    parser.add_argument("--without-catboost", action="store_true")
    parser.add_argument("--publish-metrics", action="store_true")
    args = parser.parse_args()
    frame = pd.read_csv(args.features)
    validate_feature_schema(frame)
    train, valid, test = split(frame, args.validation_season, args.test_season)
    data_hash = hashlib.sha256(args.features.read_bytes()).hexdigest()
    created_at = datetime.now(timezone.utc).isoformat()
    version = "qual-v2-" + data_hash[:8] + "-" + created_at[:19].replace(":", "").replace("-", "")
    artifacts = ROOT / "ml/artifacts" / version
    artifacts.mkdir(parents=True, exist_ok=True)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "uncommitted local workspace"
    counts = train.groupby("qualifying_position").target.agg(["sum", "count"])
    grid_rates = {int(k): (float(r["sum"]) + 1) / (float(r["count"]) + 20) for k, r in counts.iterrows()}
    def grid_scores(f):
        return f.qualifying_position.map(grid_rates).fillna(1 / 20).to_numpy()
    candidates = {"grid_baseline": (None, grid_scores(valid), grid_scores(test))}
    transform = ColumnTransformer([
        ("numeric", Pipeline([("imputer", SimpleImputer(strategy="median", add_indicator=True)), ("scale", StandardScaler())]), NUMERIC),
        ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL)])
    logistic = Pipeline([("features", transform), ("model", LogisticRegression(max_iter=2000, random_state=42, C=1.0))])
    logistic.fit(train[NUMERIC + CATEGORICAL], train.target)
    candidates["logistic"] = (logistic, logistic.predict_proba(valid[NUMERIC + CATEGORICAL])[:,1], logistic.predict_proba(test[NUMERIC + CATEGORICAL])[:,1])
    if not args.without_catboost:
        from catboost import CatBoostClassifier
        model = CatBoostClassifier(iterations=500, depth=5, learning_rate=.04, loss_function="Logloss", random_seed=42,
                                   verbose=False, thread_count=2, allow_writing_files=False)
        def cat_input(f):
            data = f[NUMERIC + CATEGORICAL].copy()
            for col in NUMERIC:
                data[col] = data[col].fillna(-999)
            for col in CATEGORICAL:
                data[col] = data[col].fillna("unknown").astype(str)
            return data
        model.fit(cat_input(train), train.target, cat_features=CATEGORICAL, eval_set=(cat_input(valid), valid.target), early_stopping_rounds=60)
        candidates["catboost"] = (model, model.predict_proba(cat_input(valid))[:,1], model.predict_proba(cat_input(test))[:,1])
        model.save_model(str(artifacts / "model.cbm"))
    validation_metrics, test_metrics, temperatures, bins = {}, {}, {}, {}
    for name, (model, valid_scores, test_scores) in candidates.items():
        temperatures[name] = fit_temperature(valid, valid_scores)
        validation_metrics[name] = evaluate(valid, valid_scores, temperatures[name])[0]
        test_metrics[name], predictions = evaluate(test, test_scores, temperatures[name])
        bins[name] = reliability(predictions)
        (artifacts / f"{name}-predictions.json").write_text(json.dumps(predictions, indent=2))
    selected = min(validation_metrics, key=lambda n: validation_metrics[n]["log_loss"])
    with (artifacts / "logistic.pkl").open("wb") as stream:
        pickle.dump(logistic, stream)
    def window(f):
        return f"{int(f.season.min())}–{int(f.season.max())} ({f.race_id.nunique()} races)"
    report = {"status": "backtested", "model_version": version, "feature_version": FEATURE_VERSION, "created_at": created_at,
              "training_window": window(train), "validation_window": window(valid), "test_window": window(test),
              "trained_until": valid.race_date.max(), "selected_model": selected, "selection_rule": "lowest validation race log loss",
              "metrics": test_metrics, "validation_metrics": validation_metrics, "temperatures": temperatures, "grid_rates": grid_rates,
              "reliability": bins, "features": NUMERIC + CATEGORICAL, "dataset_sha256": data_hash, "code_commit": commit, "seed": 42,
              "notice": "Qualifying/history experiment; estimated historical publication cutoffs. Practice/weather excluded. No live forecast certification."}
    (artifacts / "report.json").write_text(json.dumps(report, indent=2))
    if args.publish_metrics:
        from apps.api.database import initialize, SessionLocal, save_snapshot
        initialize()
        with SessionLocal() as db:
            save_snapshot(db, "model", "metrics", version, created_at, report)
            db.commit()
    print(json.dumps({"selected_model": selected, "metrics": test_metrics, "report": str(artifacts / "report.json")}, indent=2))


if __name__ == "__main__":
    main()
