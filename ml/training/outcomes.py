"""Train real finishing-position targets. Never publish retrospective forecasts."""
import argparse
import json
import pickle
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from ml.live.outcomes import ROOT, ACTIVE, checksum, constrained_marginals
from ml.features.build import NUMERIC, CATEGORICAL
from ml.features.practice import numeric
from ml.training.practice import logistic_model, validate_frame
from ml.training.train import split
from ml.training.evaluate import race_distribution


def finishing_labels(frame, races):
    labels = {}
    for race in races:
        rid = f"{race['season']}-{int(race['round']):02d}"
        results = race.get('Results',[])
        positions = [int(d['position']) for d in results]
        if len(set(positions)) != len(positions): raise ValueError('Duplicate classified positions')
        for d in results: labels[(rid,d['Driver']['driverId'])] = int(d['position'])
    positions = [labels[(r.race_id,r.driver_id)] for r in frame.itertuples()]
    out = frame.copy(); out['finish_label'] = positions
    for _, race in out.groupby('race_id'):
        for places in [1,3,10]:
            if (race.finish_label <= places).sum() != places: raise ValueError('Incomplete classified field')
        if not np.array_equal((race.finish_label==1).astype(int),race.target): raise ValueError('Winner label mismatch')
    return out


def winner_probabilities(frame, stage):
    if stage != 'Q':
        from ml.live.practice_model import active_report, predict_scores
        path, report = active_report(stage)
        scores = predict_scores(frame,path,report)
    else:
        from ml.live.refresh import choose_model
        path, report = choose_model()
        name = report['selected_model']
        if name == 'catboost':
            from catboost import CatBoostClassifier
            model=CatBoostClassifier(); model.load_model(str(path.parent/'model.cbm'))
            x=frame[NUMERIC+CATEGORICAL].copy()
            x[NUMERIC]=x[NUMERIC].fillna(-999)
            for col in CATEGORICAL: x[col]=x[col].fillna('unknown').astype(str)
            scores=model.predict_proba(x)[:,1]
        elif name == 'logistic':
            from ml.inference.linear import load_linear
            model=load_linear(path.parent/'logistic.pkl')
            scores=model.predict_proba(frame[NUMERIC+CATEGORICAL])[:,1]
        else: scores=frame.qualifying_position.map(lambda p:report['grid_rates'].get(str(p),.05)).to_numpy()
    result=np.empty(len(frame))
    for _,group in frame.groupby('race_id'):
        result[group.index]=race_distribution(np.asarray(scores)[group.index],report['temperatures'][report['selected_model']])
    return result, report['model_version']


def project(frame, scores, lower, places):
    result=np.empty(len(frame))
    for _,group in frame.groupby('race_id'):
        idx=group.index; result[idx]=constrained_marginals(scores[idx],lower[idx],places)
    return result


def metrics(frame, probability, places):
    p=np.clip(probability,1e-10,1-1e-10); y=(frame.finish_label<=places).to_numpy(dtype=int)
    rows=pd.DataFrame({'race_id':frame.race_id,'ll':-y*np.log(p)-(1-y)*np.log(1-p),'brier':(p-y)**2})
    return {'binary_log_loss':float(rows.groupby('race_id').ll.mean().mean()),
            'brier':float(rows.groupby('race_id').brier.mean().mean()),'races':int(frame.race_id.nunique())}


def train_stage(stage, races, output):
    source=ROOT/('data/processed/qualifying-v2/features.csv' if stage=='Q' else f'data/processed/practice-2018-2025/{stage.lower()}-features.csv')
    frame=pd.read_csv(source)
    if stage!='Q': validate_frame(frame,stage)
    if frame.duplicated(['race_id','driver_id']).any(): raise ValueError('Duplicate driver/race')
    frame=finishing_labels(frame,races)
    train,valid,test=split(frame,2024,2025)
    columns=NUMERIC if stage=='Q' else numeric(stage)
    valid_lower,winner_version=winner_probabilities(valid,stage); test_lower,_=winner_probabilities(test,stage)
    directory=output/stage; directory.mkdir()
    report={'schema':'race-outcomes-v1','stage':stage,'model_version':output.name+'-'+stage,'created_at':datetime.now(timezone.utc).isoformat(),
        'trained_until':valid.race_date.max(),'features':columns+CATEGORICAL,'winner_model_version':winner_version,
        'dataset_sha256':checksum(source),'dataset_path':source.relative_to(ROOT).as_posix(),'targets':{},'artifacts':{},'splits':{'train_races':train.race_id.nunique(),'validation_races':valid.race_id.nunique(),'test_races':test.race_id.nunique()},
        'notice':'Experimental. Train 2018–2023, validation 2024, previously inspected development benchmark 2025. Labels are classified positions. Standard weekends only. Marginals constrained to nest and sum to 3 / 10; not a joint finishing-order distribution.'}
    for target,places in [('podium',3),('top10',10)]:
        model=logistic_model(columns); model.fit(train[columns+CATEGORICAL],(train.finish_label<=places).astype(int))
        valid_scores=model.predict_proba(valid[columns+CATEGORICAL])[:,1]; test_scores=model.predict_proba(test[columns+CATEGORICAL])[:,1]
        candidates={
            'logistic':(project(valid,valid_scores,valid_lower,places),project(test,test_scores,test_lower,places)),
            'uniform':(project(valid,np.full(len(valid),.5),valid_lower,places),project(test,np.full(len(test),.5),test_lower,places))}
        validation={k:metrics(valid,v[0],places) for k,v in candidates.items()}
        selected=min(validation,key=lambda k:validation[k]['binary_log_loss'])
        valid_lower,test_lower=candidates[selected]
        model_path=directory/f'{target}.pkl'
        with model_path.open('wb') as stream: pickle.dump(model,stream)
        report['artifacts'][model_path.name]=checksum(model_path)
        report['targets'][target]={'selected_model':selected,'validation':validation,'test':{k:metrics(test,v[1],places) for k,v in candidates.items()}}
        rows=test[['race_id','driver_id','finish_label']].copy(); rows['probability']=test_lower
        rows.to_csv(directory/f'{target}-benchmark.csv',index=False)
    path=directory/'report.json'; path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(stage,json.dumps(report['targets']),flush=True)
    return {'report':path.relative_to(ROOT).as_posix(),'sha256':checksum(path)},report


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--activate',action='store_true'); args=parser.parse_args()
    races=json.loads((ROOT/'data/processed/kaggle-2018-2025/history.json').read_text())['races']
    output=ROOT/'ml/artifacts'/('outcomes-v1-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')); output.mkdir()
    bundle={'schema':'race-outcomes-v1','stages':{}}; reports={}
    for stage in ['FP1','FP2','FP3','Q']:
        bundle['stages'][stage],reports[stage]=train_stage(stage,races,output)
    (ROOT/'docs/outcome-model-reports.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    if args.activate:
        temporary=ACTIVE.with_suffix('.tmp'); temporary.write_text(json.dumps(bundle,indent=2)); temporary.replace(ACTIVE)
    print('Saved',output,'activated:',args.activate,flush=True)


if __name__=='__main__': main()
