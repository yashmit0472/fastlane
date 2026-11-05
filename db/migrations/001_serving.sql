-- PostgreSQL serving schema corresponding to apps/api/database.py.
-- Keep bulk laps/telemetry in cached files. JSON snapshots contain the stable API contract.
BEGIN;
CREATE TABLE IF NOT EXISTS races (
    race_id VARCHAR PRIMARY KEY,
    season INTEGER NOT NULL,
    round INTEGER NOT NULL,
    scheduled_at VARCHAR NOT NULL,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    payload JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    id SERIAL PRIMARY KEY,
    entity_id VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    version VARCHAR NOT NULL,
    cutoff VARCHAR NOT NULL,
    payload JSON NOT NULL,
    UNIQUE (entity_id, kind, version, cutoff)
);
CREATE INDEX IF NOT EXISTS snapshot_lookup ON snapshots(entity_id, kind, cutoff DESC);
COMMIT;
