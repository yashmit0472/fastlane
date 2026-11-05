"""Train FP1/FP2/FP3 models with frozen chronological windows and stage-safe features."""
import argparse
import hashlib
import json
import pickle
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from ml.features.practice import FEATURE_VERSION,STAGE_ORDER,HISTORY_NUMERIC,CATEGORICAL,numeric
from ml.training.train import split
from ml.training.evaluate import evaluate,fit_temperature,reliability

ROOT=Path(__file__).resolve().parents[2]
ACTIVE=ROOT/'ml/artifacts/practice-active.json'


def validate_frame(frame,stage):
    expected=set(numeric(stage)+CATEGORICAL+['target','race_id','season','race_date','cutoff','stage','feature_version','availability_policy'])
    if set(frame.columns)!=expected: raise ValueError('Unexpected practice schema: '+str(set(frame.columns)^expected))
    if set(frame.feature_version)!={FEATURE_VERSION} or set(frame.stage)!={stage}: raise ValueError('Incompatible feature stage/version')
    if frame.duplicated(['race_id','driver_id']).any(): raise ValueError('Duplicate driver/race rows')
    if not frame.target.isin([0,1]).all() or not frame.groupby('race_id').target.sum().eq(1).all(): raise ValueError('Expected exactly one winner per full race')
    if not frame.groupby('race_id').race_date.nunique().eq(1).all(): raise ValueError('Race start must be constant within race')
    if not (pd.to_datetime(frame.cutoff,utc=True)<pd.to_datetime(frame.race_date,utc=True)).all(): raise ValueError('Feature cutoff crosses race start')
    for column in numeric(stage):
        if not np.isfinite(frame[column].dropna().to_numpy(dtype=float)).all(): raise ValueError('Non-finite practice input')


def baseline_scores(frame,stage,name):
    if name=='uniform_baseline': return np.ones(len(frame))
    if name!='practice_pace_baseline': raise ValueError('Unknown baseline')
    columns=[f'{s.lower()}_best_gap_pct' for s in STAGE_ORDER[:STAGE_ORDER.index(stage)+1]]
    mean=frame[columns].mean(axis=1).fillna(0).clip(lower=0,upper=10)
    return frame.recent_win_rate.to_numpy()*np.exp(-mean.to_numpy())


def logistic_model(columns):
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder,StandardScaler
    preprocessing=ColumnTransformer([
        ('numeric',Pipeline([('imputer',SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True)),('scale',StandardScaler())]),columns),
        ('categorical',OneHotEncoder(handle_unknown='ignore'),CATEGORICAL)])
    return Pipeline([('features',preprocessing),('model',LogisticRegression(max_iter=3000,C=1,random_state=42))])


def cat_input(frame,stage):
    x=frame[numeric(stage)+CATEGORICAL].copy()
    for column in numeric(stage): x[column]=x[column].fillna(-999)
    for column in CATEGORICAL: x[column]=x[column].fillna('unknown').astype(str)
    return x


def train_stage(path,stage,validation_season,test_season,without_catboost=False):
    frame=pd.read_csv(path); validate_frame(frame,stage)
    train,valid,test=split(frame,validation_season,test_season)
    if train.race_id.nunique()<20 or min(valid.race_id.nunique(),test.race_id.nunique())<6:
        raise ValueError('Insufficient chronological coverage: require 20 train, 6 validation and 6 test races')
    created=datetime.now(timezone.utc).isoformat(); data_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    version=f"practice-{stage.lower()}-v1-{data_hash[:8]}-"+created[:19].replace(':','').replace('-','')
    output=ROOT/'ml/artifacts'/version; output.mkdir(parents=True,exist_ok=False)
    candidates={name:(None,baseline_scores(valid,stage,name),baseline_scores(test,stage,name)) for name in ['uniform_baseline','practice_pace_baseline']}
    for name,columns in [('history_logistic',HISTORY_NUMERIC),('logistic',numeric(stage))]:
        model=logistic_model(columns); model.fit(train,train.target)
        candidates[name]=(model,model.predict_proba(valid)[:,1],model.predict_proba(test)[:,1])
        with (output/f'{name}.pkl').open('wb') as stream: pickle.dump(model,stream)
    if not without_catboost:
        from catboost import CatBoostClassifier
        model=CatBoostClassifier(iterations=700,depth=5,learning_rate=.035,loss_function='Logloss',random_seed=42,
            verbose=False,thread_count=2,allow_writing_files=False)
        model.fit(cat_input(train,stage),train.target,cat_features=CATEGORICAL,
            eval_set=(cat_input(valid,stage),valid.target),early_stopping_rounds=60)
        model.save_model(str(output/'model.cbm'))
        candidates['catboost']=(model,model.predict_proba(cat_input(valid,stage))[:,1],model.predict_proba(cat_input(test,stage))[:,1])
    temperatures={}; validation={}; metrics={}; bins={}
    for name,(_,valid_scores,test_scores) in candidates.items():
        temperature=fit_temperature(valid,valid_scores); temperatures[name]=temperature
        validation[name]=evaluate(valid,valid_scores,temperature)[0]
        metrics[name],predictions=evaluate(test,test_scores,temperature)
        bins[name]=reliability(predictions)
        (output/f'{name}-predictions.json').write_text(json.dumps(predictions,indent=2),encoding='utf-8')
    selected=min(validation,key=lambda name:validation[name]['log_loss'])
    def window(f): return f'{int(f.season.min())}–{int(f.season.max())} ({f.race_id.nunique()} races)'
    report={'status':'backtested','stage':stage,'feature_version':FEATURE_VERSION,'model_version':version,'created_at':created,
        'training_window':window(train),'validation_window':window(valid),'test_window':window(test),
        'trained_until':valid.race_date.max(),'trained_until_policy':'Includes validation used for early stopping, selection and temperature fitting.',
        'selected_model':selected,'selection_rule':'lowest validation race log loss across all five candidates; never test selection',
        'uses_practice':selected not in {'history_logistic','uniform_baseline'},'metrics':metrics,'validation_metrics':validation,
        'temperatures':temperatures,'reliability':bins,'features':numeric(stage)+CATEGORICAL,'dataset_sha256':data_hash,'seed':42,
        'minimum_field_coverage':.7,'historical_availability_audited':False,'sprint_supported':False,
        'top1_tie_policy':'fractional credit among equal-probability leaders; independent of result-row order',
        'notice':'Experimental practice-stage backtest. Historical publication cutoffs estimated; retrospective confirmed rosters. 2025 is a development benchmark previously inspected for qualifying. Long-run proxy is not fuel-adjusted.'}
    coverage=path.parent/'coverage.json'
    if coverage.exists():
        source=json.loads(coverage.read_text()); report['source_manifest_sha256']=source['source_manifest_sha256']; report['coverage']=source['stages'][stage]
    report['artifact_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.suffix in {'.cbm','.pkl'}}
    report_path=output/'report.json'; report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'stage':stage,'selected_model':selected,'metrics':metrics,'report':str(report_path)},indent=2),flush=True)
    return report_path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feature-dir',type=Path,default=ROOT/'data/processed/practice-2018-2025')
    parser.add_argument('--stages',nargs='+',choices=STAGE_ORDER,default=STAGE_ORDER)
    parser.add_argument('--validation-season',type=int,default=2024)
    parser.add_argument('--test-season',type=int,default=2025)
    parser.add_argument('--without-catboost',action='store_true')
    parser.add_argument('--activate',action='store_true')
    args=parser.parse_args(); paths={}
    if args.activate and set(args.stages)!=set(STAGE_ORDER): parser.error('Activation requires all three stages to succeed together')
    for stage in args.stages:
        path=train_stage(args.feature_dir/f'{stage.lower()}-features.csv',stage,args.validation_season,args.test_season,args.without_catboost)
        paths[stage]={'report':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    if args.activate:
        temporary=ACTIVE.with_suffix('.tmp'); temporary.write_text(json.dumps({'feature_version':FEATURE_VERSION,'stages':paths},indent=2),encoding='utf-8'); temporary.replace(ACTIVE)
        print('Activated all three evaluated practice-stage artifacts; the worker will pick them up on its next refresh.',flush=True)


if __name__=='__main__': main()
