"""Complete post-race classification fallback; never derives results from live positions."""
import json
from datetime import datetime,timezone
from pathlib import Path
from ml.features.build import race_start
from ml.ingestion.openf1_sessions import Client,match_session
from ml.ingestion.qualifying import canonical

ROOT=Path(__file__).resolve().parents[2]


def validate(data,raw,entries=None):
    if str(data.get('season'))!=str(raw['season']) or int(data.get('round',-1))!=int(raw['round']): raise ValueError('Classification belongs to a different race')
    rows=data.get('Results',[]); ids=[r['Driver']['driverId'] for r in rows]; positions=[int(r['position']) for r in rows]
    if not rows or len(ids)!=len(set(ids)) or sorted(positions)!=list(range(1,len(rows)+1)): raise ValueError('Incomplete or duplicate race classification')
    if entries and set(ids)!={e['driver_id'] for e in entries}: raise ValueError('Race classification field differs from confirmed entrants')
    if len(rows)<10: raise ValueError('Insufficient classified race field')
    return data


def normalize(raw,entries,session,drivers,results,observed,grid=None):
    key=int(session['session_key']); meeting=int(session['meeting_key']); records=drivers+results+(grid or [])
    if any(int(r.get('session_key',-1))!=key or int(r.get('meeting_key',-1))!=meeting for r in records): raise ValueError('Wrong race session records')
    by_code={e['abbreviation'].upper():e for e in entries}; mapped={}; starting={int(r['driver_number']):int(r['position']) for r in grid or []}
    for d in drivers:
        e=by_code.get(str(d.get('name_acronym','')).upper()); number=int(d['driver_number'])
        if e:
            if e['number']!=number or number in mapped: raise ValueError('Ambiguous race entrant identity')
            mapped[number]=e
    rows=[]
    for r in results:
        e=mapped.get(int(r['driver_number']))
        if not e or not isinstance(r.get('position'),int) or isinstance(r['position'],bool): raise ValueError('Unmapped or unclassified race entrant')
        if not all(isinstance(r.get(k),bool) for k in ['dnf','dns','dsq']): raise ValueError('Missing published race status flags')
        q=canonical(e,r['position'],[]); q['grid']=str(starting.get(int(r['driver_number']),0)); q['laps']=str(r.get('number_of_laps',0))
        q['status']='Disqualified' if r['dsq'] else 'Did not start' if r['dns'] else 'Retired' if r['dnf'] else 'Finished'
        rows.append(q)
    return validate({**raw,'Results':sorted(rows,key=lambda r:int(r['position'])),'source':'OpenF1',
        'source_url':f'https://api.openf1.org/v1/session_result?session_key={key}','observed_at':observed.isoformat(),
        'session_key':key,'ended_at':session['date_end'],'quality_policy':'published-full-race-v1',
        'notice':'Published post-race classification. Unknown starting grids remain 0 and are excluded from grid-specific priors.'},raw,entries)


def openf1(raw,entries,client=None,now=None):
    provided=now; now=now or datetime.now(timezone.utc); client=client or Client()
    try:
        session=match_session(client.get('sessions',{'year':int(raw['season'])},ttl=300),raw,'R',now)
        params={'session_key':session['session_key']}
        drivers=client.get('drivers',params,ttl=300); results=client.get('session_result',params,ttl=300)
        try: grid=client.get('starting_grid',params,ttl=3600)
        except Exception: grid=[]  # grid is optional; final positions are never used as grid positions
        return normalize(raw,entries,session,drivers,results,provided or datetime.now(timezone.utc),grid)
    finally:
        if hasattr(client,'http'): client.http.close()


def fastf1(raw,entries,now):
    """Use published result positions, never infer retirement order from lap counts."""
    import fastf1 as source
    import math
    from datetime import timedelta
    if now < race_start(raw)+timedelta(hours=3): raise ValueError('Race publication guard has not elapsed')
    with source.Cache.disabled():
        session=source.get_session(int(raw['season']),int(raw['round']),'R')
        session.load(laps=False,telemetry=False,weather=False,messages=False)
    mapping={e['abbreviation'].upper():e for e in entries}; rows=[]
    for _,r in session.results.iterrows():
        entry=mapping.get(str(r.Abbreviation).upper()); position=float(r.Position)
        if entry is None or int(r.DriverNumber)!=entry['number'] or not math.isfinite(position) or not position.is_integer(): raise ValueError('FastF1 final classification is incomplete')
        row=canonical(entry,int(position),[])
        grid=float(r.GridPosition)
        row.update(grid=str(int(grid)) if math.isfinite(grid) and grid.is_integer() else '0',status=str(r.Status),laps=str(int(r.Laps)) if math.isfinite(float(r.Laps)) else '0')
        rows.append(row)
    return validate({**raw,'Results':sorted(rows,key=lambda r:int(r['position'])),'source':'FastF1',
        'source_url':'https://docs.fastf1.dev/core.html#fastf1.core.Session.results','observed_at':now.isoformat(),
        'quality_policy':'published-full-race-v1','notice':'Published FastF1 results; its results backend may share Jolpica availability.'},raw,entries)


def load(raw,entries,primary=None,cache=None,now=None):
    now=now or datetime.now(timezone.utc)
    if now<=race_start(raw): raise ValueError('Cannot retrieve a finished classification before race start')
    folder=Path(cache or ROOT/'data/raw/live'); folder.mkdir(parents=True,exist_ok=True); path=folder/f"{raw['season']}-{int(raw['round']):02d}-R.json"
    data=None; error=None
    if primary:
        try: data={**validate(primary,raw,entries),'source':'Jolpica','observed_at':now.isoformat()}
        except (KeyError,ValueError) as exc: error=exc
    if data is None:
        try: data=openf1(raw,entries,now=now)
        except Exception as exc: error=exc
    if data is None:
        try: data=fastf1(raw,entries,now)
        except Exception as exc: error=exc
    if data is not None:
        temporary=path.with_suffix('.tmp'); temporary.write_text(json.dumps(data),encoding='utf-8'); temporary.replace(path); return data
    if path.exists():
        data=validate(json.loads(path.read_text()),raw,entries); data['refresh_warning']='Result sources delayed; using the last complete published classification.'; return data
    raise ValueError(f'Final race classification not available yet: {error}')
