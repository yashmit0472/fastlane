"""Audit explicitly supplied CSV files and import validated session metadata only."""
import argparse
import csv
import hashlib
import io
import json
import math
from datetime import datetime,timezone
from pathlib import Path
from ml.ingestion.practice_archive import DEFAULT_HISTORY
from ml.features.build import race_start

ROOT=Path(__file__).resolve().parents[2]
SESSION_INDEX=ROOT/'data/processed/openf1/session-index.json'
STAGES={'Practice 1':'FP1','Practice 2':'FP2','Practice 3':'FP3','Qualifying':'Q','Race':'R','Sprint':'Sprint','Sprint Qualifying':'SQ','Sprint Shootout':'SQ'}


def timestamp(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None: raise ValueError('Session timestamps must include timezone')
    return result.astimezone(timezone.utc)


def country(value):
    text=value.strip().casefold()
    return {'usa':'united states','us':'united states','uk':'united kingdom','great britain':'united kingdom','uae':'united arab emirates'}.get(text,text)


def session_index(rows,history):
    normalized=[]; seen=set()
    for row in rows:
        key=int(row['session_key'])
        if key in seen: raise ValueError('Duplicate session_key; refusing ambiguous import')
        seen.add(key)
        start,end=timestamp(row['date_start']),timestamp(row['date_end'])
        if end<=start or start.year!=int(row['year']): raise ValueError('Invalid session date range/year')
        flag=row['is_cancelled'].strip().casefold()
        if flag not in {'true','false'}: raise ValueError('Unknown cancellation flag')
        normalized.append({'session_key':key,'meeting_key':int(row['meeting_key']),'stage':STAGES.get(row['session_name']),
            'session_name':row['session_name'],'started_at':start.isoformat(),'ended_at':end.isoformat(),
            'cancelled':flag=='true','year':start.year,'country':row['country_name'],'circuit_short_name':row['circuit_short_name']})
    meetings={}
    for session in normalized:
        if session['stage']!='R' or session['cancelled']: continue
        start=timestamp(session['started_at'])
        candidates=[r for r in history if race_start(r).date()==start.date()
            and abs((race_start(r)-start).total_seconds())<=6*3600
            and country(r['Circuit'].get('Location',{}).get('country',''))==country(session['country'])]
        if len(candidates)!=1: continue
        race=candidates[0]
        meetings[session['meeting_key']]={'race_id':f"{race['season']}-{int(race['round']):02d}",'circuit_id':race['Circuit']['circuitId'],
            'country':session['country'],'scheduled_at':race_start(race).isoformat()}
    races={}
    for session in normalized:
        meeting=meetings.get(session['meeting_key'])
        if not meeting or session['cancelled'] or session['stage'] is None: continue
        if country(session['country'])!=country(meeting['country']): raise ValueError('Meeting country mismatch')
        if abs((timestamp(meeting['scheduled_at'])-timestamp(session['started_at'])).total_seconds())>7*86400:
            raise ValueError('Session outside matched race weekend')
        session['race_id']=meeting['race_id']
        target=races.setdefault(meeting['race_id'],{**meeting,'meeting_key':session['meeting_key'],'sessions':{}})
        if session['stage'] in target['sessions']: raise ValueError('Duplicate stage in matched meeting')
        target['sessions'][session['stage']]=session
    return {'schema_version':'openf1-session-index-v1','races':races,'sessions':normalized,
        'coverage':{'session_rows':len(normalized),'mapped_races':len(races),
            'mapped_sessions':sum(len(r['sessions']) for r in races.values()),
            'cancelled_sessions':sum(s['cancelled'] for s in normalized),
            'unmapped_sessions':sum('race_id' not in s for s in normalized)}}


def distance_km(lat,lon,other_lat,other_lon):
    a,b=math.radians(lat),math.radians(other_lat)
    h=math.sin((b-a)/2)**2+math.cos(a)*math.cos(b)*math.sin(math.radians(other_lon-lon)/2)**2
    return 6371*2*math.asin(math.sqrt(min(h,1)))


def weather_audit(content,history):
    lines=content.decode('utf-8-sig').splitlines()
    metadata=next(csv.DictReader(lines[:2])); header=next(i for i,line in enumerate(lines) if line.startswith('time,'))
    rows=list(csv.DictReader(lines[header:])); lat=float(metadata['latitude']); lon=float(metadata['longitude'])
    if not (-90<=lat<=90 and -180<=lon<=180) or not rows: raise ValueError('Invalid weather coordinates or empty observations')
    circuits={r['Circuit']['circuitId']:r['Circuit'] for r in history}; nearest=[]
    for key,circuit in circuits.items():
        loc=circuit.get('Location',{})
        if loc.get('lat') and loc.get('long'):
            nearest.append((distance_km(lat,lon,float(loc['lat']),float(loc['long'])),key))
    closest=min(nearest) if nearest else (None,None); reasons=[]
    if closest[0] is None or closest[0]>25: reasons.append('Coordinates do not match a known F1 circuit within 25 km')
    if min(r['time'] for r in rows)[:4]>'2025': reasons.append('Dates are outside the 2018–2025 training window')
    reasons.append('No audited forecast issue/availability timestamp for a prediction cutoff')
    return {'kind':'weather','status':'excluded from training','training_eligible':False,'rows':len(rows),
        'latitude':lat,'longitude':lon,'timezone':metadata.get('timezone'),'utc_offset_seconds':metadata.get('utc_offset_seconds'),
        'first_valid_time':min(r['time'] for r in rows),'last_valid_time':max(r['time'] for r in rows),
        'columns':list(rows[0]),'nearest_circuit_id':closest[1],
        'nearest_circuit_distance_km':round(closest[0],1) if closest[0] is not None else None,'reasons':reasons}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--files',nargs='+',type=Path,required=True)
    parser.add_argument('--history',type=Path,default=DEFAULT_HISTORY)
    args=parser.parse_args(); history=json.loads(args.history.read_text(encoding='utf-8'))['races']; results=[]
    for path in args.files:
        content=path.read_bytes(); sha=hashlib.sha256(content).hexdigest(); entry={'file':path.name,'sha256':sha,'bytes':len(content)}
        try:
            first=content.decode('utf-8-sig').splitlines()[0]
            if 'session_key' in first.split(',') and 'date_start' in first.split(','):
                index=session_index(list(csv.DictReader(io.StringIO(content.decode('utf-8-sig')))),history)
                if not index['races']: raise ValueError('No race weekends matched the existing history')
                index['source']={'provider':'user-provided OpenF1-format session export','filename':path.name,'sha256':sha,
                    'imported_at':datetime.now(timezone.utc).isoformat(),'publication_availability_audited':False}
                SESSION_INDEX.parent.mkdir(parents=True,exist_ok=True); SESSION_INDEX.write_text(json.dumps(index,indent=2),encoding='utf-8')
                raw=ROOT/'data/raw/user-imports'/f'{sha[:12]}-{path.name}'; raw.parent.mkdir(parents=True,exist_ok=True); raw.write_bytes(content)
                entry.update(kind='session metadata',status='imported',training_eligible=False,
                    purpose='Session identity, cancellation checks and conservative historical timing bounds; no new lap/pace features.',
                    coverage=index['coverage'],index=SESSION_INDEX.relative_to(ROOT).as_posix())
            elif first.startswith('latitude,longitude,'): entry.update(weather_audit(content,history))
            else: entry.update(status='not imported',reason='Unrecognized dataset schema')
        except Exception as exc: entry.update(status='not imported',reason=str(exc))
        results.append(entry)
    report={'audited_at':datetime.now(timezone.utc).isoformat(),'files':results,'models_retrained':False,
        'notice':'Session metadata is not additional race/driver training examples. Invalid weather is never merged into inputs.'}
    (ROOT/'docs/downloaded-datasets-audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
