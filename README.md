# FASTLANE

**[Open the live FASTLANE dashboard](https://fastlane-psi.vercel.app/)** · [Model performance](https://fastlane-psi.vercel.app/performance) · [API health](https://fastlane-api-2dui.onrender.com/health)

FASTLANE forecasts Formula 1 race outcomes using published session timing, qualifying and historical results. It estimates each driver's chances of winning, making the podium and finishing in the top 10. The app saves pre-race forecasts after eligible sessions and scores them against the official classification when it becomes available.

- Compare FP1, FP2, FP3 and post-qualifying forecasts, with probability changes, driver form and the evidence available at each cutoff.
- Explore practice pace, qualifying phases, circuit history, weather and race results. Sprint weekends use a labeled experimental fallback where supported.
- Review saved forecasts against published results and simple baselines on the Performance page. Each forecast shows its data cutoff and model version.

The frontend uses **Next.js, TypeScript and React**. **FastAPI and SQLAlchemy** serve saved forecasts from PostgreSQL in production or SQLite locally. The Python pipeline uses CatBoost and logistic regression alongside qualifying-position and recent-form baselines.

## Model evaluation

The qualifying model used 111 races from 2018–2023 for training and 18 races from 2024 for validation. The table shows post-qualifying forecasts on 17 standard-format races from the 2025 development backtest.

| Metric | FASTLANE | Qualifying-position baseline |
| --- | ---: | ---: |
| Winner top-pick accuracy | 58.8% (10 of 17) | 70.6% (12 of 17) |
| Podium recall | 68.6% | 74.5% |
| Top-10 recall | 72.4% | 76.5% |
| Race-winner log loss (lower is better) | 0.874 | 0.894 |

Podium and top-10 recall measure the share of actual finishers captured by the predicted group, regardless of finishing order. The winner comparison uses historical win rates by qualifying position. The recall comparisons use logistic regression with qualifying position as its only input. The 2025 races had been inspected during development, and historical session publication times were estimated. See the [winner report](docs/model-report.json), [stage-by-stage benchmark](docs/validation-report.json) and [evaluation and reproduction notes](docs/product-improvements.md).

## Run locally

Use Node.js 22 and Python 3.12, the versions used in CI. On Windows, run these commands from a fresh checkout in PowerShell.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
npm.cmd ci

New-Item -ItemType Directory -Force ml/artifacts, data/processed/kaggle-2018-2025 | Out-Null
Copy-Item -Path 'deploy/bundle/models/*' -Destination 'ml/artifacts' -Recurse
Copy-Item -LiteralPath 'deploy/bundle/history.json' -Destination 'data/processed/kaggle-2018-2025/history.json'

powershell -NoProfile -File scripts/start.ps1
```

The start script launches the frontend, API and refresh worker. Open the [local dashboard](http://127.0.0.1:3000) or the [local API docs](http://127.0.0.1:8000/docs). The first refresh needs an internet connection. Use `-WebPort 3010` or `-ApiPort 8001` if the default ports are in use. Logs are in `tmp/`. Run `powershell -NoProfile -File scripts/stop.ps1` to stop the recorded processes.

For manual startup, run the API, refresh worker and frontend in separate terminals after installing dependencies and copying the bundle. On macOS or Linux, use `python3` to create the virtual environment, activate it with `source .venv/bin/activate`, and use `npm` in place of `npm.cmd`.

```text
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
python -m ml.live.refresh --loop
npm run dev
```

See [.env.example](.env.example) for configuration. Set `API_BASE_URL` for the frontend when using a custom API address.

## Deployment and refresh

Vercel hosts the Next.js frontend. Render runs the FastAPI service and source-refresh worker from [render.yaml](render.yaml), with Supabase PostgreSQL storing race data and forecast snapshots. UptimeRobot checks the API health endpoint every five minutes. The separate local [Docker Compose stack](compose.yml) runs its own PostgreSQL database.

The worker checks sources about every five minutes. Open pages refresh their saved data every minute. Forecasts appear after the necessary session data is published and validated. See [automatic refresh](docs/automatic-refresh.md) and [deployment and recovery](docs/deployment-readiness.md).

## Development

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm.cmd run typecheck
npm.cmd run build
node --experimental-strip-types scripts/test-forecast-changes.mjs
```

Training runs separately from serving. See the [data contract](docs/data-contract.md) and the training notes for [practice models](docs/practice-models.md), [podium and top-10 models](docs/outcome-models.md), and [weather and race conditions](docs/weather-and-conditions.md).

## Data sources

[Jolpica-F1](https://github.com/jolpica/jolpica-f1) provides schedules and classifications. [FastF1](https://docs.fastf1.dev/) provides session timing, with [OpenF1](https://openf1.org/docs/) as a fallback. [Open-Meteo](https://open-meteo.com/en/docs/previous-runs-api) provides archived forecasts for the evaluated FP3 conditions model and weather context for race weekends. Data availability depends on when each source publishes. See the [artwork notes](docs/artwork.md) for the original hero image.

FASTLANE is an independent educational project unaffiliated with Formula 1, the FIA, Formula One Management or any team.
