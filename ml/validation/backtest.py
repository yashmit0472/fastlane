"""Frozen serving models vs training-only form/grid baselines. Never publishes forecasts."""
import json
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from ml.live.outcomes import ROOT,ACTIVE,attach_outcomes,checksum
from ml.training.outcomes import finishing_labels,winner_probabilities,project
from ml.training.evaluate import fit_temperature,race_distribution
from ml.training.train import split
from .metrics import assess

TARGETS={'winner':1,'podium':3,'top10':10}


def model_arrays(frame,stage):
    frame=frame.reset_index(drop=True)
    winner,version=winner_probabilities(frame,stage)
    arrays={'winner':winner,'podium':np.empty(len(frame)),'top10':np.empty(len(frame))}
    for _,race in frame.groupby('race_id'):
        drivers=[{'driver_id':r.driver_id,'probability':float(winner[i])} for i,r in race.iterrows()]
        if not attach_outcomes(drivers,race,stage,datetime.now(timezone.utc),version,explain=False): raise ValueError('Active outcome models unavailable for current winner version')
        for d,i in zip(drivers,race.index):
            for target in ['podium','top10']: arrays[target][i]=d[target+'_probability']
    return arrays,version


def baseline_arrays(train,valid,test,columns):
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    output={}; lower_valid=np.zeros(len(valid)); lower_test=np.zeros(len(test))
    for target,places in TARGETS.items():
        model=make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler(),LogisticRegression(C=1,max_iter=2000,random_state=42))
        model.fit(train[columns],(train.finish_label<=places).astype(int))
        v=model.predict_proba(valid[columns])[:,1]; t=model.predict_proba(test[columns])[:,1]
        if target=='winner':
            temperature=fit_temperature(valid,v)
            for f,s in [(valid,v),(test,t)]:
                for _,group in f.groupby('race_id'): s[group.index]=race_distribution(s[group.index],temperature)
            lower_valid=v; lower_test=t
        else:
            lower_valid=project(valid,v,lower_valid,places); lower_test=project(test,t,lower_test,places)
        output[target]=lower_test.copy()
    return output


def main():
    history=json.loads((ROOT/'data/processed/kaggle-2018-2025/history.json').read_text())['races']
    stages={}
    for stage in ['FP1','FP2','FP3','Q']:
        path=ROOT/('data/processed/qualifying-v2/features.csv' if stage=='Q' else f'data/processed/practice-2018-2025/{stage.lower()}-features.csv')
        frame=finishing_labels(pd.read_csv(path),history); train,valid,test=split(frame,2024,2025)
        current,version=model_arrays(test,stage)
        candidates={'serving_model':current,'recent_form':baseline_arrays(train,valid,test,['recent_finish','recent_win_rate','team_recent_finish'])}
        if stage=='Q': candidates['qualifying_only']=baseline_arrays(train,valid,test,['qualifying_position'])
        candidates['uniform']={name:np.array([k/int((test.race_id==rid).sum()) for rid in test.race_id]) for name,k in TARGETS.items()}
        results={name:{target:assess(test.race_id,(test.finish_label<=k).astype(int),arrays[target],k) for target,k in TARGETS.items()} for name,arrays in candidates.items()}
        stages[stage]={'models':results,'winner_model_version':version,'dataset_sha256':checksum(path),'race_ids':sorted(test.race_id.unique().tolist()),
            'train_races':int(train.race_id.nunique()),'validation_races':int(valid.race_id.nunique()),'test_races':int(test.race_id.nunique())}
        print(stage,{t:round(results['serving_model'][t]['brier'],4) for t in TARGETS},flush=True)
    report={'schema':'validation-v1','created_at':datetime.now(timezone.utc).isoformat(),'stages':stages,
        'outcomes_manifest_sha256':checksum(ACTIVE),'train_window':'2018–2023','validation_window':'2024','benchmark_window':'2025',
        'notice':'Previously inspected development benchmark, not an untouched final test. Baseline preprocessing fits training only; winner normalization fits validation only. Every comparison within a stage uses identical races. Different stages have different coverage. Reliability bins are descriptive and may be sparse.',
        'metric_definition':'Binary log loss and Brier are averaged per driver within each race, then across races. Top-k recall uses fractional credit for cutoff ties. ECE uses race-balanced bins. 95% intervals bootstrap whole races (300 resamples, seed 42). No causal explanations or guaranteed calibration.'}
    target=ROOT/'docs/validation-report.json'; target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Saved',target,flush=True)


if __name__=='__main__': main()
