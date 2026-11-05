"""Capture a race-hour forecast when it is actually observed; context only."""
import json
import math
from datetime import datetime,timezone,timedelta
from pathlib import Path
import httpx
from ml.features.build import race_start

ROOT=Path(__file__).resolve().parents[2]


def parse_forecast(payload,raw,available_at):
    target=race_start(raw)
    if available_at>=target: raise ValueError('A race forecast must be captured before race start')
    hours=payload['hourly']; dates=[datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in hours['time']]
    index=min(range(len(dates)),key=lambda i:abs((dates[i]-target).total_seconds()))
    if abs((dates[index]-target).total_seconds())>3600: raise ValueError('Weather response does not cover race hour')
    values={name:hours[name][index] for name in ['temperature_2m','precipitation_probability','wind_speed_10m']}
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in values.values()) or not 0<=values['precipitation_probability']<=100:
        raise ValueError('Incomplete race-weather forecast')
    return {'source':'Open-Meteo','available_at':available_at.isoformat(),'valid_for':dates[index].isoformat(),
        'latitude':float(raw['Circuit']['Location']['lat']),'longitude':float(raw['Circuit']['Location']['long']),
        'temperature_c':values['temperature_2m'],'rain_probability_pct':values['precipitation_probability'],
        'wind_kmh':values['wind_speed_10m'],'used_by_model':False,
        'notice':'Race-hour weather forecast captured at the displayed time. Context only; historical issue-time weather training data is not yet validated.'}


def capture(raw):
    now=datetime.now(timezone.utc); target=race_start(raw)
    if not now<target<=now+timedelta(days=15): return None
    folder=ROOT/'data/raw/weather-forecasts'; folder.mkdir(parents=True,exist_ok=True)
    path=folder/f"{raw['season']}-{int(raw['round']):02d}-latest.json"
    if path.exists():
        saved=json.loads(path.read_text())
        if (now-datetime.fromisoformat(saved['available_at'])).total_seconds()<3600: return saved
    location=raw['Circuit']['Location']
    response=httpx.get('https://api.open-meteo.com/v1/forecast',params={'latitude':location['lat'],'longitude':location['long'],
        'hourly':'temperature_2m,precipitation_probability,wind_speed_10m','timezone':'UTC','forecast_days':16},timeout=20)
    response.raise_for_status(); payload=response.json()
    result=parse_forecast(payload,raw,datetime.now(timezone.utc))
    (folder/(result['available_at'].replace(':','')+'.json')).write_text(json.dumps({'forecast':result,'response':payload}),encoding='utf-8')
    temporary=path.with_suffix('.tmp'); temporary.write_text(json.dumps(result),encoding='utf-8'); temporary.replace(path)
    return result
