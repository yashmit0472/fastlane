"""Apply only a checksummed conditions candidate accepted on chronological validation."""
import json
import pickle
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from ml.features.conditions import FEATURE_VERSION,enrich,reliability
from ml.features.build import features_for_race
from ml.features.practice import features_for_practice
from ml.ingestion.condition_forecasts import ROOT,FOLDER,fetch,live
from ml.live.outcomes import checksum,ACTIVE as OUTCOMES_ACTIVE
from ml.training.conditions import ACTIVE,inputs,infer
from ml.live.explain import linear_terms,pack


def signature(): return checksum(ACTIVE) if ACTIVE.exists() else 'no-conditions-bundle'


def active(stage):
    if not ACTIVE.exists(): return None
    bundle=json.loads(ACTIVE.read_text())
    if bundle.get('schema')!=FEATURE_VERSION: raise ValueError('Conditions manifest schema mismatch')
    info=bundle['stages'].get(stage)
    if not info: return None
    path=(ROOT/info['report']).resolve()
    if not path.is_relative_to(ROOT/'ml/artifacts') or checksum(path)!=info['sha256']: raise ValueError('Conditions report checksum/path mismatch')
    report=json.loads(path.read_text())
    if report['schema']!=FEATURE_VERSION or report['stage']!=stage: raise ValueError('Conditions report schema mismatch')
    return path,report


def prepare(raw):
    if not ACTIVE.exists(): return None
    fetch(raw)
    return live(raw,datetime.now(timezone.utc))


def load_models(path,report):
    choice=report['selected_candidate']; candidate=report['candidates'][choice]; directory=path.parent/choice; models={}
    for target in ['winner','podium','top10']:
        name=target+('.cbm' if candidate['kind']=='catboost' else '.pkl'); file=directory/name
        if checksum(file)!=candidate['artifacts'][name]: raise ValueError('Conditions model checksum mismatch')
        if candidate['kind']=='catboost':
            from catboost import CatBoostClassifier
            model=CatBoostClassifier(); model.load_model(str(file))
        else:
            from ml.inference.linear import load_linear
            model=load_linear(file)
        models[target]=model
    return models,candidate


def apply(forecast,raw,history,entries,practice,stage,cutoff,weather):
    chosen=active(stage)
    context={'used_by_model':False,'forecast':weather,'reason':'No evaluated conditions model is activated.','available_at':cutoff.isoformat(),
        'notice':'Forecast rainfall is a deterministic hourly amount, not a rain probability. Prior nonfinish history includes accidents/exclusions; it is not a mechanical failure probability. Safety cars, incidents and future tyre strategies are not known inputs.'}
    forecast['conditions_context']=context
    if FOLDER.joinpath('status-map.json').exists():
        status_map=json.loads((FOLDER/'status-map.json').read_text()); by_id={e['driver_id']:e for e in entries}
        for d in forecast['drivers']:
            e=by_id.get(d['driver_id'])
            if e: d.setdefault('observations',{})['race_conditions']=reliability(raw,history,e['driver_id'],e['constructor_id'],cutoff,status_map)
    if not chosen: return False
    path,report=chosen; context['candidate_version']=report['model_version']
    if not report['enabled']: context['reason']='Weather candidate did not pass the validation improvement gate for this stage.'; return False
    if raw.get('Sprint') or raw.get('SprintResults'): context['reason']='Sprint format is outside evaluated conditions coverage.'; return False
    if not weather: context['reason']='A complete compatible JMA forecast was not available at cutoff.'; return False
    if report['base_winner_version']!=forecast['model_version'] or checksum(OUTCOMES_ACTIVE)!=report['base_outcomes_manifest_sha256']:
        context['reason']='Base model versions changed; conditions require revalidation.'; return False
    if datetime.fromisoformat(report['created_at'])>cutoff or datetime.fromisoformat(report['trained_until'])>=cutoff:
        context['reason']='Conditions artifact was not available at cutoff.'; return False
    rows=features_for_race(raw,history,cutoff) if stage=='Q' else features_for_practice(raw,history,entries,practice,stage,cutoff)
    frame=enrich(pd.DataFrame(rows),raw,history,weather,cutoff)
    if set(frame.driver_id)!={d['driver_id'] for d in forecast['drivers']}: raise ValueError('Conditions entrant mismatch')
    models,candidate=load_models(path,report); arrays=infer(frame,models,candidate['features'],candidate['kind'],candidate['temperature'])
    associations={}
    for target,model in models.items():
        if candidate['kind']=='catboost':
            from catboost import Pool
            values=model.get_feature_importance(Pool(inputs(frame,candidate['features']),cat_features=['driver_id','constructor_id','circuit_id']),type='ShapValues')[:,:-1]
            associations[target]=pack(values,candidate['features'],'CatBoost SHAP values')
        else: associations[target]=linear_terms(model,frame)
    lookup={d['driver_id']:d for d in forecast['drivers']}
    for i,did in enumerate(frame.driver_id):
        d=lookup[did]
        for target,field in [('winner','probability'),('podium','podium_probability'),('top10','top10_probability')]:
            d[field]=float(arrays[target][i]); d.setdefault('model_associations',{})[target]=associations[target][i]
        d['factors']+=['72h-lead race weather forecast','Earlier driver/team nonfinish and circuit history']
    forecast['drivers'].sort(key=lambda d:d['probability'],reverse=True)
    context.update(used_by_model=True,reason='Weather-aware candidate passed the stage validation gate.',base_model_version=forecast['model_version'])
    forecast['model_version']=report['model_version']; forecast['outcomes_model_version']=report['model_version']
    forecast['method']=candidate['kind']+' weather / reliability / stage-history model'
    forecast['notice']=(forecast.get('notice') or '')+' '+report['notice']
    forecast['input_quality']['weather_model_input']=True
    forecast['evidence'].append({'source':weather['source'],'session':'race-hour 72h-lead forecast','available_at':weather['available_at']})
    return True
