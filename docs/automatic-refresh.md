# Automatic real-data updates

Qualifying fix, 25 October 2026: qualifying now uses Jolpica → OpenF1 → FastF1 with a last-complete-result cache. A running local worker previously waited indefinitely for an empty Jolpica qualifying response even when OpenF1 had all phase results; the fallback was only wired to practice. The current US qualifying import was verified with 22 mapped drivers and published Q1/Q2/Q3 times. The worker published the Q prediction and cleared its pending status automatically.

The serving API excludes demo races and demo fact/forecast snapshots, including direct links. Existing fixture files remain solely for offline tests. Startup and Docker no longer seed demo data.

## Run locally

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -WebPort 3010
```

This starts the API, Next.js and a separate refresh worker. Keep the computer awake and connected to the internet. Existing processes must be stopped before restarting with this command; scripts/stop.ps1 stops the recorded process trees.

The worker checks its wall-clock deadline in short intervals so an overdue check resumes promptly after the computer wakes. To restart only the worker after training a new model, while leaving the website and API running:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/restart-worker.ps1
```

For a manually managed setup, run the worker separately:

```powershell
.\.venv\Scripts\python.exe -m ml.live.refresh --loop
```

Run one source refresh without the loop by omitting --loop. No model training occurs in these commands. Optional --model-report PATH pins a specific evaluated local report; otherwise the latest complete evaluated v1 artifact is pinned when the worker starts. Refresh interval defaults to 300 seconds; --interval must be at least 300.

## Data lifecycle

Practice-model update (19 October 2026): standard-weekend FP1/FP2/FP3 forecasts now use the separately trained, validation-selected artifacts registered in ml/artifacts/practice-active.json. The older uncalibrated baseline described below remains the fallback when no bundle is activated and for sprint formats outside the trained coverage. See [practice-models.md](practice-models.md) for metrics, limitations and reproduction commands. Qualifying remains a separate model.

All completed races in the refreshed season receive archived qualifying and published race classification. Completed-race pages display results directly, even without a saved forecast. Missing practice weekends are backfilled one per refresh by default, using cached successful sessions. For an initial season backfill, restart the worker with `scripts/restart-worker.ps1 -ArchiveLimit 20`; `--archive-limit` controls this batch size for manually managed workers. Sprint timing remains explicitly outside this importer. Archived data never creates retrospective predictions.

Jolpica supplies the real calendar, qualifying classification and race results. FastF1 loads completed published practice sessions, with telemetry/weather downloads disabled. No API key or paid real-time feed is configured. Sources can be delayed or unavailable; polling does not promise immediate publication.

The worker checks sources about every 5 minutes, with caching and rate-limit retries. Open, visible pages refresh their persisted API views every minute using router.refresh, and on browser reconnect/focus. Web requests do not call upstream timing APIs or train models.

FP1/FP2/FP3 snapshots use an **uncalibrated experimental practice pace/form baseline**: earlier five-race smoothed win rate multiplied by exp(-mean within-session best-lap gap / 1 second), then normalized across the provisional latest-race field. Missing eligible pace uses a neutral earlier-form prior; at least 70% of the field needs usable timing. This rule has not been backtested as a calibrated winner model. Practice is mixed fuel/tyre/setup work. Reserve drivers and roster changes limit the provisional field. It must be replaced by stage-specific learned models once those are independently trained and evaluated.

Post-qualifying snapshots use the user's evaluated qualifying/history artifact and validation-fitted probability temperature. Sprint-format forecasts are explicitly flagged outside the standard-weekend training coverage. FP2/FP3 stages are not invented on sprint weekends.

Practice session completion must be confirmed by the source's final session-status value. Downloaded inputs carry actual observation timestamps. Forecasts are never published at or after race start; delayed downloads cannot create a historical pre-race forecast. An FP1 snapshot excludes FP2, FP3, qualifying and target-race outcomes. Every saved stage remains immutable.

After a classification is published, the actual winner is joined to already-saved forecasts. The API exposes correct top pick, probability assigned to the winner, race log loss and one-winner Brier. If no pre-race prediction exists, it says so rather than making one retrospectively. Results can be revised; scoring can update without altering original predictions.

## API additions

- /api/system/status: refresh health, last attempt/success, pending errors and model version.
- /api/races/{id}/predictions: all real saved pre-race snapshots.
- /api/races/{id}/evaluation: published classification and scores for recorded snapshots.

Schedule/session/history pages show saved real facts or explicit waiting states. The latest evaluated model report is published as methodology metrics. API history filters preserve prediction cutoffs; weekend views can display real archived timing without pretending it was retrieved before the race.

## Deployment limits

This is local automatic updating while the worker is running. It is not a deployed 24/7 hosted scheduler. A future deployment needs a persistent database/artifact store and one scheduled worker on a host that stays available. No paid subscription or hosting purchase has been made. The Docker API image initializes an empty database; its refresh worker must be deployed separately with access to trained artifacts and serving storage.

Source documentation: https://github.com/theOehrly/Fast-F1 ; https://github.com/jolpica/jolpica-f1/blob/main/docs/rate_limits.md ; https://openf1.org/docs/

## Verification

35 backend/pipeline tests passed; TypeScript and production build passed. Tests include stage/future-data exclusion, timing identity, tie scoring, roster mismatch rejection, recovery after a wall-clock jump and archive merging without losing real practice or inventing missing qualifying times. Real source refresh succeeded against the 2026 calendar, qualifying classifications and race results. A completed 2026 Singapore FP1 import returned usable laps for all 22 drivers; qualifying phase counts and real classification are served as archived data. Eleven page checks and real API checks passed, including demo URL rejection, cutoff invariants, waiting states and CORS. Browser visual/interaction QA remains blocked by the browser plugin Windows permission error. PostgreSQL/Docker hosting is not exercised.

## Free practice fallback

FastF1 primary timing can fail when its source returns 401 or its mirror has no session archive. Completed practice now falls back to OpenF1 automatically. Session matching checks year, country, practice stage and scheduled UTC start, rejecting ambiguous/cancelled matches. The fallback waits until 30 minutes after session end to avoid OpenF1's paid live window. No API key is required.

The US 2026 FP1 and FP2 imports were verified against the live API: each contains all 22 drivers, with 123 and 120 filtered laps respectively. Best times use the published practice classification. Median, lap count, tyres and long-run proxies use conservatively filtered laps, excluding out/pit laps, deleted times, race-control flag periods, unknown/pit mini-sectors, inconsistent sectors and possible stint-ending in-laps. FastF1 accuracy flags are unavailable in OpenF1, so this source switch is explicitly labeled and is not claimed to have validated calibration.

Before race start, OpenF1 practice summaries are rechecked after five minutes; network calls are spaced to respect the free rate limit. Cached last-good timing remains visible during provider failures, with partial refresh status. Forecasts carry a signature of eligible practice inputs: identical inputs do not create new snapshots, while corrected inputs may append a new pre-race snapshot. Earlier snapshots remain unchanged. No new forecast is published after race start.

The site is a free post-session service, not an in-session streaming feed. Sources are checked every five minutes and visible pages refresh every minute, including on reconnect/focus. Race results currently use Jolpica; qualifying has the source fallback described below. The computer and refresh worker must remain running with internet access.

## Qualifying fallback and recovery

- Select the exact non-cancelled qualifying session by season, country and scheduled UTC time; Sprint Qualifying is excluded. OpenF1 calls wait until at least 30 minutes after the published end time.
- Join official phase arrays to canonical entrants using acronym and car number. Require complete expected identities, unique contiguous positions, plausible Q1/Q2/Q3 times and a published final phase. A complete Jolpica classification can confirm replacement drivers when the earlier roster is provisional.
- Reject wrong sessions, partial fields, duplicated positions, scalar qualifying durations and Q1-only responses. Never use race starting-grid positions as qualifying results.
- Cache only complete successful classifications. Empty/failed responses are retried. If every provider fails, keep the last complete data with a refresh warning. A failure fetching the annual Jolpica tables no longer prevents targeted session fallbacks from running against the cached schedule.
- Check source classifications again on later worker cycles. Changed timing/source/model inputs append a new pre-race revision; a retrieval-timestamp change alone does not create another forecast. Preserve fallback Q1/Q2/Q3 when later archive passes still have no Jolpica qualifying rows. Queue archives missing qualifying as well as those missing practice.
- Record the actual classification source and observation time in session rows and prediction evidence. No new prediction can be published after race start.

`scripts/start.ps1` now runs the Python worker under `scripts/worker-supervisor.ps1`. Unexpected child exits restart after 15 seconds. `scripts/stop.ps1` stops the owned supervisor and descendants. This is local supervision while the app/computer are running, not an OS boot task or cloud deployment. The page shows last completed check, last attempt and next scheduled check. An overdue worker becomes visibly stale after two expected intervals plus one minute instead of waiting 30 minutes.

Regression coverage includes delayed/empty primary responses, wrong/sprint/paid-window sessions, partial final results, driver mapping, time units, later corrections, idempotent polling, outage cache preservation, archive preservation and stale-worker detection. The full suite now contains 93 tests. Production/TypeScript checks and real API/page checks cover the refreshed data. A controlled termination of the owned worker child verifies the supervisor recovery path; see `tmp/worker-recovery-test.json` and worker logs from this verification.

The crash test also exposed a Windows Application Control block on a scikit-learn training DLL. Reinstalling the exact official version did not remove that block. Security policy and file permissions were left unchanged. Serving now reads the checksummed local linear models as parameter data and applies their median imputation, missing indicators, standard scaling, unknown-category one-hot encoding and logistic coefficients using NumPy, without importing/executing sklearn training code. Unsupported model layouts fail closed. All 1,300 original winner, 2,600 original outcome and 3,720 conditions benchmark probabilities reproduce within 1e-10; the trained weights, model versions and selection decisions are unchanged. Actual offline fitting still requires a working scikit-learn training environment. Training-only imports are lazy so they do not prevent live source ingestion from starting. A primary FastF1 import failure also falls through to OpenF1.


Final race results now retry Jolpica, complete OpenF1 classifications and published FastF1 results, preserving the last complete cache. Missing positions for retired drivers are never guessed. The worker also makes daily verified backups and records operational issue/recovery transitions. See [deployment verification and recovery](deployment-readiness.md).


## Started races awaiting classification — 2 November 2026

The default overview, session and circuit pages now use `/api/races/current`. A started race remains in focus while classification is pending, for up to 24 hours; once classification arrives the focus advances to the next future race. `/api/races/next` retains its strictly future contract. An unclassified race remains in the ingestion queue for seven days even before race results exist. Results-pending races are listed separately from future weekends and completed races.

For Mexico round 19, no forecast was recorded before the scheduled start. The latest saved Mexico update before restarting was from 29 October. Importing past timing does not create a prospective prediction or an accuracy score. The recovery attempt also found an inconsistent primary qualifying classification (duplicate P8), unavailable unauthenticated OpenF1 access and unavailable FastF1 timing. These remain source delays; the importer retries rather than inventing positions. Archive validation preserves previously verified phases when a later response is invalid. Missing phase strings are accepted as missing, not fabricated times.

The regression suite contains 101 tests after this fix. Local source checks only happen while the computer and refresh worker are running; a public frontend by itself does not provide an always-on ingestion worker.
