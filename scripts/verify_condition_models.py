"""Reproduce saved condition probabilities; never publish retrospective forecasts."""
import json
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from ml.features.conditions import ROOT
from ml.live.conditions import active,load_models
from ml.training.conditions import infer
from ml.training.outcomes import finishing_labels


def main():
    history=json.loads((ROOT/'data/processed/kaggle-2018-2025/history.json').read_text())['races']; count=0
    for stage in ['FP1','FP2','FP3','Q']:
        path,report=active(stage); models,candidate=load_models(path,report)
        frame=finishing_labels(pd.read_csv(ROOT/report['dataset_path']),history)
        frame=frame[frame.season>=2025].reset_index(drop=True)
        arrays=infer(frame,models,candidate['features'],candidate['kind'],candidate['temperature'])
        for target in arrays:
            expected=pd.read_csv(path.parent/report['selected_candidate']/(target+'-benchmark.csv'))
            assert list(zip(frame.race_id,frame.driver_id))==list(zip(expected.race_id,expected.driver_id))
            assert np.allclose(arrays[target],expected.probability,atol=1e-10,rtol=0)
            count+=len(frame)
        for rid,group in frame.groupby('race_id'):
            ids=group.index
            assert np.all(arrays['winner'][ids]<=arrays['podium'][ids]+1e-9)
            assert np.all(arrays['podium'][ids]<=arrays['top10'][ids]+1e-9)
            for target,k in [('winner',1),('podium',3),('top10',10)]: assert abs(arrays[target][ids].sum()-k)<1e-8
        # Confirm weather inputs actually can alter the fitted candidate's scores.
        changed=frame.copy(); changed['forecast_wind_kmh']+=30; changed['wind_x_recent_finish']+=changed.recent_finish
        modified=infer(changed,models,candidate['features'],candidate['kind'],candidate['temperature'])
        assert any(np.max(abs(arrays[t]-modified[t]))>1e-8 for t in arrays)
        print(stage,'enabled',report['enabled'],'rows',len(frame),flush=True)
    print('Reproduced',count,'condition probabilities; checked constraints and weather sensitivity. No serving snapshots written.')


if __name__=='__main__': main()
