# Deployment and model verification

The application serves saved real forecasts and refreshes published session data with a persistent worker. No public hosting has been configured. Keep the computer awake for local updates.

## Verified on 26 October 2026

- 93 backend/pipeline regression tests, production Webpack build (including TypeScript), and session probability-change checks passed.
- Backend and standalone frontend Docker images built. PostgreSQL 17, API, worker and frontend ran successfully. A real SQLite backup restored into an empty PostgreSQL database: 24 races, 1,656 snapshots and one system-state record. The restored report cards served successfully.
- The production worker completed a source refresh and verified its automatic backup. `/ready` returned ready with no blockers or backup warnings.
- The clean Python 3.12 Linux training environment fitted logistic and CatBoost models. Full qualifying training reproduced the original 2025 development benchmark: CatBoost race log loss 0.87435 versus grid baseline 0.89441. The grid baseline still had better top-pick accuracy. This is reproducibility, not a new improvement or untouched test result.
- The qualifying champion is explicitly pinned with report and weight checksums. Training writes candidates without promoting them. Active practice, outcome and weather selection decisions remain unchanged. See `model-readiness-report.json` for the inference audit; only the FP3 weather candidate passed its activation gate.
- Published FastF1 final results mapped all 22 US GP entrants. OpenF1 had null positions for three retired drivers; those incomplete responses are rejected rather than assigning invented finishing ranks.

PostgreSQL data also survived a Docker engine restart, verified by reading the restored prospective report cards afterward. Docker became temporarily unavailable after host memory pressure and recovered through a Desktop restart. An isolated TypeScript run initially ran out of memory, then passed serially; the final production build also passed. The initial visual-check tools timed out. Desktop and mobile visual/interaction checks subsequently passed on 29 October; screenshot export later stalled. See `release-verification.json` for the verification record.

## Start the local production build

From the project root in PowerShell:

```powershell
npm.cmd run build
powershell -NoProfile -File scripts/start.ps1 -WebPort 3010 -Production
```

Stop the existing owned processes first with `scripts/stop.ps1` when restarting. The launcher starts the API, standalone frontend and supervised refresh worker. Static assets, self-hosted fonts and car artwork are copied into the standalone output.

## Run the container stack

Create a private environment file, for example `deploy/runtime/production.env`, containing a strong URL-safe `POSTGRES_PASSWORD`, `WEB_PORT=3000`, `API_PORT=8000` and the intended `CORS_ORIGINS`. Never commit passwords. Then:

```powershell
docker compose --env-file deploy/runtime/production.env up -d --build
docker compose --env-file deploy/runtime/production.env ps
```

PostgreSQL has no host port. The web/API ports bind to loopback by default; configure a TLS reverse proxy and real domain when choosing a public host. Model artifacts and prepared historical data must be present on the host. Models and prepared history are mounted read-only in serving containers. Database and runtime caches/backups use persistent named volumes. Do not use `down -v` against data you need.

Probe training without changing serving artifacts:

```powershell
docker compose --env-file deploy/runtime/production.env --profile training run --rm --no-deps training
```

Reproduce the actual qualifying experiment (writes a new candidate, no activation):

```powershell
docker compose --env-file deploy/runtime/production.env --profile training run --rm --no-deps training python -m ml.training.train --features data/processed/qualifying-v2/features.csv --validation-season 2024 --test-season 2025
```

Windows Application Control still blocks a sklearn training DLL on this machine. Linux containers provide a working training environment without modifying security policy. Serving uses the original trained coefficients through the verified parameter-only inference path.

## Recovery and operations

The worker checks sources about every five minutes; visible pages refresh each minute. Free OpenF1 retrieval waits until at least 30 minutes after published session end. Practice uses FastF1 then OpenF1; qualifying uses Jolpica, OpenF1 and FastF1; final classifications use Jolpica, complete OpenF1 results, then published FastF1 results. FastF1's results backend can share Jolpica availability. Empty or partial replies retry; complete cached data survives outages. Race results retry during the first seven days after race start and cached classifications remain available afterward. Later corrections update scores, never the frozen pre-race picks.

`/health` checks database liveness. `/ready` checks worker freshness, active model integrity and prepared history; `/api/system/operations` also exposes backup warnings. The website shows delayed-update states. Deduplicated issue/recovery transitions are saved locally in `data/operations/alerts.jsonl`; external notifications are not configured. A Docker health failure marks a stalled process unhealthy; it does not itself restart a still-running hung process. Restart policies recover exited processes. A host monitor should alert on unhealthy services.

Daily backups include a consistent database export, SQLite hot copy when applicable, model artifacts, history and source provenance, with SHA-256 and ZIP integrity checks. Backups stay on the same machine until copied off-host; choose an off-host location and retention policy before public operation. No automatic deletion is configured.

```powershell
.\.venv\Scripts\python.exe -m scripts.maintenance
.\.venv\Scripts\python.exe -m scripts.backup --verify data/backups/YOUR_BACKUP
.\.venv\Scripts\python.exe -m scripts.backup --restore data/backups/YOUR_BACKUP --database-url sqlite:///./tmp/recovered.db
```

Restore refuses a nonempty database. The same export restores into PostgreSQL using its explicit database URL. The model/history ZIP is a separate recovery payload: restore it into an isolated checkout, verify the artifacts, then point the recovered service at the restored database. Do not overwrite a running service's model directory.

## Evidence still accumulating

New pre-race forecasts save recent-form and qualifying-only comparator probabilities at the same cutoff. Performance compares only matched race/stage/model cohorts. Old forecasts are never retroactively assigned baselines. One completed prospective weekend cannot establish calibration or generalization. More genuinely future races and a larger paired timing-source audit are needed, rather than another uncurated CSV download. Free providers and an available host cannot guarantee uninterrupted updates.
