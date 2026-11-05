# FASTLANE.

**Predict the unpredictable.** A local F1 race intelligence MVP based on the supplied project guide: Next.js 16 + TypeScript, FastAPI, SQLAlchemy, optional PostgreSQL, and a separate historical ingestion/feature/training pipeline.

The website serves **real data only**. It resolves the next race from Jolpica, imports published session timing with FastF1 and a free OpenF1 fallback, saves pre-race snapshots and scores them after published race results arrive. Demo fixtures are retained only for offline tests and are blocked by all serving routes. A separate worker checks sources about every 5 minutes, while visible pages refresh every minute. See [automatic refresh](docs/automatic-refresh.md).

## Run locally

Requires Node 20.9+ and Python 3.11 or 3.12. Run from the repository root. Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
npm.cmd install
.\.venv\Scripts\python.exe -m ml.live.refresh
.\.venv\Scripts\python.exe -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
npm.cmd run dev
```

Open http://127.0.0.1:3000. API docs: http://127.0.0.1:8000/docs. After setup, `powershell -ExecutionPolicy Bypass -File scripts/start.ps1` starts both processes with hidden windows and logs in `tmp/`; `scripts/stop.ps1` stops those recorded processes.

The preview created for this build uses port **3010** because 3000 was occupied. To restart it, run `powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -WebPort 3010`. The script also accepts `-ApiPort` and configures the API URL and CORS for the selected ports.

On macOS/Linux use `python3`, `.venv/bin/python`, and `npm`. The committed fixture is used only by offline tests; it is blocked from serving routes.

`.env.example` lists configuration. These are environment variables; set them in the shell or your host configuration. For a custom frontend API URL, create `apps/web/.env.local` with `NEXT_PUBLIC_API_BASE_URL=...`. FastAPI does not implicitly load a root `.env` file.

## What works

- Cinematic responsive home, sticky/mobile navigation, original WebP car artwork.
- Real FP1/FP2/FP3 and post-qualifying snapshot history, stage-specific trained models, cutoff and model version. Sprint weekends retain the explicitly experimental pace/form fallback.
- Session probability changes, frozen driver evidence and separate actual model associations, official entry-list checks, captured race-hour weather context, searchable races and phone probability cards.
- Race report cards and a Performance page with proper scores, simple baselines, calibration bins, race-cluster intervals and a paired OpenF1 source pilot. See [product improvements](docs/product-improvements.md).
- Published FP1/FP2/FP3/Q1/Q2/Q3 comparisons; missing timings and sessions absent on sprint weekends stay explicit.
- Circuit grid win/podium charts with corresponding tables, sample counts, time range and smoothed priors.
- Driver form pages, methodology, source attribution, loading/error/empty states.
- Read-only API backed by persisted immutable snapshots; schedule-based next-race selection.
- Cached, paginated Jolpica ingestion; coverage report; leakage-safe historical feature construction.
- Grid baseline, logistic regression and CatBoost; chronological splits, validation-fitted temperature, race log loss, Brier, top-1 and reliability bins.
- Automatic source-refresh worker, preserved snapshots, post-race scoring, manual backtest workflow, PostgreSQL deployment, daily verified backups, model integrity checks and operational readiness.

## Reproduce a historical experiment

```powershell
.\.venv\Scripts\python.exe -m ml.ingestion.jolpica --seasons 2019 2020 2021 2022 2023 2024
.\.venv\Scripts\python.exe -m ml.features.build
.\.venv\Scripts\python.exe -m ml.training.train --validation-season 2023 --test-season 2024 --publish-metrics
```

Raw responses are cached with source URL, retrieval time and parser version. Outputs: `data/processed/history.json`, `features.csv`, `coverage.csv`, and `coverage.json`. Each training run writes a versioned artifact directory under `ml/artifacts/` with report, probabilities, logistic artifact and CatBoost model. Seeds, feature schema, dataset SHA-256, code commit (when available), training windows, temperatures and selected model are recorded. The lowest validation log loss selects the model; test data is reserved for reporting. `--without-catboost` runs the baselines when CatBoost is unavailable.

The initial experiment excludes sprint weekends, practice, weather, and detailed telemetry. Historical qualifying publication time is estimated and explicitly disclosed. No claim of production calibration is made. See [data contract](docs/data-contract.md).

The current qualifying-history-v2 experiment retained **146 complete non-sprint events** (2,919 driver rows): 111 training races in 2018–2023, 18 validation races in 2024, and 17 development races in 2025. Qualifying gaps now compare the same phase. Development winner race log loss: grid baseline **0.894**, CatBoost **0.874**. CatBoost was selected on validation; the baseline made more correct top picks (70.6% versus 58.8%). 2025 was previously inspected, so it is not an untouched final test. The report is copied to docs/model-report.json; live refresh publishes metadata without retraining. Current reproduction commands are in [product improvements](docs/product-improvements.md).

Optional timing coverage audit:

```powershell
.\.venv\Scripts\python.exe -m ml.ingestion.fastf1_sessions --season 2024 --round 18
```

Verified schedule import (choose the intended season; cached schedules need `--refresh` to update):

```powershell
.\.venv\Scripts\python.exe -m ml.ingestion.jolpica --seasons 2026 --schedule-only --refresh
```

An imported schedule can identify the next race while its prediction remains unavailable. The API never invents a forecast for an imported event.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm.cmd run typecheck
npm.cmd run build
node --experimental-strip-types scripts/test-forecast-changes.mjs
```

Tests exercise target/future outcome exclusion, chronological race grouping, timing missingness, sprint exclusion, distribution normalization, race-level metrics, evidence availability, immutable snapshots, API unknown/missing data, and demo versus future schedule behavior.

## PostgreSQL and deployment

SQLite remains the default for local use. The production Compose stack now includes PostgreSQL 17, FastAPI, a persistent refresh worker and the standalone Next.js frontend. Backend/frontend images, PostgreSQL backup restore, source refresh and readiness were verified locally. See [deployment and recovery instructions](docs/deployment-readiness.md) for private environment configuration, persistent volumes, model training and backup commands. Public hosting is not configured.

To run the production build locally, first stop the owned app processes, then run `npm.cmd run build` and `powershell -NoProfile -File scripts/start.ps1 -WebPort 3010 -Production`.

## Sources & limitations

[Jolpica-F1](https://github.com/jolpica/jolpica-f1) supplies historical qualifying/results; [FastF1](https://docs.fastf1.dev/) provides timing. [OpenF1](https://openf1.org/docs/) supplies a free completed-practice fallback. [Open-Meteo](https://open-meteo.com/en/docs/previous-runs-api) supplies archived JMA forecasts used by the evaluated FP3 conditions model; its latest weather feed is separate context. Historical fixed-lead forecast release times remain estimated, with a conservative availability allowance. Source terms and attribution apply. The eight-weekend timing source pilot does not certify the new weather model. Delayed post-session refresh, post-race scoring and actual model associations are implemented. Public hosting is not configured. Circuit samples are small; collisions, strategy, reliability and regulations limit predictability.

Original artwork and prompt are documented in [artwork notes](docs/artwork.md). FASTLANE is an independent educational project, not affiliated with Formula 1, FIA, Formula One Management, or any team.

## Build verification

93 backend/pipeline tests passed; production Webpack build and TypeScript checks passed. All 1,300 original winner, 2,600 original outcome and 3,720 condition-model probabilities reproduce through serving code. Linear inference reads trained parameters without loading sklearn training DLLs; model weights and versions stay unchanged. Downloaded session metadata and excluded weather files are documented in [downloaded-datasets.md](docs/downloaded-datasets.md). The local preview uses port 3010. Supported Webpack/WASM handles the local native-SWC Application Control block without changing security settings. Production container builds, PostgreSQL restore and the container worker were verified; public deployment remains unconfigured.

Typography is self-hosted under apps/web/public/fonts, with the included OFL licenses. The original hero image is in apps/web/public/images/hero-car.webp; its generation prompt is in docs/artwork.md.

## Current automatic service

Qualifying now retries Jolpica, OpenF1 and FastF1, preserving the last complete classification during outages and appending a new pre-race revision when published inputs change. The 2026 US Q1/Q2/Q3 tables and qualifying prediction were verified with all 22 drivers. Local startup supervises/restarts the worker after unexpected exits; a controlled crash/recovery test passed. See [automatic refresh](docs/automatic-refresh.md) for source delays, provenance checks and the requirement that the local computer remain awake/online.

Weather update (25 October): archived JMA forecasts and prior driver/team/circuit nonfinish features are trained and evaluated. Only FP3 cleared the matched no-weather validation gate and uses the new weather-aware model; FP1, FP2 and qualifying retain existing models. The latest weather card remains context, while the new factor card identifies the fixed-lead forecast actually consumed. Sources, coverage, scores and reproduction commands: [weather and conditions](docs/weather-and-conditions.md). Results are on `/performance#weather-models`.

FP1/FP2/FP3 model update: separate practice/history models have been trained and activated. See [practice-models.md](docs/practice-models.md) for coverage, all candidate scores and exact reproduction commands. Standard weekends use the selected stage artifact; sprint formats retain the explicitly experimental fallback. FP1 did not improve on the pace baseline in the 2025 development benchmark, so the models remain experimental.

Use scripts/start.ps1 -WebPort 3010 to start the website, API, and source-refresh worker together. The computer must remain awake with internet access. Public 24/7 hosting has not been configured. No API key or subscription is needed for the configured post-session sources. Separate experimental practice models serve standard weekends; qualifying uses its own artifact. Sprint weekends retain the labeled pace/form fallback. Upcoming races show waiting states until eligible session data is published. Historical events without recorded pre-race predictions are not scored using invented forecasts.

## Outcome forecasts and dashboard

The overview now prioritizes a compact forecast table with sortable winner, podium and top-10 probabilities. Inter is self-hosted, and model/source details are expandable. Session tables expose genuine median clean laps, long-run proxies, compound and sample sizes; additional tyre and consistency data is available on demand.

Eight logistic regression models predict podium/top-ten finishes across FP1, FP2, FP3 and qualifying. They reuse stage-safe data with classified-position labels and were retrained against the corrected qualifying winner model. Practice winner artifacts remain unchanged. See [outcome-models.md](docs/outcome-models.md) for training commands, constraints and restrictions. Old snapshots remain unchanged and sprint forecasts leave unsupported outcome columns unavailable. The frontend uses Next.js 16.4.3 with React / React DOM 19.3.1. Hero image qualities are explicitly configured for 75 and 85.

The qualifying champion is pinned; manual training creates candidates without replacing it. New pre-race snapshots also record matched simple baselines for prospective Performance comparisons. See [deployment verification](docs/deployment-readiness.md).
