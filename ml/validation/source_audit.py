"""Paired offline source audit. Historical facts only; no retrospective publication."""
import argparse
import hashlib
import json
from datetime import datetime,timezone,timedelta
import numpy as np
import pandas as pd
from ml.ingestion.openf1_sessions import Client,match_session,filtered_summary
from ml.features.practice import decode_archive,historical_entries,features_for_practice,parse_time
from ml.training.outcomes import finishing_labels
from ml.live.outcomes import ROOT
from .backtest import model_arrays,TARGETS
from .metrics import assess


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--limit',type=int,default=8); args=parser.parse_args()
    if not 3<=args.limit<=17: raise ValueError('Audit 3 to 17 paired sessions')
    history=json.loads((ROOT/'data/processed/kaggle-2018-2025/history.json').read_text())['races']
    manifest=json.loads((ROOT/'data/raw/practice-archive/manifest.json').read_text())
    canonical=pd.read_csv(ROOT/'data/processed/practice-2018-2025/fp2-features.csv')
    eligible=set(canonical[canonical.season==2025].race_id)
    client=Client(ROOT/'data/raw/source-audit-openf1'); metadata=client.get('sessions',{'year':2025},ttl=86400)
    records={'FastF1':[],'OpenF1':[]}; paired=[]; excluded=[]; now=datetime.now(timezone.utc)
    for race in history:
        rid=f"{race['season']}-{int(race['round']):02d}"
        if rid not in eligible or len(paired)>=args.limit: continue
        try:
            sessions={}
            for stage in ['FP1','FP2']:
                path=ROOT/'data/raw/practice-archive'/f'{rid}-{stage}.json'
                if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['files'][f'{rid}-{stage}']['sha256']: raise ValueError('Archive checksum mismatch')
                sessions[stage]=decode_archive(json.loads(path.read_text()),race,stage)
            matched=match_session(metadata,race,'FP2',now)
            data={name:client.get(name,{'session_key':matched['session_key']},ttl=86400) for name in ['drivers','laps','stints','pit','race_control','session_result']}
            summary=filtered_summary(race,'FP2',matched,data,now)
            entries=historical_entries(race); mapping={e['abbreviation']:e['driver_id'] for e in entries}
            for d in summary['drivers']: d['driver_id']=mapping.get(d['abbreviation'],'reserve:'+d['abbreviation'])
            cutoff=max(parse_time(sessions['FP2']['ended_at']),parse_time(summary['ended_at']))+timedelta(minutes=45)
            # Offline historical availability uses session end, never today's retrieval
            # timestamp. Publication-time equivalence is deliberately not certified.
        except Exception as exc:
            excluded.append({'race_id':rid,'reason':str(exc)}); print('skip',rid,str(exc),flush=True); continue
        try:
            first=features_for_practice(race,history,entries,sessions,'FP2',cutoff,include_target=True,historical=True)
            second=features_for_practice(race,history,entries,{**sessions,'FP2':summary},'FP2',cutoff,include_target=True,historical=True)
            records['FastF1'].extend(first); records['OpenF1'].extend(second)
            paired.append({'race_id':rid,'session_key':matched['session_key'],'drivers':len(first),
                'fastf1_laps':sum(d['lap_count'] for d in sessions['FP2']['drivers']),
                'openf1_laps':sum(d['lap_count'] for d in summary['drivers'])})
            print('paired',rid,len(paired),'/',args.limit,flush=True)
        except Exception as exc: excluded.append({'race_id':rid,'reason':str(exc)})
    if len(paired)<3: raise ValueError('Insufficient paired coverage to publish source metrics: '+str(excluded))
    models={}; frames={}
    for source,rows in records.items():
        frame=finishing_labels(pd.DataFrame(rows),history); arrays,_=model_arrays(frame,'FP2'); frames[source]=frame
        models[source]={t:assess(frame.race_id,(frame.finish_label<=k).astype(int),arrays[t],k) for t,k in TARGETS.items()}
    left=frames['FastF1'].set_index(['race_id','driver_id']); right=frames['OpenF1'].set_index(['race_id','driver_id']).reindex(left.index)
    columns=['fp2_best_gap_pct','fp2_median_gap_pct','fp2_log_laps','fp2_long_run_gap_pct']
    differences={c:{'paired_values':int((left[c].notna()&right[c].notna()).sum()),'mean_absolute_difference':float((left[c]-right[c]).abs().mean()) if (left[c].notna()&right[c].notna()).any() else None} for c in columns}
    report={'status':'paired pilot','stage':'FP2','created_at':datetime.now(timezone.utc).isoformat(),'paired_sessions':paired,'excluded':excluded,
        'models':models,'input_differences':differences,
        'notice':'Paired 2025 FP2 development pilot using identical drivers, races, fixed models and earlier FP1 inputs. OpenF1 published bests / conservative aggregates differ from FastF1 clean laps. This measures source shift, not equivalence or production calibration certification. Historical publication availability is estimated. No forecasts were added to the serving database.'}
    (ROOT/'docs/source-validation-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Saved paired audit',len(paired),flush=True)


if __name__=='__main__': main()
