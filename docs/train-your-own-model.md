# Training FASTLANE with the downloaded datasets

The qualifying model and separate practice models are already trained. You can reproduce training locally with these commands. Run from the FastLane project directory in PowerShell.

For the weather/conditions candidate added on 25 October, use the separate [weather training workflow](weather-and-conditions.md). Only FP3 passed its matched validation gate. The original stage-model commands below still build the base models; changing their versions requires revalidating conditions.

## Qualifying/history model

```powershell
.\.venv\Scripts\python.exe -m ml.ingestion.kaggle --source "C:\Users\yashm\Downloads\archive (1).zip"
.\.venv\Scripts\python.exe -m ml.features.build --history data/processed/kaggle-2018-2025/history.json --first-season 2018 --last-season 2025 --output-dir data/processed/qualifying-v2
.\.venv\Scripts\python.exe -m ml.training.train --features data/processed/qualifying-v2/features.csv --validation-season 2024 --test-season 2025 --publish-metrics
.\.venv\Scripts\python.exe -m ml.training.outcomes --activate
.\.venv\Scripts\python.exe -m scripts.verify_outcome_models
.\.venv\Scripts\python.exe -m ml.validation.backtest
```

The builder uses **qualifying-history-v2**: gaps compare the same qualifying phase and teammate gaps use their highest common phase. The trainer rejects old/missing feature-version columns. Rebuild old CSVs before training. The outcome command retrains eight podium/top-10 models against current winner versions; changing the winner model disables incompatible outcome artifacts until this completes.

Training uses 2018–2023, validation uses 2024, and 2025 is a previously inspected **development benchmark**, not an untouched final test. Preprocessing fits only training; temperatures and model selection use validation. All rows from a race stay together. Training writes a new versioned directory under `ml/artifacts/`. `--publish-metrics` publishes report metadata; it does not manufacture historical forecasts. `--without-catboost` runs baseline candidates only.

The table contains 2,919 driver rows / 146 complete non-sprint races: 111 training, 18 validation and 17 development races. Sprint and incomplete events are excluded; inspect the generated coverage CSV. Historical publication cutoffs remain estimated. The 1950-onward source provides broader history, but the modern target window starts in 2018. Usable warmup records with exact UTC race starts in this archive begin in 2005. Earlier history is context, not automatically more comparable training examples.

## Practice models

See [practice-models.md](practice-models.md) for archive preparation, stage-specific training commands, coverage and scores. Real FP1/FP2/FP3 timing archives are already integrated. Do not use target-race laps as practice inputs. Each stage can use only that session and earlier evidence. Standard weekends use trained stage models; sprint formats keep an experimental fallback with unsupported extra targets unavailable.

## Downloaded Zenodo data

```powershell
.\.venv\Scripts\python.exe -m ml.ingestion.audit_laps --source "C:\Users\yashm\Downloads\f1_enriched_driver_lap.csv"
```

The local file was audited: 191,602 rows, all `SessionName=Race`, including 3,038 rows from 2026. It contains no practice or qualifying rows. Its target-race lap timing, telemetry, observed weather and running order would leak future information into pre-race forecasts. Earlier-race aggregates could support a separate shifted-history experiment, with availability and validation checks. It is not merged as practice data.

Kaggle standings are after-race snapshots; use only an earlier event's standings. Actual starting grids can include penalties announced after qualifying; do not replace qualifying position without an availability audit. Observed race weather is not a historical pre-race weather forecast. Captured current race-hour weather is displayed as context, not used by the model.

## Evaluate before claiming improvement

```powershell
.\.venv\Scripts\python.exe -m ml.validation.source_audit --limit 8
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --experimental-strip-types scripts/test-forecast-changes.mjs
npm.cmd run build
```

The source audit reuses caches or downloads free paired OpenF1 sessions. It checks an eight-weekend FP2 pilot, not universal source equivalence. `/performance` exposes all three outcomes, baselines, calibration bins and race-cluster intervals. The v2 qualifying model has lower 2025 race log loss than the grid baseline (0.874 versus 0.894) but lower top-pick accuracy (58.8% versus 70.6%). Neither one metric nor a small sample establishes robust calibration. Reserve future prospectively recorded races for stronger evaluation. See [product improvements](product-improvements.md) for full behavior and limitations.
