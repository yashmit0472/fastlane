"""Compact serving store. SQLite locally; the same models support PostgreSQL."""
import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import Column, String, Integer, Boolean, JSON, UniqueConstraint, Index, create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, validates

ROOT = Path(__file__).resolve().parents[2]
(ROOT / "data").mkdir(exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///" + (ROOT / "data/fastlane.db").as_posix())
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}, pool_pre_ping=True)
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def sqlite_concurrency(connection, record):
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def utc_timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("A timezone is required")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Race(Base):
    __tablename__ = "races"
    race_id = Column(String, primary_key=True)
    season = Column(Integer, nullable=False)
    round = Column(Integer, nullable=False)
    scheduled_at = Column(String, nullable=False)
    is_demo = Column(Boolean, nullable=False, default=False)
    payload = Column(JSON, nullable=False)

    @validates("scheduled_at")
    def normalize_start(self, key, value):
        return utc_timestamp(value)


class Snapshot(Base):
    __tablename__ = "snapshots"
    id = Column(Integer, primary_key=True)
    entity_id = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    version = Column(String, nullable=False)
    cutoff = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("entity_id", "kind", "version", "cutoff"),Index('snapshot_lookup','entity_id','kind','cutoff'))

    @validates("cutoff")
    def normalize_cutoff(self, key, value):
        return utc_timestamp(value)


class SystemState(Base):
    __tablename__ = "system_state"
    key = Column(String, primary_key=True)
    payload = Column(JSON, nullable=False)


def initialize():
    Base.metadata.create_all(engine)
    for index in Snapshot.__table__.indexes: index.create(engine,checkfirst=True)


def save_snapshot(db, entity_id, kind, version, cutoff, payload):
    """Idempotent, immutable: a repeated run cannot rewrite an old prediction."""
    cutoff = utc_timestamp(cutoff)
    found = db.query(Snapshot).filter_by(entity_id=entity_id, kind=kind, version=version, cutoff=cutoff).first()
    if found:
        if found.payload != payload:
            raise ValueError("Snapshot already exists with different data; use a new version or cutoff")
        return found
    value = Snapshot(entity_id=entity_id, kind=kind, version=version, cutoff=cutoff, payload=payload)
    db.add(value)
    db.flush()
    return value
