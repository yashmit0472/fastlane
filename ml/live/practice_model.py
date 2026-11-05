"""Inference from an explicitly activated local practice bundle. Never fits models."""
import hashlib
import json
import pickle
from pathlib import Path
import pandas as pd
from ml.features.practice import FEATURE_VERSION,numeric,CATEGORICAL,features_for_practice,parse_time
from ml.training.practice import ACTIVE,ROOT,cat_input,baseline_scores
from ml.training.evaluate import race_distribution


def active_report(stage):
    if not ACTIVE.exists(): return None
    bundle=json.loads(ACTIVE.read_text(encoding='utf-8'))
    if bundle.get('feature_version')!=FEATURE_VERSION: raise ValueError('Incompatible activated practice bundle')
    info=bundle.get('stages',{}).get(stage)
    if not info: return None
    path=(ROOT/info['report']).resolve()
    if not path.is_relative_to(ROOT/'ml/artifacts'): raise ValueError('Practice report must be a local artifact')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=info['sha256']: raise ValueError('Practice report checksum mismatch')
    report=json.loads(path.read_text(encoding='utf-8'))
    if report.get('status')!='backtested' or report.get('feature_version')!=FEATURE_VERSION or report.get('stage')!=stage:
        raise ValueError('Practice report stage/version/status mismatch')
    if report.get('features')!=numeric(stage)+CATEGORICAL: raise ValueError('Practice report feature order mismatch')
    return path,report


def predict_scores(frame,path,report):
    name=report['selected_model']; stage=report['stage']
    if name in {'uniform_baseline','practice_pace_baseline'}: return baseline_scores(frame,stage,name)
    artifact=path.parent/('model.cbm' if name=='catboost' else name+'.pkl')
    if hashlib.sha256(artifact.read_bytes()).hexdigest()!=report['artifact_sha256'][artifact.name]: raise ValueError('Practice model checksum mismatch')
    if name=='catboost':
        from catboost import CatBoostClassifier
        model=CatBoostClassifier(); model.load_model(str(artifact))
        return model.predict_proba(cat_input(frame,stage))[:,1]
    if name not in {'logistic','history_logistic'}: raise ValueError('Unknown practice model')
    from ml.inference.linear import load_linear
    model=load_linear(artifact)
    return model.predict_proba(frame)[:,1]


def learned_forecast(race,raw,entries,completed,history,stage,cutoff):
    chosen=active_report(stage)
    if chosen is None: return None
    path,report=chosen
    if cutoff>=parse_time(race['scheduled_at']): raise ValueError('Race has started; cannot publish a retrospective practice forecast')
    if parse_time(report['trained_until'])>=cutoff or parse_time(report['created_at'])>cutoff:
        raise ValueError('Practice model was fitted or created after forecast cutoff')
    rows=features_for_practice(raw,history,entries,completed,stage,cutoff)
    frame=pd.DataFrame(rows)
    probabilities=race_distribution(predict_scores(frame,path,report),report['temperatures'][report['selected_model']])
    from ml.live.explain import winner_associations
    associations=winner_associations(frame,path,report)
    lookup={e['driver_id']:e for e in entries}
    drivers=[{**lookup[row['driver_id']],'grid':None,'probability':float(p),
        'factors':[f'{stage} and earlier practice only','Earlier driver, team and circuit history','Provisional field from latest completed Grand Prix']}
        for row,p in zip(rows,probabilities)]
    for d in drivers: d['model_associations']={'winner':associations[d['driver_id']]} if d['driver_id'] in associations else {}
    drivers.sort(key=lambda d:d['probability'],reverse=True)
    from ml.live.outcomes import attach_outcomes
    outcomes_version = attach_outcomes(drivers,frame,stage,cutoff,report['model_version'])
    allowed=['FP1','FP2','FP3'][:['FP1','FP2','FP3'].index(stage)+1]
    return {'race_id':race['race_id'],'model_version':report['model_version'],'cutoff':cutoff.isoformat(),'updated_at':cutoff.isoformat(),
        'race_start':race['scheduled_at'],'is_demo':False,'calibrated':True,'stage':stage,'status':'experimental; validation-temperature fitted',
        'method':f"{report['selected_model']} {stage} / earlier-history model",'field_status':'provisional latest-race field',
        'notice':report['notice']+(' Validation selected a history-only/uniform baseline; this snapshot does not use practice pace.' if not report['uses_practice'] else ''),
        'evidence':[{'source':s.get('source','FastF1'),'session':name,'available_at':s['observed_at']} for name,s in completed.items() if name in allowed],
        'drivers':drivers,'outcomes_model_version':outcomes_version}
