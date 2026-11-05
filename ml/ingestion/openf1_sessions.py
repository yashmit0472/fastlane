"""Free completed-session fallback. Never requests the paid live window."""
import hashlib
import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
import pandas as pd
from ml.ingestion.fastf1_sessions import summarize

ROOT = Path(__file__).resolve().parents[2]
BASE = 'https://api.openf1.org/v1'
FIELDS = {'FP1':'FirstPractice','FP2':'SecondPractice','FP3':'ThirdPractice','Q':'Qualifying','R':'Race'}


def stamp(value):
    result = datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None: raise ValueError('Source timestamp must include timezone')
    return result


def country(value):
    value = str(value).lower().strip()
    return {'usa':'united states','uk':'united kingdom','uae':'united arab emirates'}.get(value,value)


def match_session(sessions, raw, stage, now):
    expected = {'date':raw['date'],'time':raw['time']} if stage=='R' else raw[FIELDS[stage]]
    start = stamp(expected['date']+'T'+expected['time'])
    matches = [s for s in sessions if s.get('year')==int(raw['season']) and not s.get('is_cancelled')
        and s.get('session_name')==({'Q':'Qualifying','R':'Race'}.get(stage,'Practice '+stage[-1]))
        and country(s.get('country_name'))==country(raw['Circuit']['Location']['country'])
        and abs((stamp(s['date_start'])-start).total_seconds())<=3*3600]
    if len(matches)!=1: raise ValueError('No unique OpenF1 session matching this race, stage and scheduled time')
    session = matches[0]
    if stamp(session['date_end'])<=stamp(session['date_start']): raise ValueError('Invalid session time window')
    if now < stamp(session['date_end'])+timedelta(minutes=30):
        raise ValueError('Waiting for the free OpenF1 window: 30 minutes after session end')
    return session


class Client:
    def __init__(self, cache=None):
        self.cache = Path(cache or ROOT/'data/raw/openf1'); self.cache.mkdir(parents=True,exist_ok=True)
        self.http = httpx.Client(timeout=25,headers={'User-Agent':'FASTLANE educational post-session analysis'})
        self.last_request = 0.

    def get(self, endpoint, params, ttl=3600):
        key=hashlib.sha256(json.dumps([endpoint,params],sort_keys=True).encode()).hexdigest()[:24]
        path=self.cache/(key+'.json'); now=datetime.now(timezone.utc)
        if path.exists():
            saved=json.loads(path.read_text())
            if (now-stamp(saved['observed_at'])).total_seconds()<ttl: return saved['records']
        for attempt in range(3):
            time.sleep(max(0,2.1-(time.monotonic()-self.last_request)))
            self.last_request=time.monotonic()
            response=self.http.get(BASE+'/'+endpoint,params=params)
            if response.status_code in {429,500,502,503,504} and attempt<2:
                retry=response.headers.get('Retry-After','')
                time.sleep(min(float(retry) if retry.isdigit() else 2**(attempt+1),30)); continue
            if response.status_code in {401,403}: raise ValueError('OpenF1 access unavailable; no paid/live access is configured')
            response.raise_for_status(); rows=response.json()
            if not isinstance(rows,list) or not all(isinstance(r,dict) for r in rows): raise ValueError('Invalid OpenF1 response schema')
            if rows:
                saved={'source':str(response.url),'observed_at':datetime.now(timezone.utc).isoformat(),'records':rows}
                temporary=path.with_suffix('.tmp'); temporary.write_text(json.dumps(saved),encoding='utf-8'); temporary.replace(path)
            return rows
        raise ValueError('OpenF1 is temporarily unavailable')


def filtered_summary(raw, stage, session, datasets, now):
    """Conservative observed laps; no fabricated FastF1 accuracy flags."""
    key=int(session['session_key']); meeting=int(session['meeting_key'])
    for records in datasets.values():
        if any(int(r.get('session_key',-1))!=key or int(r.get('meeting_key',-1))!=meeting for r in records):
            raise ValueError('OpenF1 records belong to another session or meeting')
    controls=sorted(datasets['race_control'],key=lambda r:r.get('date',''))
    green=[stamp(r['date']) for r in controls if r.get('flag')=='GREEN' and r.get('scope')=='Track']
    if not green: raise ValueError('No published green-track status for this session')
    deleted={}; flags=[]
    for item in controls:
        message=item.get('message','')
        match=re.search(r'CAR\s+(\d+).*?TIME\s+(\d+):(\d+\.\d+)\s+(DELETED|REINSTATED)',message)
        if match:
            number,minutes,seconds,action=match.groups()
            deleted[(int(number),round(int(minutes)*60+float(seconds),3))]=action=='DELETED'
        if item.get('category')=='Flag' and item.get('scope') in {'Track','Sector'}:
            flags.append((stamp(item['date']),(item.get('scope'),item.get('sector')),item.get('flag')))

    def green_lap(start,end):
        if start<min(green): return False
        active={}
        for when,scope,flag in flags:
            if when>end: break
            if when>start and any(active.values()): return False
            if scope[0]=='Track' and flag=='GREEN': active.clear()
            else: active[scope]=flag not in {'GREEN','CLEAR','CHEQUERED',None}
            if when>=start and any(active.values()): return False
        return not any(active.values())

    results={int(r['driver_number']):r for r in datasets['session_result']}
    if not results: raise ValueError('Published OpenF1 practice result is not available yet')
    pit={(int(r['driver_number']),int(r['lap_number'])) for r in datasets['pit'] if r.get('lap_number') is not None}
    drivers={int(d['driver_number']):d for d in datasets['drivers']}
    laps=[]; seen=set()
    for lap in datasets['laps']:
        number=int(lap['driver_number']); lap_number=int(lap['lap_number'])
        identity=(number,lap_number)
        if identity in seen: raise ValueError('Duplicate OpenF1 lap identity')
        seen.add(identity)
        duration=lap.get('lap_duration'); sectors=[lap.get('duration_sector_'+str(i)) for i in (1,2,3)]
        if not isinstance(duration,(int,float)) or not math.isfinite(duration) or not 30<=duration<=600: continue
        if lap.get('is_pit_out_lap') is not False or identity in pit or deleted.get((number,round(duration,3)),False): continue
        if any(not isinstance(s,(int,float)) or not math.isfinite(s) or s<=0 for s in sectors) or abs(sum(sectors)-duration)>.005: continue
        segments=[v for i in (1,2,3) for v in lap.get('segments_sector_'+str(i),[]) or []]
        # Mini-sector colors describe timing performance; race-control flags
        # determine track safety status. 2048 is not evidence of a yellow flag.
        if any(v not in {2048,2049,2051} for v in segments): continue
        if not lap.get('date_start') or number not in drivers: continue
        start=stamp(lap['date_start']); end=start+timedelta(seconds=duration)
        if start<stamp(session['date_start']) or end>min(now,stamp(session['date_end'])+timedelta(minutes=10)): continue
        if not green_lap(start,end): continue
        official=results.get(number,{}).get('duration')
        if not isinstance(official,(int,float)) or duration<official-.005: continue
        stints=[s for s in datasets['stints'] if int(s['driver_number'])==number and s.get('lap_start') is not None
            and s.get('lap_end') is not None and s['lap_start']<=lap_number<=s['lap_end']]
        if len(stints)>1: raise ValueError('Ambiguous OpenF1 stint assignment')
        stint=stints[0] if stints else {}
        if stint and lap_number==stint['lap_end']: continue  # conservatively exclude possible in-laps
        age=stint.get('tyre_age_at_start')
        laps.append({'Driver':drivers[number]['name_acronym'],'LapTime':pd.to_timedelta(float(duration),unit='s'),
            'LapNumber':lap_number,'Stint':stint.get('stint_number'),'Compound':stint.get('compound'),
            'TyreLife':float(age)+lap_number-stint['lap_start']+1 if isinstance(age,(int,float)) else float('nan')})
    if not laps: raise ValueError('OpenF1 has not published sufficient verified practice laps')
    metadata=pd.DataFrame([{'DriverId':d['name_acronym'],'Abbreviation':d['name_acronym'],
        'FullName':(d.get('first_name','')+' '+d.get('last_name','')).strip() or d['full_name'],
        'TeamName':d['team_name'],'TeamColor':d.get('team_colour') or '888888'} for d in drivers.values()])
    rows=summarize(pd.DataFrame(laps),metadata)
    if sum(r['best_lap_ms'] is not None for r in rows)<2: raise ValueError('Insufficient OpenF1 timing coverage')
    by_code={d['name_acronym']:number for number,d in drivers.items()}
    for row in rows:
        official=results.get(by_code[row['abbreviation']],{}).get('duration')
        # A strict filter may remove a driver's fastest lap. Never display a
        # cooldown as their session best when the published classification exists.
        row['best_lap_ms']=int(round(official*1000)) if isinstance(official,(int,float)) and math.isfinite(official) and official>0 else None
        row['quality']='OpenF1 published best / filtered aggregates' if row['lap_count']>=5 else 'published best / small filtered sample'
    best=min(r['best_lap_ms'] for r in rows if r['best_lap_ms'] is not None)
    for row in rows: row['gap_ms']=row['best_lap_ms']-best if row['best_lap_ms'] is not None else None
    rows.sort(key=lambda r:r['best_lap_ms'] if r['best_lap_ms'] is not None else float('inf'))
    return {'race_id':f"{raw['season']}-{int(raw['round']):02d}",'type':stage,'status':'published','source':'OpenF1',
        'session_key':key,'meeting_key':meeting,'started_at':session['date_start'],'ended_at':session['date_end'],
        'observed_at':now.isoformat(),'summary_version':'practice-stats-v1','quality_policy':'published-best-v2','drivers':rows,
        'notice':'Free post-session OpenF1 fallback. Best laps come from the published classification; counts, medians and tyre aggregates use filtered laps excluding pit, deleted, non-green and inconsistent-sector timing. FastF1 accuracy flags are unavailable; source-switch calibration has not been independently validated.'}


def load_practice(raw, stage, client=None, now=None):
    provided_now=now
    now=now or datetime.now(timezone.utc); client=client or Client()
    try:
        sessions=client.get('sessions',{'year':int(raw['season'])},ttl=300)
        session=match_session(sessions,raw,stage,now)
        datasets={name:client.get(name,{'session_key':session['session_key']},ttl=300)
            for name in ['drivers','laps','stints','pit','race_control','session_result']}
        return filtered_summary(raw,stage,session,datasets,provided_now or datetime.now(timezone.utc))
    finally:
        if hasattr(client,'http'): client.http.close()
