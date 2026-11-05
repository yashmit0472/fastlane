"""Chronological weather/conditions experiment and explicit serving activation."""
import argparse
import json
import pickle
import shutil
from datetime import datetime,timezone
import numpy as np
from catboost import CatBoostClassifier
from ml.features.conditions import ROOT,FEATURE_VERSION,columns,build
from ml.features.build import CATEGORICAL
from ml.training.practice import logistic_model
from ml.training.train import split
from ml.training.evaluate import race_distribution,fit_temperature
from ml.training.outcomes import finishing_labels,project
from ml.live.outcomes import checksum,ACTIVE as OUTCOMES_ACTIVE
from ml.validation.backtest import model_arrays,TARGETS
from ml.validation.metrics import assess

ACTIVE=ROOT/'ml/artifacts/conditions-active.json'
RULE='Mean of three validation binary log losses improves by >0.001 over current serving and both matched no-weather ablations (logistic and CatBoost); no target worsens by more than 5% versus current serving.'


def inputs(frame,features):
    x=frame[features].copy()
    for col in features: x[col]=x[col].fillna('unknown').astype(str) if col in CATEGORICAL else x[col].fillna(-999).astype(float)
    return x


def infer(frame,models,features,kind,temperature):
    arrays={}; lower=np.zeros(len(frame))
    for target,k in TARGETS.items():
        model=models[target]; x=inputs(frame,features) if kind=='catboost' else frame[features]
        p=model.predict_proba(x)[:,1]
        if target=='winner':
            for _,group in frame.groupby('race_id'): lower[group.index]=race_distribution(p[group.index],temperature)
        else: lower=project(frame,p,lower,k)
        arrays[target]=lower.copy()
    return arrays


def measure(frame,arrays):
    return {t:assess(frame.race_id,(frame.finish_label<=k).astype(int),arrays[t],k) for t,k in TARGETS.items()}


def joint(scores): return float(np.mean([scores[t]['binary_log_loss'] for t in TARGETS]))


def passes(validation,selected):
    return bool(joint(validation[selected])+0.001<min(joint(validation[n]) for n in ['current_serving','without_weather','without_weather_catboost']) and all(validation[selected][t]['binary_log_loss']<=validation['current_serving'][t]['binary_log_loss']*1.05 for t in TARGETS))


def train(stage,history,output):
    frame,path=build(stage,history); frame=finishing_labels(frame,history); train,valid,test=split(frame,2024,2025)
    if train.race_id.nunique()<40 or min(valid.race_id.nunique(),test.race_id.nunique())<6: raise ValueError('Insufficient chronological weather coverage')
    base_v,version=model_arrays(valid,stage); base_t,_=model_arrays(test,stage)
    validation={'current_serving':measure(valid,base_v)}; benchmark={'current_serving':measure(test,base_t)}
    records={}; stage_dir=output/stage; stage_dir.mkdir()
    for name,kind,weather in [('without_weather','logistic',False),('without_weather_catboost','catboost',False),('weather_logistic','logistic',True),('weather_catboost','catboost',True)]:
        features=columns(stage,weather)+CATEGORICAL; directory=stage_dir/name; directory.mkdir(); models={}; hashes={}
        for target,k in TARGETS.items():
            y=(train.finish_label<=k).astype(int)
            if kind=='catboost':
                model=CatBoostClassifier(iterations=350,depth=4,learning_rate=.04,loss_function='Logloss',random_seed=42,thread_count=2,verbose=False,allow_writing_files=False)
                model.fit(inputs(train,features),y,cat_features=CATEGORICAL); file=directory/(target+'.cbm'); model.save_model(str(file))
            else:
                model=logistic_model([c for c in features if c not in CATEGORICAL]); model.fit(train[features],y); file=directory/(target+'.pkl')
                with file.open('wb') as stream: pickle.dump(model,stream)
            hashes[file.name]=checksum(file); models[target]=model
        raw=models['winner'].predict_proba(inputs(valid,features) if kind=='catboost' else valid[features])[:,1]
        temperature=fit_temperature(valid,raw)
        arrays_v=infer(valid,models,features,kind,temperature); arrays_t=infer(test,models,features,kind,temperature)
        validation[name]=measure(valid,arrays_v); benchmark[name]=measure(test,arrays_t)
        records[name]={'kind':kind,'features':features,'temperature':temperature,'artifacts':hashes}
        for t in TARGETS:
            rows=test[['race_id','driver_id','finish_label']].copy(); rows['probability']=arrays_t[t]; rows.to_csv(directory/(t+'-benchmark.csv'),index=False)
    selected=min(['weather_logistic','weather_catboost'],key=lambda n:joint(validation[n]))
    # A single preregistered validation rule; never select based on 2025.
    enabled=passes(validation,selected)
    report={'schema':FEATURE_VERSION,'stage':stage,'model_version':output.name+'-'+stage,'created_at':datetime.now(timezone.utc).isoformat(),
        'trained_until':valid.race_date.max(),'selected_candidate':selected,'enabled':enabled,'selection_rule':RULE,
        'features':records[selected]['features'],'candidates':records,'validation':validation,'benchmark':benchmark,
        'base_winner_version':version,'base_outcomes_manifest_sha256':checksum(OUTCOMES_ACTIVE),'dataset_path':path.relative_to(ROOT).as_posix(),'dataset_sha256':checksum(path),
        'splits':{k:int(f.race_id.nunique()) for k,f in [('train',train),('validation',valid),('benchmark',test)]},
        'train_seasons':sorted(train.season.unique().astype(int).tolist()),'race_ids':{k:sorted(f.race_id.unique().tolist()) for k,f in [('train',train),('validation',valid),('benchmark',test)]},
        'notice':'Experimental fixed 72h-lead JMA weather plus prior nonfinish/circuit conditions. Historical weather publication is estimated with 6h release allowance. 2025 is a previously inspected development benchmark. No new source-shift certification. Unsupported stages or missing weather retain existing predictions.'}
    file=stage_dir/'report.json'; file.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(stage,'enabled',enabled,{n:round(joint(s),5) for n,s in validation.items()},flush=True)
    return {'report':file.relative_to(ROOT).as_posix(),'sha256':checksum(file)},report


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--activate',action='store_true'); parser.add_argument('--complete-ablation',action='store_true'); args=parser.parse_args()
    history=json.loads((ROOT/'data/processed/kaggle-2018-2025/history.json').read_text())['races']
    output=ROOT/'ml/artifacts'/('conditions-v1-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'))
    if args.complete_ablation:
        original=json.loads(ACTIVE.read_text()); first=original['stages']['FP1']; root=(ROOT/first['report']).parent.parent
        if not root.resolve().is_relative_to(ROOT/'ml/artifacts'): raise ValueError('Invalid original artifact path')
        shutil.copytree(root,output)
    else: output.mkdir()
    bundle={'schema':FEATURE_VERSION,'stages':{}}; reports={}
    for stage in ['FP1','FP2','FP3','Q']:
        if args.complete_ablation: bundle['stages'][stage],reports[stage]=complete_ablation(stage,history,output)
        else: bundle['stages'][stage],reports[stage]=train(stage,history,output)
    (ROOT/'docs/conditions-model-report.json').write_text(json.dumps({'status':'backtested','stages':reports},indent=2),encoding='utf-8')
    if args.activate:
        temp=ACTIVE.with_suffix('.tmp'); temp.write_text(json.dumps(bundle,indent=2)); temp.replace(ACTIVE)
    print('Saved',output,flush=True)


def complete_ablation(stage,history,output):
    """Reuse frozen candidates/data in a new artifact directory; add only the missing matched ablation."""
    path=output/stage/'report.json'; report=json.loads(path.read_text()); source=ROOT/report['dataset_path']
    if checksum(source)!=report['dataset_sha256']: raise ValueError('Prepared dataset changed')
    frame=finishing_labels(__import__('pandas').read_csv(source),history); train,valid,test=split(frame,2024,2025)
    features=columns(stage,False)+CATEGORICAL; directory=path.parent/'without_weather_catboost'; directory.mkdir(); models={}; hashes={}
    for target,k in TARGETS.items():
        model=CatBoostClassifier(iterations=350,depth=4,learning_rate=.04,loss_function='Logloss',random_seed=42,thread_count=2,verbose=False,allow_writing_files=False)
        model.fit(inputs(train,features),(train.finish_label<=k).astype(int),cat_features=CATEGORICAL)
        file=directory/(target+'.cbm'); model.save_model(str(file)); hashes[file.name]=checksum(file); models[target]=model
    raw=models['winner'].predict_proba(inputs(valid,features))[:,1]; temperature=fit_temperature(valid,raw)
    report['validation']['without_weather_catboost']=measure(valid,infer(valid,models,features,'catboost',temperature))
    arrays=infer(test,models,features,'catboost',temperature); report['benchmark']['without_weather_catboost']=measure(test,arrays)
    report['candidates']['without_weather_catboost']={'kind':'catboost','features':features,'temperature':temperature,'artifacts':hashes}
    for target in TARGETS:
        rows=test[['race_id','driver_id','finish_label']].copy(); rows['probability']=arrays[target]; rows.to_csv(directory/(target+'-benchmark.csv'),index=False)
    report['enabled']=passes(report['validation'],report['selected_candidate']); report['selection_rule']=RULE
    report['model_version']=output.name+'-'+stage; report['created_at']=datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(stage,'matched gate:',report['enabled'],{n:round(joint(s),5) for n,s in report['validation'].items()},flush=True)
    return {'report':path.relative_to(ROOT).as_posix(),'sha256':checksum(path)},report


if __name__=='__main__': main()
