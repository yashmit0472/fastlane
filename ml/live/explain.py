"""Actual additive raw-score associations, never causal probability deltas."""
import pickle
import numpy as np


def family(name):
    name=name.split('__')[-1].replace('missingindicator_','')
    if name.startswith(('forecast_','rain_x_','wind_x_','temperature_x_')): return 'Forecast weather & weather interactions'
    if 'nonfinish' in name or 'status_samples' in name: return 'Prior nonfinish history & sample'
    if name.startswith(('driver_id_','constructor_id_','circuit_id_')) or name in {'driver_id','constructor_id','circuit_id'}: return 'Driver, team & circuit encoding'
    if 'long_run' in name: return 'Compound-matched long-run proxy'
    if name.startswith('team_'): return 'Recent team form'
    if name.startswith(('recent_','driver_')): return 'Recent driver form'
    if 'circuit' in name or name=='prior_starts': return 'Circuit history'
    if 'qualifying' in name: return 'Qualifying performance'
    if any(x in name for x in ['tyre','soft','iqr','log_laps','available']): return 'Tyres & practice sample'
    return 'Practice pace'


def pack(values,names,method):
    result=[]
    for row in values:
        groups={}
        for name,value in zip(names,row): groups[family(name)]=groups.get(family(name),0)+float(value)
        result.append({'method':method,'space':'raw binary log-odds before temperature and race constraints',
            'notice':'Associations describe this fitted model. They are not causal effects or percentage-point changes.',
            'signals':[{'label':k,'contribution':v} for k,v in sorted(groups.items(),key=lambda kv:abs(kv[1]),reverse=True)[:3]]})
    return result


def linear_terms(model,frame):
    transform=model.named_steps['features']; classifier=model.named_steps['model']
    x=transform.transform(frame)
    if hasattr(x,'toarray'): x=x.toarray()
    return pack(np.asarray(x)*classifier.coef_[0],transform.get_feature_names_out(),'Linear model terms (standardized / encoded features)')


def winner_associations(frame,path,report):
    name=report['selected_model']
    if name=='catboost':
        from catboost import CatBoostClassifier,Pool
        from ml.features.build import CATEGORICAL
        columns=report['features']; x=frame[columns].copy()
        for col in columns:
            x[col]=x[col].fillna('unknown').astype(str) if col in CATEGORICAL else x[col].fillna(-999)
        model=CatBoostClassifier(); model.load_model(str(path.parent/'model.cbm'))
        values=model.get_feature_importance(Pool(x,cat_features=CATEGORICAL),type='ShapValues')[:,:-1]
        packed=pack(values,columns,'CatBoost SHAP values')
    elif name in {'logistic','history_logistic'}:
        from ml.inference.linear import load_linear
        model=load_linear(path.parent/(name+'.pkl'))
        packed=linear_terms(model,frame)
    else: return {}
    return {did:value for did,value in zip(frame.driver_id,packed)}
