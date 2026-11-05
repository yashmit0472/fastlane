"""Local podium/top-ten inference with coherent race marginal probabilities."""
import hashlib
import json
import pickle
from datetime import datetime
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / 'ml/artifacts/outcomes-active.json'


def constrained_marginals(scores, lower, places):
    scores = np.asarray(scores, dtype=float)
    lower = np.asarray(lower, dtype=float)
    if scores.shape != lower.shape or not np.isfinite(scores).all() or not np.isfinite(lower).all():
        raise ValueError('Invalid outcome probability inputs')
    if len(scores) < places or (scores < 0).any() or (scores > 1).any() or (lower < 0).any() or (lower > 1).any() or lower.sum() > places + 1e-8:
        raise ValueError('Infeasible race marginals')
    if len(scores) == places: return np.ones(len(scores))
    odds = np.log(np.clip(scores, 1e-9, 1-1e-9) / np.clip(1-scores, 1e-9, 1))
    lo, hi = -80., 80.
    for _ in range(100):
        shift = (lo+hi)/2
        result = lower + (1-lower)/(1+np.exp(-np.clip(odds+shift,-80,80)))
        if result.sum() < places: lo = shift
        else: hi = shift
    return result


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attach_outcomes(drivers, frame, stage, cutoff, winner_model_version=None, explain=True):
    """Leave old or unsupported forecasts intact; never fabricate missing targets."""
    if not ACTIVE.exists(): return None
    bundle = json.loads(ACTIVE.read_text())
    info = bundle['stages'].get(stage)
    if not info: return None
    path = (ROOT/info['report']).resolve()
    if not path.is_relative_to(ROOT/'ml/artifacts') or checksum(path) != info['sha256']:
        raise ValueError('Outcome report checksum/path mismatch')
    report = json.loads(path.read_text())
    if report['stage'] != stage or report['schema'] != 'race-outcomes-v1': raise ValueError('Outcome schema mismatch')
    if winner_model_version is not None and report['winner_model_version'] != winner_model_version: return None
    if datetime.fromisoformat(report['created_at'].replace('Z','+00:00')) > cutoff or datetime.fromisoformat(report['trained_until'].replace('Z','+00:00')) >= cutoff:
        return None
    lookup = {d['driver_id']: d for d in drivers}
    if set(frame.driver_id) != set(lookup): raise ValueError('Outcome field mismatch')
    lower = np.array([lookup[d]['probability'] for d in frame.driver_id])
    for target, places in [('podium',3),('top10',10)]:
        selected = report['targets'][target]['selected_model']
        if selected == 'uniform': scores = np.full(len(frame), places/len(frame))
        else:
            model_path = path.parent / f'{target}.pkl'
            if checksum(model_path) != report['artifacts'][model_path.name]: raise ValueError('Outcome model checksum mismatch')
            from ml.inference.linear import load_linear
            model=load_linear(model_path)
            scores = model.predict_proba(frame[report['features']])[:,1]
            if explain:
                from ml.live.explain import linear_terms
                for did,association in zip(frame.driver_id,linear_terms(model,frame)):
                    lookup[did].setdefault('model_associations',{})[target]=association
        lower = constrained_marginals(scores,lower,places)
        for driver, p in zip(frame.driver_id,lower): lookup[driver][target+'_probability'] = float(p)
    return report['model_version']
