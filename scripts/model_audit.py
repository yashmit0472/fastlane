"""Check active model decisions and exact saved benchmark reproduction. No fitting or promotion."""
import json
import subprocess
import sys
from datetime import datetime,timezone
from ml.features.practice import parse_time
from ml.live.conditions import active
from ml.training.conditions import passes
from ml.live.refresh import ROOT


def main():
    gates={}
    for stage in ['FP1','FP2','FP3','Q']:
        _,r=active(stage)
        if r['enabled']!=passes(r['validation'],r['selected_candidate']): raise ValueError('Conditions activation differs from validation rule')
        windows=r['race_ids']; a=set(windows['train']); b=set(windows['validation']); c=set(windows['benchmark'])
        if a&b or a&c or b&c: raise ValueError('Chronological groups overlap')
        if parse_time(r['trained_until'])>=datetime.now(timezone.utc): raise ValueError('Model training range crosses current time')
        gates[stage]={'weather_enabled':r['enabled'],'model_version':r['model_version'],'splits':r['splits']}
    checks=[]
    for module in ['scripts.verify_practice_models','scripts.verify_outcome_models','scripts.verify_condition_models']:
        completed=subprocess.run([sys.executable,'-m',module],cwd=ROOT,capture_output=True,text=True)
        print(completed.stdout,end='')
        if completed.returncode: print(completed.stderr,file=sys.stderr); raise SystemExit(completed.returncode)
        checks.append(module)
    report={'status':'passed','created_at':datetime.now(timezone.utc).isoformat(),'checks':checks,'conditions':gates,
        'notice':'Artifact/inference and selection-rule audit. No weights were changed. One scored prospective race cannot establish calibration or future accuracy.'}
    (ROOT/'docs/model-readiness-report.json').write_text(json.dumps(report,indent=2))
    print('Active model integrity and inference audit passed.')


if __name__=='__main__': main()
