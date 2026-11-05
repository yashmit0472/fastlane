"""Check optional metadata integration without changing or retraining active models."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from ml.features.practice import numeric,CATEGORICAL

ROOT=Path(__file__).resolve().parents[1]


def main():
    original=ROOT/'data/processed/practice-2018-2025'
    audit=ROOT/'data/processed/practice-session-metadata-audit'
    coverage=json.loads((audit/'coverage.json').read_text())
    conflicts=[r for r in coverage['coverage'] if r.get('metadata_warning')]
    checked=[r for r in coverage['coverage'] if r.get('metadata_session_key')]
    for stage in ['FP1','FP2','FP3']:
        before=pd.read_csv(original/f'{stage.lower()}-features.csv').sort_values(['race_id','driver_id']).reset_index(drop=True)
        after=pd.read_csv(audit/f'{stage.lower()}-features.csv').sort_values(['race_id','driver_id']).reset_index(drop=True)
        assert len(before)==len(after),f'{stage}: optional metadata removed eligible driver rows'
        assert before[['race_id']+CATEGORICAL+['target']].equals(after[['race_id']+CATEGORICAL+['target']])
        assert np.allclose(before[numeric(stage)].to_numpy(float),after[numeric(stage)].to_numpy(float),equal_nan=True)
        print(f'PASS {stage}: {len(after)} existing driver rows and model input values preserved')
    path=ROOT/'docs/downloaded-datasets-audit.json'; report=json.loads(path.read_text())
    report['session_metadata_validation']={'checked_eligible_practice_sessions':len(checked),
        'conflicting_session_times':conflicts,'model_inputs_changed':False,
        'notice':'Conflicting optional external timing is recorded and ignored. Existing raw lap data is retained. Source publication times remain unaudited.'}
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'checked_eligible_sessions':len(checked),'timing_conflicts':len(conflicts),'models_retrained':False},indent=2))


if __name__=='__main__': main()
