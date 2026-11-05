"""Daily local backup, with visible failure state; no external messages are sent."""
import os
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from apps.api.database import ROOT,SessionLocal,SystemState
from scripts.backup import backup


def run_due(force=False):
    now=datetime.now(timezone.utc)
    with SessionLocal() as db:
        state=db.get(SystemState,'maintenance'); old=state.payload if state else {}
        if not force and old.get('last_backup') and now-datetime.fromisoformat(old['last_backup'])<timedelta(hours=24): return old
        if not force and old.get('last_attempt') and now-datetime.fromisoformat(old['last_attempt'])<timedelta(minutes=15): return old
    result={**old,'last_attempt':now.isoformat()}
    try:
        folder=Path(os.getenv('BACKUP_DIR',str(ROOT/'data/backups')))/now.strftime('%Y%m%dT%H%M%S%f')
        manifest=backup(folder)
        result.update(status='ok',last_backup=manifest['created_at'],rows=manifest['rows'],notice='Backup integrity verified. Restore only into an empty database.')
    except Exception as exc: result.update(status='error',notice='Automatic backup failed: '+type(exc).__name__)
    with SessionLocal() as db:
        state=db.get(SystemState,'maintenance')
        if state: state.payload=result
        else: db.add(SystemState(key='maintenance',payload=result))
        db.commit()
        from ml.live.operations import inspect,record_alerts
        record_alerts(db,inspect(db))
    return result


if __name__=='__main__': print(json.dumps(run_due(force=True),indent=2))
