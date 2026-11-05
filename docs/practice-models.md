# FP1, FP2 and FP3 models

All three stage models were trained and activated locally on 19 October 2026. Nothing is needed from the user to run the current bundle. The qualifying artifact remains separate.

Later on 19 October, a downloaded 2023 session index was added for optional historical timing/cancellation cross-checks. See [downloaded-datasets.md](downloaded-datasets.md). The active model training files remain the original versioned inputs; metadata integration is verified in a separate audit output. Invalid Berlin weather downloads are excluded.

## Data and features

The downloaded Zenodo CSV contains race sessions, so it is not used as target-weekend practice data. The new importer downloads the public FastF1-derived [TracingInsights archive](https://github.com/TracingInsights/2024) with pinned repository commits, SHA-256 checksums and repository license copies. It fetched 422 of 447 requested non-sprint session files for 2018–2025. Missing/cancelled files, timestamp mismatches and insufficient clean-lap coverage are recorded in data/processed/practice-2018-2025/coverage.json.

The archive is parsed as JSON, never executed. Seconds are checked before conversion to milliseconds. Pit, deleted, inaccurate and non-green laps are excluded. A cross-source audit against the downloaded Kaggle practice table matched 1,027 driver/session pairs: 91.4% agreed within 1ms, 98.0% within one second, and the median difference was zero. Filtering and later timing corrections can explain differences. The attempted direct FastF1 2024 FP1 check was unavailable upstream; it is not counted as a successful independent verification. Historical roster mismatches between source tables, including a later DNS withdrawal, are excluded as well. Final stage coverage is 126 FP1 races / 2,519 rows, 133 FP2 races / 2,659 rows, and 131 FP3 races / 2,619 rows.

Features include within-session best/median gaps, valid-lap counts, variability, teammate gaps, tyre composition/age and a same-compound consecutive-lap long-run proxy. The latter is not fuel-adjusted. Earlier driver, team and circuit history supplies form. Practice models never use target-event qualifying, grid, race laps, points or finishing positions as inputs. Race outcomes supply labels only.

FP1 accepts FP1 only; FP2 accepts FP1–FP2; FP3 accepts FP1–FP3. The same feature implementation is used for training and live inference. Missing earlier sessions remain missing, not zero pace. The current stage requires usable timing for at least 70% of the entered field. Session/race identities and observed-at cutoffs are checked before inference.

## Chronological training

| Stage | Train 2018–2023 | Validation 2024 | Development test 2025 | Selected on validation |
|---|---:|---:|---:|---|
| FP1 | 96 races | 16 races | 14 races | Logistic regression |
| FP2 | 100 races | 16 races | 17 races | CatBoost |
| FP3 | 98 races | 16 races | 17 races | CatBoost |

Every stage compares uniform, a fixed practice pace/form baseline, a history-only logistic model, practice/history logistic regression and CatBoost. Preprocessing is fitted only on training. Early stopping, model selection and probability temperature use validation. Test scores do not select the artifact. Equal-probability leaders receive fractional top-pick credit; result-row order cannot inflate a uniform baseline. Rows are ordered by driver identifier independently of results.

| Stage / selected model | Test log loss ↓ | Pace baseline log loss ↓ | Selected top-pick accuracy |
|---|---:|---:|---:|
| FP1 / logistic | 2.473 | 2.327 | 21.4% |
| FP2 / CatBoost | 1.994 | 2.644 | 23.5% |
| FP3 / CatBoost | 1.950 | 2.584 | 11.8% |

FP1 did not beat the pace baseline on test log loss. Its validation-selected logistic model was retained rather than switching to the better test-performing CatBoost after seeing the test. FP2/FP3 improved log loss, but accuracy is modest; FP3 did not improve top-pick accuracy or Brier versus the pace baseline. Cohorts differ, so stage headline scores are not directly comparable. docs/practice-model-reports.json also includes all candidate scores, reliability bins, data hashes and a matched 14-race comparison.

2025 was previously inspected for qualifying, and is a development benchmark rather than an untouched final test. Historical availability uses last recorded session lap plus ten minutes, not an archived publication proof. The historical roster is retrospectively confirmed; live rosters remain provisional. These models are experimental, not production-certified or guaranteed calibrated. Sprint weekends are excluded from their training and retain the labeled pace/form fallback. A later untouched evaluation window and roster-aware backtests remain necessary.

## Live integration

ml/artifacts/practice-active.json identifies the three checksummed reports. The worker loads the selected stage artifact and checks its schema, stage, local path and artifact checksums. It rejects models created/fitted after the forecast cutoff. Archived sessions cannot manufacture pre-race forecasts. There is no training in API requests or normal startup.

Model reports are served at /api/model/practice and displayed at /methodology and /methodology/practice. Restart the worker after changing its code; an activated bundle is picked up on its next refresh. Upcoming standard weekends use learned stage models once actual eligible timing arrives. The scheduled sprint weekend uses the explicit fallback instead.

## Reproduce from PowerShell

Run from C:\Users\yashm\Desktop\CODE\FastLane:

```powershell
.\.venv\Scripts\python.exe -m ml.ingestion.practice_archive
.\.venv\Scripts\python.exe -m ml.features.practice
.\.venv\Scripts\python.exe -m ml.ingestion.audit_practice --kaggle "C:\Users\yashm\Downloads\archive (1).zip"
.\.venv\Scripts\python.exe -m ml.training.practice --activate
.\.venv\Scripts\python.exe -m scripts.verify_practice_models
powershell -ExecutionPolicy Bypass -File scripts/restart-worker.ps1
```

Downloads resume from successfully cached files. No account, paid API key or GPU is required. Training uses two CPU threads for CatBoost and writes a fresh versioned artifact directory. Failed runs do not replace the active bundle. Preliminary runs before the tie-scoring fix have an INVALIDATED.txt marker and are not activated.

Local verification: 35 regression tests passed, along with TypeScript and the production build. Saved-model inference reproduced all 960 held-out driver probabilities exactly across the three stages. Eleven real-data page checks and all 17 completed-race archive checks passed; both methodology routes served the practice reports successfully. No historical forecasts were published during verification. Browser visual checks are separate from HTTP/build checks.
