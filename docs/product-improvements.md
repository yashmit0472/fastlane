# Forecast evidence, validation and report cards

Implemented 24 October 2026. Local preview: http://127.0.0.1:3010 . The original car artwork, dark racing design and self-hosted Inter remain in place.

Weather follow-up on 25 October: the archived forecast gap was partly resolved with JMA fixed-lead data; an evaluated FP3 weather/conditions model is now active. The weather-only-context statements below describe the 24 October implementation. See [weather and conditions](weather-and-conditions.md) for current behavior, missing-year coverage and validation limits.

## What is available

1. **Performance** (`/performance`) compares all three outcomes at each stage with training-only recent-form and equal-chance baselines. Qualifying also has a qualifying-position baseline. It shows binary log loss, per-driver Brier score, fractional top-k recall, race-balanced reliability bins/ECE and 95% race-cluster bootstrap intervals (300 resamples, seed 42). Comparisons use the same races within a stage; coverage differs between stages. Reports: `validation-report.json` and `source-validation-report.json`.
2. **What changed** on each race page compares the selected saved forecast with the latest earlier stage available at its cutoff. Winner, podium and top-10 changes are in percentage points. A driver journey plots saved stages only. Missing previous probabilities are never zero-filled. Stage-model changes are disclosed.
3. **Compare drivers** combines frozen recent finishes, practice best/median and clean-lap counts, same-phase qualifying gaps and common-phase teammate gaps. Long-run teammate comparisons require a known matching compound. Separate expandable model associations use actual CatBoost SHAP values or standardized/encoded linear terms. These describe the fitted raw score before calibration and field constraints, not causal effects or probability-point changes.
4. **Race report cards** select the latest real pre-race revision per stage and compare saved picks/probabilities with the published full classification. The overall page groups scores by stage and winner-model version and shows per-race/cumulative trends. Older races with no saved forecast retain results and an honest empty report card. No retrospective predictions were inserted. At verification there were 17 completed races and zero completed races with saved forecasts; prospective scores will appear once a recorded race finishes.
5. **Input quality** shows roster provenance, timing coverage, guest practice participants, missing drivers and small samples. Official FIA document links are discovered from the event documents page; a complete unambiguous main entry table must match canonical driver identities. FP1-only reserves are excluded. Failed or unknown mappings keep the provisional label. The current US entry document lists 22 main identities but prints Perez's number as 111; the timing number 11 is retained and the discrepancy is visibly disclosed. Weather is captured from Open-Meteo for the race hour with retrieval/valid timestamps and frozen with each eligible forecast. It is context only, not a model input.
6. **Race navigation and mobile** add a race chooser, searchable/filterable race list, driver search, sortable outcomes and phone cards displaying all three probabilities together. Comparison tables wrap within the page. At 390px viewport width, the race page has no horizontal document overflow.

## Corrected qualifying model

`qualifying-history-v2` compares each driver's last completed phase against the fastest time in that same phase. Teammate gaps use their highest common phase. The training command rejects old/missing feature-version columns instead of applying the new semantics to old CSVs.

The rebuilt table has 2,919 rows / 146 standard weekends: training 111 races (2018–2023), validation 18 (2024), development benchmark 17 (2025). CatBoost was selected on validation. Its 2025 winner race log loss is 0.874 versus grid baseline 0.894; top-pick accuracy is 58.8% versus the baseline's 70.6%. The change corrects comparability; it does not establish improvement on every metric. The eight podium/top-10 models were retrained against the active winner versions; 2,600 saved development marginals reproduce through serving code. New report: `model-report.json`; outcome reports: `outcome-model-reports.json`.

2025 was inspected in earlier development, so these are development benchmarks, not untouched final tests. Historical publication cutoffs remain estimated. Sprint forecasts retain the explicitly experimental fallback and unsupported extra targets remain unavailable.

## OpenF1 source check

An eight-weekend paired 2025 FP2 pilot fixes entrant field, earlier FP1 inputs and model versions, and changes only the FP2 source. Per-driver race-balanced Brier scores:

| Outcome | FastF1 | OpenF1 |
| --- | ---: | ---: |
| Winner | 0.0447 | 0.0455 |
| Podium | 0.0868 | 0.0889 |
| Top 10 | 0.1740 | 0.1723 |

This identifies source differences; it does not certify production calibration, every stage, every circuit or current regulations. The paired source report includes sessions, input discrepancies, proper scores and calibration bins. Historical source availability is estimated; it never publishes these experiments as historical live predictions.

## Reproduce locally

Run in PowerShell from the project directory, with dependencies and the existing downloaded data already installed:

```powershell
.\.venv\Scripts\python.exe -m ml.features.build --history data/processed/kaggle-2018-2025/history.json --first-season 2018 --last-season 2025 --output-dir data/processed/qualifying-v2
.\.venv\Scripts\python.exe -m ml.training.train --features data/processed/qualifying-v2/features.csv --validation-season 2024 --test-season 2025 --publish-metrics
.\.venv\Scripts\python.exe -m ml.training.outcomes --activate
.\.venv\Scripts\python.exe -m ml.validation.backtest
.\.venv\Scripts\python.exe -m ml.validation.source_audit --limit 8
.\.venv\Scripts\python.exe -m scripts.verify_outcome_models
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --experimental-strip-types scripts/test-forecast-changes.mjs
npm.cmd run build
```

Training/revalidation is a separate offline operation. The source audit uses cached responses when present, otherwise free public endpoints. The serving worker only fetches and runs existing artifacts. The UI refreshes each minute; the worker polls approximately every five minutes. Free OpenF1 availability is delayed after sessions; this is not in-session streaming. Windows startup/build uses supported Webpack/WASM because local Application Control blocks the native SWC compiler; no security policy is changed.

## Data still needed for further model work

No extra dataset is required for these six features. The existing historical and practice data are sufficient. To train **race-weather effects**, obtain archived forecasts with genuine issue times before each historical prediction cutoff, a race-hour valid time and circuit coordinates. Race-day observed weather does not substitute for that dataset. The later conditions experiment now enables only the FP3 candidate that passed its validation gate; other stages retain weather as context. See weather-and-conditions.md. A larger paired OpenF1 sample across stages/seasons and future prospectively recorded races would strengthen validation before making accuracy or calibration claims.


## UI polish — 29 October 2026

The original car artwork and dark/red racing identity remain. The overview now has subtle pointer parallax, staged headline entrances and a layered, tilting circuit illustration with an animated racing line. The illustration is decorative and explicitly labelled, rather than presented as an exact track map or live telemetry. The weekend spotlight uses actual imported race/session times; its controls update the selected session note.

Cards, controls, page headings, data rows and navigation share refined typography, borders and hover transitions. Intersection-based entrances progressively enhance visible content; pages remain readable without JavaScript. Reduced-motion preferences disable animation/parallax, and the circuit has an explicit pause control. Mobile navigation supports Escape with focus restoration. No runtime dependencies, external visual services, paid assets or ML weight changes were introduced.

Browser review covered desktop and phone layouts, schedule selection, animation pause, mobile navigation, actual driver search and podium sorting, with no horizontal page overflow or console errors on the inspected pages. The browser tool later stalled while exporting screenshots; the temporary viewport was reset. Production compilation/TypeScript, 93 regression tests, session-change checks and actual real-data page/API checks passed. The legacy verify_local smoke-check entry point now runs the real-only check rather than expecting demo fixtures. Operational status requests allow a longer cold-start check without delaying ordinary data requests.

Public hosting/domain/TLS, off-host backup storage and optional external notifications are deployment configuration, not local MVP features. Forecast accuracy still needs genuinely future races; the UI work makes no new model-performance claims.
