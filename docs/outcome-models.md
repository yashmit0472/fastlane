# Podium and top-10 models

Run from the project directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m ml.training.outcomes --activate
.\.venv\Scripts\python.exe -m scripts.verify_outcome_models
```

The first command fits eight logistic regression models: podium and top ten for FP1, FP2, FP3 and qualifying. It reuses the stage-safe 2018–2025 feature tables already built in the project. No extra download is needed. Full classified results from the imported history join **only as labels**; they are excluded from the feature whitelist.

Training is 2018–2023, validation is 2024 and the development benchmark is 2025. Preprocessing fits only training rows. Each target selects logistic or constrained uniform on validation binary log loss. The 2025 benchmark was already inspected during earlier development and is not an untouched test. No hyperparameter search against that benchmark was performed here.

Podium marginals use winner probabilities as lower bounds, and top-ten marginals use podium probabilities as lower bounds. An odds shift finds probabilities that sum to exactly 3 or 10 for the whole field. This is a documented constraint, not a full joint finishing-order distribution or a guarantee of calibration. Model selection and metrics use the constrained outputs, including the corresponding saved winner model. A winner-model version change disables these extra targets until they are retrained against it. On 24 October the qualifying model was corrected to use same-phase gaps and the full outcome bundle was retrained/activated against current winner versions.

The 2025 qualifying benchmark contains 17 races: podium binary log loss 0.213 versus constrained uniform 0.309; top-ten 0.535 versus 0.588. Corresponding per-driver Brier scores are 0.063 and 0.174. These binary metrics average across drivers within each race, then across races. They differ in scale from winner race log loss and summed Brier scores. All stage reports are saved in `docs/outcome-model-reports.json`. The Performance page adds recent-form/qualifying baselines, reliability bins and race-cluster intervals; see [product improvements](product-improvements.md).

Artifacts and SHA-256 checksums are stored under `ml/artifacts/outcomes-v1-<timestamp>/`. All four stages must complete before activation atomically replaces `ml/artifacts/outcomes-active.json`. The API never trains models. The verification command reproduces 2,600 benchmark marginals through serving code without writing historical forecasts to the database.

Sprint weekends remain outside these models' training coverage, so extra targets remain unavailable there. Old saved winner-only snapshots are preserved. Newly observed source data must still be available before race start; no retrospective predictions are invented. After results arrive, saved podium/top-ten probabilities are scored only when the published classification matches the full forecast field.

The redesign exposes existing real timing information: clean-lap median, long-run proxy and compound, stint sample size, lap spread, soft-tyre share and mean tyre age. Missing values remain missing. The long-run proxy is not fuel-adjusted. This change adds outcome targets and makes collected inputs easier to inspect; it does not claim a newly improved winner model or add weather features.

Inter is self-hosted from the font author's repository under its included SIL Open Font License: https://github.com/rsms/inter . Browsers do not request fonts from a third-party CDN.
