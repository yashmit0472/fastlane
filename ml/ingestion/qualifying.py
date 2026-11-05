"""Verified, complete qualifying results from Jolpica, OpenF1 or FastF1."""
import math
from datetime import datetime,timezone
from ml.features.build import lap_ms
from ml.ingestion.openf1_sessions import Client,match_session,stamp


def validate(raw,expected,require_final=True):
    rows=raw.get('QualifyingResults',[])
    ids=[r['Driver']['driverId'] for r in rows]
    positions=[int(r['position']) for r in rows]
    if not rows or len(set(ids))!=len(ids) or (expected and set(ids)!={e['driver_id'] for e in expected}): raise ValueError('Qualifying classification does not match the complete expected field')
    if sorted(positions)!=list(range(1,len(rows)+1)): raise ValueError('Qualifying positions are incomplete or duplicated')
    # Current knockout qualifying requires a published final phase, not a Q1-only response.
    if require_final and sum(lap_ms(r.get('Q3')) is not None for r in rows)<2: raise ValueError('Final qualifying phase has not been published')
    for row in rows:
        for phase in ['Q1','Q2','Q3']:
            if row.get(phase) not in (None,'') and (lap_ms(row[phase]) is None or not 30000<=lap_ms(row[phase])<=600000): raise ValueError('Invalid qualifying phase timing')
    return raw


def canonical(entry,position,times):
    first,_,last=entry['name'].rpartition(' ')
    row={'position':str(position),'number':str(entry['number']),
        'Driver':{'driverId':entry['driver_id'],'code':entry['abbreviation'],'givenName':first,'familyName':last},
        'Constructor':{'constructorId':entry['constructor_id'],'name':entry['team']}}
    for phase,value in zip(['Q1','Q2','Q3'],times):
        if value is not None:
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 30<=value<=600: raise ValueError('Invalid published phase duration')
            ms=int(round(value*1000)); row[phase]=f'{ms//60000}:{(ms%60000)/1000:06.3f}'
    return row


def normalize_openf1(raw,entries,session,drivers,results,observed):
    key=int(session['session_key']); meeting=int(session['meeting_key'])
    if any(int(r.get('session_key',-1))!=key or int(r.get('meeting_key',-1))!=meeting for r in drivers+results): raise ValueError('Qualifying records belong to another session/meeting')
    by_code={e['abbreviation'].upper():e for e in entries}; metadata={}
    for driver in drivers:
        code=str(driver.get('name_acronym','')).upper(); entry=by_code.get(code)
        if entry:
            number=int(driver['driver_number'])
            if number!=entry['number']: raise ValueError('Qualifying driver number conflicts with confirmed identity')
            if number in metadata: raise ValueError('Duplicate qualifying driver metadata')
            metadata[number]=entry
    rows=[]
    for result in results:
        number=int(result['driver_number']); entry=metadata.get(number)
        if entry is None: raise ValueError('Published qualifying driver could not be mapped to a confirmed entrant')
        times=result.get('duration')
        if not isinstance(times,list) or len(times)!=3: raise ValueError('Expected published Q1/Q2/Q3 timing array')
        rows.append(canonical(entry,int(result['position']),times))
    return validate({'season':raw['season'],'round':raw['round'],'QualifyingResults':sorted(rows,key=lambda q:int(q['position'])),
        'source':'OpenF1','source_url':f'https://api.openf1.org/v1/session_result?session_key={key}',
        'session_key':key,'meeting_key':meeting,'started_at':session['date_start'],'ended_at':session['date_end'],
        'observed_at':observed.isoformat(),'quality_policy':'published-qualifying-v1'},entries)


def openf1(raw,entries,client=None,now=None):
    provided_now=now; now=now or datetime.now(timezone.utc); client=client or Client()
    try:
        session=match_session(client.get('sessions',{'year':int(raw['season'])},ttl=300),raw,'Q',now)
        params={'session_key':session['session_key']}
        drivers=client.get('drivers',params,ttl=300); results=client.get('session_result',params,ttl=300)
        return normalize_openf1(raw,entries,session,drivers,results,provided_now or datetime.now(timezone.utc))
    finally:
        if hasattr(client,'http'): client.http.close()


def fastf1(raw,entries):
    import fastf1 as source
    with source.Cache.disabled():
        session=source.get_session(int(raw['season']),int(raw['round']),'Q'); session.load(telemetry=False,weather=False,messages=False)
    statuses=session.session_status
    if statuses.empty or statuses.sort_values('Time').iloc[-1]['Status'] not in {'Finished','Finalised','Ends'}: raise ValueError('FastF1 qualifying is not confirmed complete')
    mapping={e['abbreviation'].upper():e for e in entries}; rows=[]
    import pandas as pd
    for _,r in session.results.iterrows():
        entry=mapping.get(str(r.Abbreviation).upper())
        if entry is None: raise ValueError('FastF1 qualifying driver mapping unavailable')
        rows.append(canonical(entry,int(r.Position),[r[p].total_seconds() if pd.notna(r.get(p)) else None for p in ['Q1','Q2','Q3']]))
    return validate({'season':raw['season'],'round':raw['round'],'QualifyingResults':sorted(rows,key=lambda q:int(q['position'])),
        'source':'FastF1','observed_at':datetime.now(timezone.utc).isoformat(),'quality_policy':'published-qualifying-v1'},entries)
