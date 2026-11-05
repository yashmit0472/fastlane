"""Cache free fixed-lead JMA forecasts. Never replace them with race-day reanalysis."""
import argparse
import csv
import hashlib
import io
import json
import math
import time
import zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
import httpx
from ml.features.build import race_start

ROOT=Path(__file__).resolve().parents[2]
FOLDER=ROOT/'data/raw/race-conditions'
ENDPOINT='https://previous-runs-api.open-meteo.com/v1/forecast'
VARIABLES={'temperature_2m':'temperature_c','precipitation':'precipitation_mm','wind_speed_10m':'wind_kmh','relative_humidity_2m':'humidity_pct'}
SCHEMA='jma-fixed-lead-v1'


def parse(payload,race,retrieved_at):
    target=race_start(race); hours=payload.get('hourly',{}); dates=[datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in hours.get('time',[])]
    if not dates: raise ValueError('Weather hours missing')
    # Use the last complete forecast hour at/before lights out; no later model run.
    eligible=[i for i,t in enumerate(dates) if timedelta(0)<=target-t<timedelta(hours=1)]
    if not eligible: raise ValueError('Forecast does not cover race start')
    i=eligible[-1]; values={name:hours.get(key+'_previous_day3',[None]*len(dates))[i] for key,name in VARIABLES.items()}
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in values.values()): raise ValueError('Archived forecast contains missing variables')
    if not -80<=values['temperature_c']<=65 or not 0<=values['humidity_pct']<=100 or min(values['precipitation_mm'],values['wind_kmh'])<0: raise ValueError('Invalid weather units/ranges')
    return {'schema':SCHEMA,'race_id':f"{race['season']}-{int(race['round']):02d}",'source':'Open-Meteo JMA GSM previous runs',
        'model':'jma_gsm','lead_days':3,'valid_for':dates[i].isoformat(),'retrieved_at':retrieved_at.isoformat(),
        'available_at':(dates[i]-timedelta(days=3)+timedelta(hours=6)).isoformat(),
        'availability_policy':'Estimated fixed 72h lead + conservative 6h release allowance; original publication receipt not archived.',
        'latitude':float(race['Circuit']['Location']['lat']),'longitude':float(race['Circuit']['Location']['long']),**values}


def fetch(race):
    FOLDER.mkdir(parents=True,exist_ok=True); rid=f"{race['season']}-{int(race['round']):02d}"; path=FOLDER/(rid+'.json')
    if path.exists():
        saved=json.loads(path.read_text())
        if saved['forecast']['race_id']==rid and saved['forecast']['schema']==SCHEMA: return saved['forecast']
    location=race['Circuit']['Location']; date=race['date']
    params={'latitude':location['lat'],'longitude':location['long'],'models':'jma_gsm','start_date':date,'end_date':date,
        'hourly':','.join(v+'_previous_day3' for v in VARIABLES),'timezone':'UTC','wind_speed_unit':'kmh','temperature_unit':'celsius','precipitation_unit':'mm'}
    with httpx.Client(timeout=40) as client:
        for attempt in range(3):
            response=client.get(ENDPOINT,params=params)
            if response.status_code not in {429,500,502,503,504}: break
            time.sleep(2**(attempt+1))
    response.raise_for_status(); now=datetime.now(timezone.utc); forecast=parse(response.json(),race,now)
    saved={'forecast':forecast,'source_url':str(response.url),'response_sha256':hashlib.sha256(response.content).hexdigest(),'response':response.json()}
    tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(saved),encoding='utf-8'); tmp.replace(path)
    return forecast


def live(race,cutoff):
    if cutoff>=race_start(race): return None
    forecast=fetch(race)
    if datetime.fromisoformat(forecast['available_at'])>cutoff: return None
    # Live availability is the actual first successful retrieval, not the estimated historical release.
    if datetime.fromisoformat(forecast['retrieved_at'])>cutoff: return None
    return {**forecast,'available_at':forecast['retrieved_at'],'availability_policy':'Actually retrieved before this live prediction cutoff'}


def load_status_map(source):
    with zipfile.ZipFile(source) as archive:
        names=[n for n in archive.namelist() if n.rsplit('/',1)[-1]=='status.csv']
        if len(names)!=1: raise ValueError('Unique status.csv required')
        rows=list(csv.DictReader(io.StringIO(archive.read(names[0]).decode('utf-8-sig'))))
    mapping={str(r['statusId']):r['status'] for r in rows}
    FOLDER.mkdir(parents=True,exist_ok=True); (FOLDER/'status-map.json').write_text(json.dumps(mapping,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--limit',type=int); p.add_argument('--status-archive',type=Path); args=p.parse_args()
    if args.status_archive: load_status_map(args.status_archive)
    races=json.loads((ROOT/'data/processed/kaggle-2018-2025/history.json').read_text())['races']
    races=[r for r in races if 2018<=int(r['season'])<=2025 and not r.get('Sprint') and not r.get('SprintResults')]
    if args.limit: races=races[:args.limit]
    rows=[]
    for n,race in enumerate(races,1):
        rid=f"{race['season']}-{int(race['round']):02d}"
        try: forecast=fetch(race); row={'race_id':rid,'status':'available','available_at':forecast['available_at']}
        except Exception as exc: row={'race_id':rid,'status':'unavailable','reason':str(exc)}
        rows.append(row); print(n,len(races),rid,row['status'],flush=True); time.sleep(.55)
    (FOLDER/'coverage.json').write_text(json.dumps({'schema':SCHEMA,'source':ENDPOINT,'races':rows},indent=2))


if __name__=='__main__': main()
