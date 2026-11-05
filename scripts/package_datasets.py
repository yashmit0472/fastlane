"""Package the downloaded historical data and reproducible chronological splits."""
import csv
import hashlib
import json
import math
import shutil
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path.cwd()
INPUT = ROOT / "data/processed"
OUTPUT = ROOT / "output/datasets/fastlane-2019-2024"
NUMERIC = ["qualifying_position", "qualifying_gap_s", "circuit_grid_prior", "prior_starts", "recent_finish", "recent_win_rate", "team_recent_finish"]
CATEGORICAL = ["driver_id", "constructor_id", "circuit_id"]


def lap_seconds(value):
    if not value:
        return None
    parts = str(value).split(":")
    seconds = float(parts[-1]) + (float(parts[-2]) * 60 if len(parts) > 1 else 0)
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (INPUT / "features.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    history = json.loads((INPUT / "history.json").read_text(encoding="utf-8"))
    coverage = json.loads((INPUT / "coverage.json").read_text(encoding="utf-8"))
    keys = [(r["race_id"], r["driver_id"]) for r in rows]
    assert len(keys) == len(set(keys)), "Duplicate driver-race rows"
    winners = Counter()
    for row in rows:
        assert row["target"] in {"0", "1"}
        assert datetime.fromisoformat(row["cutoff"]) < datetime.fromisoformat(row["race_date"])
        winners[row["race_id"]] += int(row["target"])
        for column in NUMERIC:
            assert row[column] == "" or math.isfinite(float(row[column])), column
    assert all(count == 1 for count in winners.values()), "Each race must have one winner"
    assert len(rows) == coverage["driver_rows"] and len(winners) == coverage["races_eligible"]
    splits = {"train": [r for r in rows if int(r["season"]) <= 2022],
              "validation": [r for r in rows if int(r["season"]) == 2023],
              "test": [r for r in rows if int(r["season"]) == 2024]}
    groups = [set(r["race_id"] for r in split) for split in splits.values()]
    assert not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
    assert sum(map(len, splits.values())) == len(rows)
    shutil.copyfile(INPUT / "features.csv", OUTPUT / "model_features_all.csv")
    summary = {}
    for name, split in splits.items():
        write_csv(OUTPUT / f"{name}.csv", split, fields)
        summary[name] = {"rows": len(split), "races": len(set(r["race_id"] for r in split)),
                         "seasons": sorted({int(r["season"]) for r in split}),
                         "winner_rows": sum(int(r["target"]) for r in split)}
    result_rows, qualifying_rows, race_rows = [], [], []
    for race in history["races"]:
        race_id = f"{race['season']}-{int(race['round']):02d}"
        circuit = race["Circuit"]
        race_rows.append({"race_id": race_id, "season": race["season"], "round": race["round"], "race_name": race["raceName"],
                          "race_date": race["date"], "race_start_utc": race["date"] + "T" + race.get("time", "00:00:00Z"),
                          "circuit_id": circuit["circuitId"], "circuit_name": circuit["circuitName"],
                          "country": circuit["Location"]["country"], "is_sprint_weekend": bool(race.get("Sprint")),
                          "qualifying_scheduled_date": race.get("Qualifying", {}).get("date"),
                          "qualifying_scheduled_time_utc": race.get("Qualifying", {}).get("time")})
        for result in race.get("Results", []):
            driver = result["Driver"]
            result_rows.append({"race_id": race_id, "driver_id": driver["driverId"],
                                "driver_name": driver["givenName"] + " " + driver["familyName"],
                                "constructor_id": result["Constructor"]["constructorId"], "actual_starting_grid": result.get("grid"),
                                "finish_position": result["position"], "position_text": result.get("positionText"),
                                "points": result.get("points"), "laps_completed": result.get("laps"), "status": result.get("status"),
                                "winner_label": int(result["position"] == "1")})
        for q in race.get("QualifyingResults", []):
            driver = q["Driver"]
            qualifying_rows.append({"race_id": race_id, "driver_id": driver["driverId"],
                                    "driver_name": driver["givenName"] + " " + driver["familyName"],
                                    "constructor_id": q["Constructor"]["constructorId"], "qualifying_position": q["position"],
                                    "q1_seconds": lap_seconds(q.get("Q1")), "q2_seconds": lap_seconds(q.get("Q2")),
                                    "q3_seconds": lap_seconds(q.get("Q3"))})
    write_csv(OUTPUT / "races.csv", race_rows, list(race_rows[0]))
    write_csv(OUTPUT / "qualifying.csv", qualifying_rows, list(qualifying_rows[0]))
    write_csv(OUTPUT / "race_results_labels.csv", result_rows, list(result_rows[0]))
    for filename in ["history.json", "coverage.csv", "coverage.json"]:
        shutil.copyfile(INPUT / filename, OUTPUT / filename)
    descriptions = {
        "qualifying_position": "Official qualifying position, not the later penalty-adjusted starting grid.",
        "qualifying_gap_s": "Seconds slower than the fastest best-available qualifying phase time. Q3, then Q2, then Q1 fallback; phases can have different conditions.",
        "circuit_grid_prior": "Earlier circuit/grid win prior, smoothed toward global grid rate with alpha=8. Uses only earlier races within the downloaded history.",
        "prior_starts": "Earlier observed starts at this circuit from the qualifying-position-equivalent grid slot within this downloaded history.",
        "recent_finish": "Mean finish position in the driver's last five earlier appearances; blank when no earlier history is available.",
        "recent_win_rate": "Win fraction in the driver's last five earlier appearances; blank when unavailable.",
        "team_recent_finish": "Mean finish for constructor drivers across the preceding five races; blank when unavailable.",
        "driver_id": "Jolpica driver identifier; categorical model input.",
        "constructor_id": "Jolpica constructor identifier; categorical model input.",
        "circuit_id": "Jolpica circuit identifier; categorical model input.",
        "target": "Outcome label: 1 if the driver won this target race, 0 otherwise. Never an input feature.",
        "race_id": "Race grouping key, season-round. Keep all drivers from the same race together.",
        "season": "Season used for chronological split; not part of the initial model input list.",
        "race_date": "Scheduled target race start; metadata, not a model input.",
        "cutoff": "Estimated availability cutoff: scheduled race start minus 18 hours. Not proof of actual qualifying publication.",
        "feature_version": "Version of the feature builder; metadata.",
        "availability_policy": "Disclosure of estimated historical publication timing; metadata.",
        "practice_available": "False for this export; practice features are not included. Metadata, not a model input.",
    }
    dictionary = {"numeric_features": NUMERIC, "categorical_features": CATEGORICAL, "target": "target", "group_key": "race_id",
                  "missing_values": "Empty CSV fields mean unavailable. Fit imputation on training data only.", "columns": descriptions}
    (OUTPUT / "data_dictionary.json").write_text(json.dumps(dictionary, indent=2), encoding="utf-8")
    readme = f"""# FASTLANE training datasets: 2019-2024

Real historical Jolpica-F1 results/qualifying data, fetched {history['fetched_at']}.
Source: https://github.com/jolpica/jolpica-f1
API: https://api.jolpi.ca/ergast/f1/
Source terms: https://github.com/jolpica/jolpica-f1/blob/main/TERMS.md
This is a derived personal research export, not a new license for upstream data.
No synthetic website/demo data is included.

## Files

| File | Contents |
|---|---|
| model_features_all.csv | {len(rows):,} driver-race feature rows covering {len(winners)} complete non-sprint races |
| train.csv | 2019-2022: {summary['train']['rows']:,} rows / {summary['train']['races']} races |
| validation.csv | 2023: {summary['validation']['rows']:,} rows / {summary['validation']['races']} races |
| test.csv | 2024: {summary['test']['rows']:,} rows / {summary['test']['races']} races |
| races.csv | {len(race_rows)} event metadata records, including excluded races |
| qualifying.csv | {len(qualifying_rows):,} driver qualifying rows with separate Q1/Q2/Q3 times in seconds |
| race_results_labels.csv | {len(result_rows):,} driver outcome rows for labels and earlier-race historical aggregation |
| history.json | Original assembled source records, including race outcomes |
| coverage.csv / coverage.json | Coverage and exclusion report |
| data_dictionary.json | Exact input features, target, grouping key, column meanings |
| manifest.json | Counts, missingness, provenance and file SHA-256 hashes |

## Training use

One row represents one driver in one race. `target=1` means that driver won; `target=0` means they did not.
Use ONLY the numeric and categorical feature allow-lists in data_dictionary.json as X, and target as y.
race_id groups competitors for probability normalization and race-level evaluation.

```python
import json
import pandas as pd
from pathlib import Path

base = Path("output/datasets/fastlane-2019-2024")
schema = json.loads((base / "data_dictionary.json").read_text())
train = pd.read_csv(base / "train.csv")
valid = pd.read_csv(base / "validation.csv")
test = pd.read_csv(base / "test.csv")
features = schema["numeric_features"] + schema["categorical_features"]
X_train, y_train = train[features], train[schema["target"]]
X_valid, y_valid = valid[features], valid[schema["target"]]
X_test, y_test = test[features], test[schema["target"]]
```

Fit preprocessing on training only. Tune model and within-race probability normalization on validation only.
Evaluate the final test once: race log loss, one-winner Brier and top-1 accuracy. Within each race probabilities must sum to one.
Do not randomly split driver rows: competitors from the same event must stay together.

The project already contains a full training runner. From the repository root:

```powershell
.\\.venv\\Scripts\\python.exe -m ml.training.train --features output/datasets/fastlane-2019-2024/model_features_all.csv --validation-season 2023 --test-season 2024
```

## Limitations and leakage controls

- This is qualifying/history data. No practice laps, long-run pace, telemetry, or weather are included.
- Sprint weekends and incomplete driver fields are excluded from model_features_all.csv and its splits.
- Raw races/qualifying/results include all 128 downloaded events, including excluded ones.
- Race outcomes, points, laps completed and finishing status are post-race labels. NEVER join those target-race columns into X.
- Actual starting grid comes from retrospective race results and can differ from qualifying position. Audit grid availability before using it as a pre-race input.
- Historical cutoff timestamps are estimated, not verified publication times. Audit them before live forecasting.
- The qualifying gap mixes best-available Q1/Q2/Q3 phases. qualifying.csv lets you construct phase-specific comparisons instead.
- Earlier history begins in 2019. Initial rolling features can be blank, and circuit priors have small samples.
- The test season has already been evaluated in this project. For a new untouched final evaluation, reserve a later season.
- This is a small dataset; the existing experiment's ML candidates did not beat the grid baseline on the test window.
"""
    (OUTPUT / "README.md").write_text(readme, encoding="utf-8")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name != "manifest.json"}
    manifest = {"source": history["source"], "source_fetched_at": history["fetched_at"], "feature_version": coverage["feature_version"],
                "source_races": len(race_rows), "eligible_races": len(winners), "feature_rows": len(rows), "splits": summary,
                "qualifying_rows": len(qualifying_rows), "result_rows": len(result_rows),
                "missing_feature_values": {name: sum(r[name] == "" for r in rows) for name in NUMERIC},
                "checks": {"unique_driver_race_keys": True, "one_winner_per_race": True, "disjoint_chronological_race_groups": True,
                           "cutoffs_before_race_start": True, "finite_present_numeric_features": True},
                "file_sha256": hashes, "limitations": coverage["limitations"]}
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    archive = OUTPUT.parent / "FASTLANE_training_datasets_2019-2024.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(OUTPUT.iterdir()):
            if path.is_file():
                bundle.write(path, arcname=OUTPUT.name + "/" + path.name)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert len(bundle.namelist()) == len([p for p in OUTPUT.iterdir() if p.is_file()])
    print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size, "splits": summary,
                      "feature_rows": len(rows), "qualifying_rows": len(qualifying_rows), "result_rows": len(result_rows)}, indent=2))


if __name__ == "__main__":
    main()
