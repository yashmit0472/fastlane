"""Read-only inference reproduction plus a documentation snapshot; never publishes forecasts."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from ml.live.practice_model import active_report,predict_scores
from ml.training.practice import validate_frame,baseline_scores
from ml.training.train import split
from ml.training.evaluate import evaluate

ROOT=Path(__file__).resolve().parents[1]


def main():
    stages={}; frames={}; paths={}
    for stage in ['FP1','FP2','FP3']:
        path,report=active_report(stage)
        frame=pd.read_csv(ROOT/f'data/processed/practice-2018-2025/{stage.lower()}-features.csv')
        validate_frame(frame,stage); train,valid,test=split(frame,2024,2025)
        scores=predict_scores(test,path,report)
        metrics,predictions=evaluate(test,scores,report['temperatures'][report['selected_model']])
        saved=json.loads((path.parent/f"{report['selected_model']}-predictions.json").read_text())
        stored={(p['race_id'],p['driver_id']):p for p in saved}
        assert len(stored)==len(predictions)
        for p in predictions:
            original=stored[(p['race_id'],p['driver_id'])]
            assert p['target']==original['target'] and abs(p['probability']-original['probability'])<1e-10
        for key,value in metrics.items(): assert np.isclose(value,report['metrics'][report['selected_model']][key]),key
        for _,group in pd.DataFrame(predictions).groupby('race_id'):
            assert np.isclose(group.probability.sum(),1) and group.target.sum()==1
        stages[stage]=report; frames[stage]=test; paths[stage]=path
        print(f"PASS {stage}: saved model reproduces {len(predictions)} held-out driver probabilities across {test.race_id.nunique()} races")
    common=set.intersection(*(set(frame.race_id) for frame in frames.values()))
    matched={}
    for stage,frame in frames.items():
        cohort=frame[frame.race_id.isin(common)].reset_index(drop=True); report=stages[stage]
        matched[stage]={'selected':evaluate(cohort,predict_scores(cohort,paths[stage],report),report['temperatures'][report['selected_model']])[0],
            'pace_baseline':evaluate(cohort,baseline_scores(cohort,stage,'practice_pace_baseline'),report['temperatures']['practice_pace_baseline'])[0]}
    snapshot={'reports':stages,'verification':'Saved-model inference exactly reproduces held-out predictions; no historical serving forecasts created.',
        'source_audit':json.loads((ROOT/'data/processed/practice-2018-2025/source-audit.json').read_text()),
        'matched_development_test':{'races':len(common),'metrics':matched}}
    target=ROOT/'docs/practice-model-reports.json'; target.write_text(json.dumps(snapshot,indent=2),encoding='utf-8')
    print(json.dumps({'matched_races':len(common),'metrics':matched,'report':str(target)},indent=2))


if __name__=='__main__': main()
