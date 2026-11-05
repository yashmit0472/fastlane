"""One schema for historical FP-stage training and live inference; never reads qualifying/grid."""
import argparse
import hashlib
import json
import math
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from ml.features.build import race_start
from ml.ingestion.fastf1_sessions import summarize
from ml.ingestion.practice_archive import DEFAULT_HISTORY,DEFAULT_OUTPUT,STAGES
from ml.ingestion.downloaded_data import SESSION_INDEX

ROOT=Path(__file__).resolve().parents[2]
FEATURE_VERSION='practice-history-v1'
STAGE_ORDER=['FP1','FP2','FP3']
HISTORY_NUMERIC=['recent_finish','recent_win_rate','team_recent_finish','team_recent_win_rate',
    'driver_circuit_win_rate','team_circuit_win_rate','driver_prior_starts']
SESSION_NUMERIC=['best_gap_pct','median_gap_pct','log_laps','lap_iqr_pct','teammate_gap_pct',
    'soft_fraction','mean_tyre_age','long_run_gap_pct','long_run_laps','available']
CATEGORICAL=['driver_id','constructor_id','circuit_id']


def numeric(stage):
    return HISTORY_NUMERIC+[f'{s.lower()}_{name}' for s in STAGE_ORDER[:STAGE_ORDER.index(stage)+1] for name in SESSION_NUMERIC]


def parse_time(value):
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None: raise ValueError('Timezone-aware timestamp required')
    return stamp


def historical_entries(race):
    # Identities only. Retrospectively confirmed race roster is an explicit backtest limitation.
    return [{'driver_id':r['Driver']['driverId'],'constructor_id':r['Constructor']['constructorId'],
        'abbreviation':r['Driver'].get('code','')} for r in race.get('Results',[])]


def features_for_practice(race,history,entries,sessions,stage,cutoff,include_target=False,historical=False):
    start=race_start(race)
    if cutoff>=start: raise ValueError('Practice cutoff must precede race start')
    if race.get('Sprint') or race.get('SprintResults'): raise ValueError('Sprint formats require separately evaluated practice models')
    allowed=STAGE_ORDER[:STAGE_ORDER.index(stage)+1]
    eligible={name:s for name,s in sessions.items() if name in allowed}
    if stage not in eligible: raise ValueError('Stage session is missing')
    for name,session in eligible.items():
        if session.get('race_id')!=f"{race['season']}-{int(race['round']):02d}":
            raise ValueError('Practice session belongs to a different race')
        if session.get('type')!=name: raise ValueError('Practice stage identity mismatch')
        key='ended_at' if historical else 'observed_at'
        if not session.get(key) or parse_time(session[key])>cutoff:
            raise ValueError(f'{name} timing unavailable at cutoff')
    if not entries or len({e['driver_id'] for e in entries})!=len(entries): raise ValueError('Unique complete field required')
    latest={r['driver_id']:r for r in eligible[stage]['drivers']}
    if sum(latest.get(e['driver_id'],{}).get('best_lap_ms') is not None for e in entries)<max(2,math.ceil(.7*len(entries))):
        raise ValueError('Insufficient current-stage coverage of the entered field')
    past=sorted([r for r in history if race_start(r)<cutoff and race_start(r)<start],key=race_start)
    circuit_id=race['Circuit']['circuitId']
    outcomes={r['Driver']['driverId']:int(r['position']) for r in race.get('Results',[])} if include_target else {}
    # Qualifying identities are used only to reject inconsistent historical
    # rosters (e.g. a later DNS), never as practice model inputs.
    if include_target and race.get('QualifyingResults'):
        qualified={q['Driver']['driverId'] for q in race['QualifyingResults']}
        if qualified!=set(outcomes): raise ValueError('Historical participant roster differs between source tables')
    if include_target and (set(outcomes)!={e['driver_id'] for e in entries} or sum(p==1 for p in outcomes.values())!=1):
        raise ValueError('Targets require a full one-winner field')
    rows=[]
    historical_policy=('estimated: max(recorded lap end, checked OpenF1 session end) + 10m; retrospective confirmed roster'
        if eligible[stage].get('metadata_ended_at') else 'estimated: last recorded practice lap + 10m; retrospective confirmed roster')
    for entry in sorted(entries,key=lambda e:e['driver_id']):
        driver=entry['driver_id']; team=entry['constructor_id']
        driver_past=[r for event in past for r in event.get('Results',[]) if r['Driver']['driverId']==driver]
        recent=driver_past[-5:]
        team_recent=[r for event in past[-5:] for r in event.get('Results',[]) if r['Constructor']['constructorId']==team]
        local=[r for event in past if event['Circuit']['circuitId']==circuit_id for r in event.get('Results',[])]
        def win_rate(results): return (sum(int(r['position'])==1 for r in results)+.5)/(len(results)+10)
        row={'race_id':f"{race['season']}-{int(race['round']):02d}",'season':int(race['season']),
            'race_date':start.isoformat(),'cutoff':cutoff.isoformat(),'stage':stage,'feature_version':FEATURE_VERSION,
            'availability_policy':historical_policy if historical else 'observed completed practice before cutoff',
            'driver_id':driver,'constructor_id':team,'circuit_id':circuit_id,
            'recent_finish':float(np.mean([int(r['position']) for r in recent])) if recent else None,
            'recent_win_rate':win_rate(recent),'team_recent_finish':float(np.mean([int(r['position']) for r in team_recent])) if team_recent else None,
            'team_recent_win_rate':win_rate(team_recent),'driver_prior_starts':len(driver_past),
            'driver_circuit_win_rate':win_rate([r for r in local if r['Driver']['driverId']==driver]),
            'team_circuit_win_rate':win_rate([r for r in local if r['Constructor']['constructorId']==team])}
        for name in allowed:
            values=eligible.get(name,{}).get('drivers',[])
            by_id={r['driver_id']:r for r in values}; value=by_id.get(driver,{})
            best=min((r['best_lap_ms'] for r in values if r.get('best_lap_ms') is not None),default=None)
            median=min((r['representative_lap_ms'] for r in values if r.get('representative_lap_ms') is not None),default=None)
            team_values=[by_id[e['driver_id']]['best_lap_ms'] for e in entries if e['constructor_id']==team and e['driver_id']!=driver and by_id.get(e['driver_id'],{}).get('best_lap_ms') is not None]
            long_best=min((r['long_run_lap_ms'] for r in values if r.get('long_run_lap_ms') is not None and r.get('long_run_compound')==value.get('long_run_compound')),default=None)
            def gap(v,reference): return 100*(v/reference-1) if v is not None and reference else None
            features={'best_gap_pct':gap(value.get('best_lap_ms'),best),'median_gap_pct':gap(value.get('representative_lap_ms'),median),
                'log_laps':math.log1p(value['lap_count']) if value.get('lap_count') is not None else None,
                'lap_iqr_pct':100*value['lap_iqr_ms']/best if value.get('lap_iqr_ms') is not None and best else None,
                'teammate_gap_pct':gap(value.get('best_lap_ms'),min(team_values)) if team_values else None,
                'soft_fraction':value.get('soft_fraction'),'mean_tyre_age':value.get('mean_tyre_age'),
                'long_run_gap_pct':gap(value.get('long_run_lap_ms'),long_best),'long_run_laps':value.get('long_run_laps'),
                'available':int(value.get('best_lap_ms') is not None)}
            row.update({name.lower()+'_'+key:v for key,v in features.items()})
        if include_target: row['target']=int(outcomes[driver]==1)
        rows.append(row)
    return rows


def decode_archive(data,race,stage):
    required={'time','drv','lSD','iacc','del','status','pin','pout'}
    if not required.issubset(data): raise ValueError('Missing timing identity, timestamp or quality flags')
    size=len(data['time'])
    if not size or any(not isinstance(data[k],list) or len(data[k])!=size for k in required): raise ValueError('Inconsistent lap arrays')
    frame=pd.DataFrame({k:v for k,v in data.items() if isinstance(v,list) and len(v)==size})
    frame=frame.replace({'None':None,'nan':None,'NaT':None})
    times=pd.to_numeric(frame.time,errors='coerce')
    if times.dropna().empty or not times.dropna().between(20,1000).all(): raise ValueError('Unexpected lap-time units/range')
    dates=pd.to_datetime(frame.lSD,utc=True,errors='coerce')
    if dates.isna().all(): raise ValueError('Lap UTC timestamps missing')
    if dates.min().to_pydatetime()<race_start(race)-timedelta(days=7) or dates.max().to_pydatetime()>=race_start(race):
        raise ValueError('Practice lap timestamps outside target weekend')
    field=STAGES[stage]; scheduled=race.get(field,{})
    if scheduled.get('date') and set(dates.dropna().dt.date.astype(str))!={scheduled['date']}: raise ValueError('Lap dates disagree with session identity')
    for col in ['iacc','del']:
        if not frame[col].dropna().isin([True,False]).all(): raise ValueError('Unknown boolean flag encoding')
    laps=pd.DataFrame({'LapTime':pd.to_timedelta(times,unit='s'),'Driver':frame.drv,
        'PitInTime':pd.to_timedelta(pd.to_numeric(frame.pin,errors='coerce'),unit='s'),
        'PitOutTime':pd.to_timedelta(pd.to_numeric(frame.pout,errors='coerce'),unit='s'),
        'IsAccurate':frame.iacc,'Deleted':frame['del'],'TrackStatus':frame.status.astype(str)})
    for old,new in [('compound','Compound'),('stint','Stint'),('lap','LapNumber'),('life','TyreLife')]:
        if old in frame: laps[new]=frame[old] if old=='compound' else pd.to_numeric(frame[old],errors='coerce')
    mapping={e['abbreviation']:e['driver_id'] for e in historical_entries(race)}
    metadata=pd.DataFrame([{'Abbreviation':code,'DriverId':mapping.get(code,'reserve:'+code),
        'FullName':code,'TeamName':'','TeamColor':'888888'} for code in frame.drv.dropna().unique()])
    ended=(dates+pd.to_timedelta(times.fillna(0),unit='s')).max().to_pydatetime()
    return {'race_id':f"{race['season']}-{int(race['round']):02d}",'type':stage,'started_at':dates.min().to_pydatetime().isoformat(),
        'ended_at':ended.isoformat(),'drivers':summarize(laps,metadata)}


class SessionMetadataConflict(ValueError):
    """An optional external clock disagrees with primary recorded laps."""


def apply_session_metadata(summary,metadata):
    if metadata['race_id']!=summary['race_id'] or metadata['stage']!=summary['type']:
        raise ValueError('External session metadata belongs to another race/stage')
    if metadata['cancelled']: raise ValueError('External source marks session cancelled')
    start,end=parse_time(metadata['started_at']),parse_time(metadata['ended_at'])
    first,last=parse_time(summary['started_at']),parse_time(summary['ended_at'])
    if first<start-timedelta(minutes=10) or first>end+timedelta(minutes=60) or last>end+timedelta(minutes=60):
        raise SessionMetadataConflict('Practice laps disagree with external session time window; external timing ignored')
    return {**summary,'metadata_session_key':metadata['session_key'],'metadata_ended_at':end.isoformat()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history',type=Path,default=DEFAULT_HISTORY)
    parser.add_argument('--session-dir',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'data/processed/practice-2018-2025')
    parser.add_argument('--session-index',type=Path,default=SESSION_INDEX)
    args=parser.parse_args(); args.output_dir.mkdir(parents=True,exist_ok=True)
    history=json.loads(args.history.read_text(encoding='utf-8'))['races']
    manifest=json.loads((args.session_dir/'manifest.json').read_text())
    session_index=json.loads(args.session_index.read_text(encoding='utf-8')) if args.session_index.exists() else None
    if session_index and session_index.get('schema_version')!='openf1-session-index-v1': raise ValueError('Unsupported session index schema')
    rows={stage:[] for stage in STAGE_ORDER}; coverage=[]
    for race in sorted(history,key=race_start):
        if not 2018<=int(race['season'])<=2025: continue
        key=f"{race['season']}-{int(race['round']):02d}"
        if race.get('Sprint') or race.get('SprintResults'):
            coverage.append({'race_id':key,'status':'excluded sprint'}); continue
        sessions={}
        for stage in STAGE_ORDER:
            try:
                path=args.session_dir/f'{key}-{stage}.json'; content=path.read_bytes()
                if hashlib.sha256(content).hexdigest()!=manifest['files'][f'{key}-{stage}']['sha256']: raise ValueError('Source checksum mismatch')
                sessions[stage]=decode_archive(json.loads(content),race,stage)
                metadata=session_index.get('races',{}).get(key,{}).get('sessions',{}).get(stage) if session_index else None
                metadata_warning=None
                if metadata:
                    try: sessions[stage]=apply_session_metadata(sessions[stage],metadata)
                    except SessionMetadataConflict as exc: metadata_warning=str(exc)
                ended=max(parse_time(sessions[stage]['ended_at']),parse_time(sessions[stage].get('metadata_ended_at',sessions[stage]['ended_at'])))
                cutoff=ended+timedelta(minutes=10)
                features=features_for_practice(race,history,historical_entries(race),sessions,stage,cutoff,include_target=True,historical=True)
                rows[stage].extend(features)
                coverage.append({'race_id':key,'stage':stage,'status':'included','drivers':len(features),'cutoff':cutoff.isoformat(),
                    'metadata_session_key':sessions[stage].get('metadata_session_key'),
                    'metadata_candidate_key':metadata.get('session_key') if metadata else None,'metadata_warning':metadata_warning})
            except Exception as exc:
                coverage.append({'race_id':key,'stage':stage,'status':'excluded','reason':str(exc)})
    report={'feature_version':FEATURE_VERSION,'source_manifest_sha256':hashlib.sha256((args.session_dir/'manifest.json').read_bytes()).hexdigest(),
        'limitations':['Historical availability estimated, not an archived publication audit.','Historical field uses retrospectively confirmed participants.','Sprint weekends excluded.','Long-run proxy is matched by compound and consecutive clean laps, not fuel-adjusted.','2025 is a previously inspected development benchmark, not an untouched final test.'],'stages':{},'coverage':coverage}
    if session_index: report['session_index_sha256']=hashlib.sha256(args.session_index.read_bytes()).hexdigest()
    for stage,values in rows.items():
        if not values: raise ValueError(f'No eligible {stage} races')
        frame=pd.DataFrame(values); frame.to_csv(args.output_dir/f'{stage.lower()}-features.csv',index=False)
        report['stages'][stage]={'races':int(frame.race_id.nunique()),'rows':len(frame),'seasons':frame.groupby('season').race_id.nunique().to_dict()}
    (args.output_dir/'coverage.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report['stages'],indent=2))


if __name__=='__main__': main()
