"""Probe a clean training runtime on an isolated synthetic example; never publish models."""
import json
import platform
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from catboost import CatBoostClassifier
from ml.training.practice import logistic_model

def main():
    f=pd.DataFrame({'recent_finish':list(range(1,21))*3,'driver_id':['a','b']*30,'constructor_id':['team']*60,'circuit_id':['test']*60})
    y=(f.recent_finish<=3).astype(int)
    model=logistic_model(['recent_finish']); model.fit(f,y); p=model.predict_proba(f)[:,1]
    cat=CatBoostClassifier(iterations=5,depth=2,verbose=False,allow_writing_files=False,thread_count=2); cat.fit(f[['recent_finish']],y)
    assert np.isfinite(p).all() and len(cat.predict_proba(f[['recent_finish']]))==len(f)
    print(json.dumps({'status':'passed','python':platform.python_version(),'notice':'Synthetic training probe only. No serving artifacts or historical forecasts were written.'}))

if __name__=='__main__': main()
