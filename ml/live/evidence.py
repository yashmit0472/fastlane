"""Freeze descriptive evidence with each forecast; never invent feature attribution."""
import json
from pathlib import Path
from ml.features.build import race_start,comparable_qualifying

ROOT=Path(__file__).resolve().parents[2]
EVIDENCE_VERSION='observed-inputs-v2'


def confirmed_entries(raw,cutoff):
    path=ROOT/'data/raw/entries'/f"{raw['season']}-{int(raw['round']):02d}.json"
    if not path.exists(): return None
    from ml.features.practice import parse_time
    payload=json.loads(path.read_text())
    if payload.get('race_id')!=f"{raw['season']}-{int(raw['round']):02d}": raise ValueError('Entry list belongs to another race')
    if not payload.get('source_url','').startswith('https://') or parse_time(payload['available_at'])>cutoff: raise ValueError('Entry-list source/availability is not verified at cutoff')
    entries=payload['entries']
    if not 10<=len(entries)<=30 or len({e['driver_id'] for e in entries})!=len(entries) or len({e['number'] for e in entries})!=len(entries): raise ValueError('Invalid complete entry list')
    required={'driver_id','constructor_id','name','abbreviation','number','team','color'}
    if any(not required.issubset(e) for e in entries): raise ValueError('Incomplete entry metadata')
    return entries,payload


def attach_evidence(forecast,raw,history,entries,practice,stage,cutoff,weather=None,entry_source=None):
    past=sorted([r for r in history if race_start(r)<cutoff and race_start(r)<race_start(raw)],key=race_start)
    teams={e['driver_id']:e['constructor_id'] for e in entries}
    latest={d['driver_id']:d for d in practice.get(stage,{}).get('drivers',[])}
    qualifying=raw.get('QualifyingResults',[]) if stage=='Q' else []
    for driver in forecast['drivers']:
        if entry_source and stage!='Q':
            driver['factors']=[('FIA-listed event identities' if f=='Provisional field from latest completed Grand Prix' else f) for f in driver.get('factors',[])]
        did=driver['driver_id']; teammate=next((d for d in teams if d!=did and teams[d]==teams.get(did)),None)
        recent=[]
        for event in past:
            result=next((r for r in event.get('Results',[]) if r['Driver']['driverId']==did),None)
            if result: recent.append({'race':event.get('raceName',event['date']),'date':event['date'],'position':int(result['position'])})
        row=latest.get(did,{}); other=latest.get(teammate,{})
        compound=row.get('long_run_compound')
        matched=compound is not None and compound==other.get('long_run_compound')
        long_gap=(row['long_run_lap_ms']-other['long_run_lap_ms'])/1000 if matched and row.get('long_run_lap_ms') is not None and other.get('long_run_lap_ms') is not None else None
        driver['observations']={'kind':'observed data; not a causal model explanation','available_at':cutoff.isoformat(),
            'recent_results':recent[-5:],'recent_average_finish':sum(r['position'] for r in recent[-5:])/len(recent[-5:]) if recent else None,
            'teammate_id':teammate,'qualifying':comparable_qualifying(qualifying,did,teammate) if stage=='Q' else None,
            'practice':{'stage':stage,'best_lap_ms':row.get('best_lap_ms'),'median_lap_ms':row.get('representative_lap_ms'),
                'gap_s':row['gap_ms']/1000 if row.get('gap_ms') is not None else None,'filtered_laps':row.get('lap_count'),
                'small_sample':row.get('lap_count',0)<5,'compound':compound,'long_run_lap_ms':row.get('long_run_lap_ms'),
                'long_run_laps':row.get('long_run_laps'),'teammate_long_run_gap_s':long_gap,
                'source':practice.get(stage,{}).get('source')} if stage!='Q' else None}
    eligible={e['driver_id'] for e in entries}
    usable={d for d,r in latest.items() if r.get('best_lap_ms') is not None}
    forecast['input_quality']={'evidence_version':EVIDENCE_VERSION,
        'roster':'qualifying participants' if stage=='Q' else 'confirmed pre-event entry list' if entry_source else 'provisional prior-race roster',
        'roster_source':entry_source.get('source_url') if entry_source else None,
        'metadata_conflicts':entry_source.get('metadata_conflicts',[]) if entry_source else [],
        'timing_coverage':len(usable&eligible)/len(eligible) if stage!='Q' and eligible else None,
        'missing_entered_drivers':sorted(eligible-usable) if stage!='Q' else [],
        'extra_practice_participants':sorted(usable-eligible) if stage!='Q' else [],
        'source_switch':any(s.get('source')=='OpenF1' for s in practice.values()),
        'weather_model_input':False,'attribution':'Observed comparisons do not explain the model causally.'}
    if entry_source and stage!='Q': forecast['field_status']='FIA-listed event identities'+(' (numbering discrepancy flagged)' if entry_source.get('metadata_conflicts') else '')
    from ml.features.practice import parse_time
    if weather and parse_time(weather['available_at'])<=cutoff: forecast['weather_context']=weather
    return forecast
