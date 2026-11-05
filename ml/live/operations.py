"""Read-only operational checks and local alert transitions."""
import json
import os
from datetime import datetime,timezone,timedelta
from apps.api.database import ROOT,SystemState


def verify_models():
    """Check the activated model files without loading weights."""
    from ml.live.practice_model import active_report
    from ml.live.outcomes import ACTIVE,checksum
    from ml.live.conditions import active
    from ml.live.refresh import choose_model
    if not choose_model()[1]: raise ValueError('Qualifying artifact missing')
    manifest=json.loads(ACTIVE.read_text())
    for stage in ['FP1','FP2','FP3','Q']:
        if stage!='Q':
            practice=active_report(stage)
            if not practice: raise ValueError('Practice artifact missing')
            pp,pr=practice
            for file,expected in pr['artifact_sha256'].items():
                artifact=(pp.parent/file).resolve()
                if not artifact.is_relative_to(pp.parent) or checksum(artifact)!=expected: raise ValueError('Practice weights invalid')
        info=manifest['stages'][stage]; path=(ROOT/info['report']).resolve()
        if not path.is_relative_to(ROOT/'ml/artifacts') or checksum(path)!=info['sha256']: raise ValueError('Outcome report invalid')
        r=json.loads(path.read_text())
        for file,expected in r['artifacts'].items():
            artifact=(path.parent/file).resolve()
            if not artifact.is_relative_to(path.parent) or checksum(artifact)!=expected: raise ValueError('Outcome weights invalid')
        decision=active(stage)
        if not decision: raise ValueError('Conditions decision missing')
        cp,cr=decision; candidate=cr['candidates'][cr['selected_candidate']]
        for file,expected in candidate['artifacts'].items():
            artifact=(cp.parent/cr['selected_candidate']/file).resolve()
            if not artifact.is_relative_to(cp.parent) or checksum(artifact)!=expected: raise ValueError('Conditions weights invalid')
    if not any(p.exists() for p in [ROOT/'data/processed/kaggle-2018-2025/history.json',ROOT/'data/processed/history.json']): raise ValueError('Historical backbone missing')


def save_model_check(db, release):
    try:
        verify_models()
        verified = True
    except Exception:
        verified = False
    state = db.get(SystemState, 'model-integrity')
    payload = {'release': release, 'verified': verified}
    if state:
        state.payload = payload
    else:
        db.add(SystemState(key='model-integrity', payload=payload))
    db.commit()


def inspect(db,now=None,models=True):
    now=now or datetime.now(timezone.utc); state=db.get(SystemState,'refresh'); payload=state.payload if state else {}
    blockers=[]; warnings=[]
    if not payload.get('last_attempt'): blockers.append('Source worker has not started.')
    else:
        age=(now-datetime.fromisoformat(payload['last_attempt'].replace('Z','+00:00'))).total_seconds()
        if age>max(payload.get('interval_seconds',300)*2+60,180): blockers.append('Source worker checks are overdue.')
        elif payload.get('status')=='error': blockers.append('Source worker reported a failed refresh.')
    if models:
        try:
            release = os.getenv('FASTLANE_WORKER_MODEL_CHECK')
            if release:
                check = db.get(SystemState, 'model-integrity')
                if not check or check.payload.get('release') != release or not check.payload.get('verified'):
                    raise ValueError('The hosted worker has not verified the deployed bundle')
            else:
                verify_models()
        except Exception:
            blockers.append('A required model artifact is missing or has not passed its integrity check.')
    maintenance=db.get(SystemState,'maintenance'); m=maintenance.payload if maintenance else {}
    if m.get('status')=='error': warnings.append('The latest automatic backup failed.')
    if not m.get('last_backup'): warnings.append('The first automatic backup is pending.')
    elif now-datetime.fromisoformat(m['last_backup'])>timedelta(hours=48): warnings.append('Automatic backups are overdue.')
    return {'status':'unavailable' if blockers else 'warning' if warnings else 'ok','ready':not blockers,
        'checked_at':now.isoformat(),'blockers':blockers,'warnings':warnings,'last_source_check':payload.get('last_successful_refresh'),
        'next_source_check':payload.get('next_check_at'),'last_backup':m.get('last_backup'),'pending_sources':payload.get('pending',[]),
        'notice':'Free post-session updates depend on upstream publication and a running worker. Readiness does not guarantee provider uptime or model accuracy.'}


def record_alerts(db,status):
    issues=status['blockers']+status['warnings']; key=json.dumps(issues,sort_keys=True); existing=db.get(SystemState,'operations-alert')
    old=existing.payload if existing else {}
    if old.get('key')==key: return
    value={'key':key,'at':status['checked_at'],'issues':issues,'recovered':bool(old.get('issues') and not issues)}
    if existing: existing.payload=value
    else: db.add(SystemState(key='operations-alert',payload=value))
    db.commit()
    folder=ROOT/'data/operations'; folder.mkdir(parents=True,exist_ok=True)
    with (folder/'alerts.jsonl').open('a',encoding='utf-8') as stream: stream.write(json.dumps(value)+'\n')
