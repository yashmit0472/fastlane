# FASTLANE data contract

Serving is deliberately small: a race catalogue plus immutable JSON snapshots. SQLite works without another local service. PostgreSQL uses the same SQLAlchemy models and a versioned bootstrap migration. Bulk API responses, session caches, features and model artifacts are ignored by Git.

`GET /api/races/next` resolves the earliest future, non-demo schedule record. Without one it explicitly returns the historical demo with `is_demo: true` and a notice. Unknown race/driver/circuit IDs and absent saved snapshots return 404. Database failures return 503. Forecast responses are validated with Pydantic.

Snapshot kinds are `prediction`, `weekend`, `circuit`, `form`, and `metrics`. The unique key is `(entity_id, kind, version, cutoff)`. Writing different data under an existing key fails. UTC timestamps must be timezone-aware. Predictions include every entered driver; finite probabilities in [0,1] total 1. The frontend uses largest-remainder rounding so the displayed percentages total 100.0%.

Historical training records use qualifying position, not the later penalty-adjusted race grid, as a feature. Circuit historical conversion uses actual grid position in earlier races. Labels are joined separately through `include_target=True`. Race outcomes do not enter prediction features. Sprint weekends are excluded until a separate timing policy is audited.

Historical qualifying cutoffs are currently estimated at race start minus 18 hours. This is disclosed in the feature rows and report; no production publication is implied. Source fetch time proves retrieval, not historical availability. No weather or long-run feature is silently invented.

## Audited prediction input

`python -m ml.training.predict --source SOURCE.json --report ml/artifacts/VERSION/report.json` requires a trusted locally generated model artifact and an audited source file:

```json
{
  "availability_audited": true,
  "cutoff": "2027-03-13T18:00:00Z",
  "evidence": [{"source": "qualifying-results", "available_at": "2027-03-13T17:00:00Z"}],
  "race": {
    "race_id": "2027-01", "season": 2027, "round": 1,
    "name": "Example Grand Prix", "circuit_id": "example", "circuit": "Example Circuit",
    "country": "Example", "scheduled_at": "2027-03-14T12:00:00Z",
    "timezone": "UTC", "status": "scheduled", "is_demo": false,
    "source": "verified schedule", "source_updated_at": "2027-03-13T17:00:00Z"
  },
  "qualifying_race": {
    "season": "2027", "round": "1", "date": "2027-03-14", "time": "12:00:00Z",
    "Circuit": {"circuitId": "example"},
    "QualifyingResults": []
  },
  "entries": []
}
```

Populate every entered driver in `entries` with `driver_id`, `name`, `abbreviation`, `number`, `team`, `color`, and the verified `grid` (or null). Qualifying rows follow the Jolpica driver/constructor/position/Q1/Q2/Q3 format. The empty example deliberately fails publication. Record evidence for each upstream input, audit identifiers, and verify that no post-race fields are present. Automated checks enforce timestamps, model training range, full entry coverage, and probability totals; the human provenance audit is still necessary.

## Optional timing ingestion

FastF1 summaries retain missing values and quality labels. At least five clean laps are required for representative median pace. This is not a fuel/tyre-adjusted long run. Qualifying phase results are kept separate. Historical session files are not automatically published as a live weekend snapshot because retrieval does not establish historical publication time.
