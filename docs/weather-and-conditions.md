# Weather and race-condition model factors

Implemented 25 October 2026. No paid data subscription or new API key is configured. These sources support this educational, non-commercial local project.

## Datasets and sources

| Source | What FASTLANE uses | Availability rule |
| --- | --- | --- |
| [Open-Meteo Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api) — JMA GSM | Race-start temperature, forecast precipitation amount, 10m wind and humidity at a fixed three-day lead | Fixed lead plus conservative six-hour release allowance for historical training; actual retrieval timestamp for new live predictions |
| [Kaggle F1 relational source](https://github.com/Arths17/f1-dataset) — existing downloaded archive | Prior classified results and the status dictionary for driver, team and circuit nonfinish history | Earlier races only; current/future results never enter features |
| [FastF1](https://docs.fastf1.dev/) and the existing [TracingInsights archives](https://github.com/TracingInsights/2024) | Existing practice pace, compound-aware long-run proxies and sample features | Completed session or earlier stages only |
| [Open-Meteo Single Runs API](https://open-meteo.com/en/docs/single-runs-api) | A useful future source for exact initialization-time forecasts; not mixed into this experiment | ECMWF coverage starts March 2024; other models start April 2026 according to the documentation |

The weather audit downloaded **123 complete archived forecast records out of 149 eligible history weekends**. All 21 weekends in 2018 and five later weekends lacked complete required variables. Missing weather stays missing; those races are excluded from this experiment, with every reason in `data/raw/race-conditions/coverage.json`. The project does not claim 2018 weather coverage just because a source's general documentation mentions 2018.

Each successful response is cached with its URL, retrieval time, model, lead time, coordinates, valid time, units and response SHA-256 in `data/raw/race-conditions/`. The status map is read from the already downloaded Kaggle ZIP. The enriched tables and exclusion reports are in `data/processed/conditions/`.

**These are archived forecasts, not ERA5 reanalysis or observed target-race weather.** The historical archive exposes fixed lead offsets rather than original receipt timestamps; its historical release availability remains an explicit estimate. A six-hour allowance is applied before checking each stage cutoff. Earlier Thursday stages that fail that cutoff are excluded. New live data must actually have been retrieved before its forecast cutoff.

## Features and model selection

The new candidate adds temperature, precipitation amount, wind, humidity, weather-by-driver/team-form interactions, smoothed prior driver/team nonfinish rates, circuit nonfinish history and sample counts to each existing stage's allowed features. The driver window is ten earlier starts; the team window is five earlier events; the circuit window is ten earlier events. Unknown statuses are excluded; `Finished` and lapped finishers count as finishers. Nonfinish includes accidents and exclusions and is not a mechanical-failure probability. The smoothing prior is one nonfinish in five equivalent starts.

Rainfall is a **deterministic forecast amount in millimetres**, not a rain probability. A fixed 72-hour lead is used consistently for training and live inference. The separate latest Open-Meteo weather card remains context only; the model factor card identifies the older JMA forecast it actually consumes.

For each stage, fixed-seed logistic and CatBoost weather candidates are compared with the current model and both matched no-weather ablations. Training uses available races in 2019–2023, selection/temperature fitting uses 2024, and 2025 is a previously inspected development benchmark. Whole races remain together. The activation gate requires the mean of winner/podium/top-10 validation binary log losses to improve by more than 0.001 over current serving and both no-weather ablations; no outcome may worsen more than 5% relative to current serving. 2025 results do not control activation.

**Only FP3 passed.** Its cohort has 75 training, 15 validation and 16 development races. Mean validation binary log loss: original stage models 0.31116; no-weather CatBoost 0.30503; weather CatBoost 0.30335. FP1, FP2 and qualifying keep their existing models. FP2's apparent improvement versus the original model disappeared in the matched weather ablation. No extra search was performed to force these stages through the gate.

On the 16-race 2025 FP3 development cohort:

| Outcome | Original binary log loss | Weather binary log loss | Original Brier | Weather Brier |
| --- | ---: | ---: | ---: | ---: |
| Winner | 0.14369 | 0.13853 | 0.04280 | 0.04230 |
| Podium | 0.29757 | 0.26393 | 0.09563 | 0.08151 |
| Top 10 | 0.58726 | 0.58309 | 0.19395 | 0.19492 |

These are race-balanced per-driver binary scores. Gains are mixed across metrics; this is not guaranteed improvement or calibration certification. The 2025 no-weather CatBoost ablation also remains competitive. All candidate scores, reliability bins, race-cluster intervals, race IDs, checksums and selection rules are in `docs/conditions-model-report.json`, exposed at `/api/model/conditions` and on `/performance#weather-models`.

## Serving behavior

The worker fetches compatible weather before inference. It uses the conditions candidate only for an enabled standard-weekend stage, complete matching weather, current base-model versions and artifacts created before cutoff. Missing weather, unsupported sprint formats, or a changed base-model bundle retain the existing forecast. Future incidents, actual safety cars, later grid changes and future tyre strategies are not model inputs. Air temperature is not track temperature.

Predictions store the source forecast, actual availability timestamp, model version, frozen prior nonfinish evidence and real SHAP contributions. Weather terms and interactions have their own association family. Probability marginals still sum to 1 / 3 / 10 and nest winner ≤ podium ≤ top 10. Changed model or weather inputs create a new immutable pre-race revision; old snapshots stay intact. Report cards keep conditions versions separate. No historical predictions were inserted into the live database.

OpenF1 timing substitution remains experimental: the earlier eight-session source audit evaluates the original FP2 model, not the new FP3 weather model. Missing practice samples and source-switch caveats stay visible. A larger paired audit and future prospective race results are still needed.

## Reproduce

From the project directory in PowerShell, after the original historical/practice feature tables have been built:

```powershell
.\.venv\Scripts\python.exe -m ml.ingestion.condition_forecasts --status-archive "C:\Users\yashm\Downloads\archive (1).zip"
.\.venv\Scripts\python.exe -m ml.training.conditions --activate
.\.venv\Scripts\python.exe -m scripts.verify_condition_models
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
npm.cmd run build
```

The first command reuses successful cached records. The training command creates a new versioned bundle and atomically activates all stage decisions only after completion. The verification command reproduces **3,720 saved condition probabilities**, checks nested/summed marginals and confirms weather-input sensitivity without writing serving snapshots. Model fitting and downloads do not run in API requests. No additional manual dataset download is needed.
