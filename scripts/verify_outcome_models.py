"""Reproduce offline saved benchmark marginals through the live inference code. No DB writes."""
import json
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from ml.live.outcomes import ROOT,ACTIVE,attach_outcomes
from ml.training.outcomes import winner_probabilities


def main():
    bundle=json.loads(ACTIVE.read_text()); checked=0
    for stage,info in bundle['stages'].items():
        report_path=ROOT/info['report']; report=json.loads(report_path.read_text())
        source=ROOT/report['dataset_path']
        frame=pd.read_csv(source); frame=frame[frame.season>=2025].reset_index(drop=True)
        probabilities,version=winner_probabilities(frame,stage)
        if stage=='Q':
            from ml.live.refresh import choose_model
            winner_path,winner_report=choose_model()
        else:
            from ml.live.practice_model import active_report
            winner_path,winner_report=active_report(stage)
        saved=json.loads((winner_path.parent/(winner_report['selected_model']+'-predictions.json')).read_text())
        expected_winner={(r['race_id'],r['driver_id']):r['probability'] for r in saved}
        assert np.allclose(probabilities,[expected_winner[(r.race_id,r.driver_id)] for r in frame.itertuples()],atol=1e-10,rtol=0)
        expected={t:pd.read_csv(report_path.parent/f'{t}-benchmark.csv').set_index(['race_id','driver_id']) for t in ['podium','top10']}
        for rid,race in frame.groupby('race_id'):
            drivers=[{'driver_id':r.driver_id,'probability':float(probabilities[i])} for i,r in race.iterrows()]
            attach_outcomes(drivers,race,stage,datetime.now(timezone.utc),version)
            for d in drivers:
                for target in expected:
                    np.testing.assert_allclose(d[target+'_probability'],expected[target].loc[(rid,d['driver_id']),'probability'],rtol=0,atol=1e-12)
                    checked+=1
        print(stage,'verified',race.shape[0],'drivers in last race;',frame.race_id.nunique(),'races',flush=True)
    print('Reproduced',checked,'outcome probabilities; no historical forecasts published.')


if __name__=='__main__': main()
