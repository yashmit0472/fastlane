"""As-of forecast and prior-result conditions, shared by training and inference."""
import json
import math
import re
from datetime import datetime
import pandas as pd
from ml.features.build import race_start,NUMERIC
from ml.features.practice import numeric
from ml.ingestion.condition_forecasts import ROOT,FOLDER,SCHEMA

FEATURE_VERSION='weather-reliability-v1'
WEATHER=['forecast_temperature_c','forecast_precipitation_mm','forecast_wind_kmh','forecast_humidity_pct']
RELIABILITY=['driver_nonfinish_rate','team_nonfinish_rate','circuit_nonfinish_rate','driver_status_samples','circuit_status_samples']
INTERACTIONS=['rain_x_recent_finish','rain_x_recent_wins','rain_x_team_form','wind_x_recent_finish','temperature_x_recent_finish','rain_x_nonfinish_rate','rain_x_session_gap']


def columns(stage,weather=True):
    base=NUMERIC if stage=='Q' else numeric(stage)
    return base+RELIABILITY+(WEATHER+INTERACTIONS if weather else [])


def nonfinish(result,status_map):
    status=result.get('status') or status_map.get(str(result.get('status_id')))
    if not status: return None
    return 0 if status=='Finished' or re.fullmatch(r'\+\d+ Laps?',status) else 1


def reliability(race,history,driver,team,cutoff,status_map):
    past=sorted([r for r in history if race_start(r)<min(cutoff,race_start(race))],key=race_start)
    drivers=[r for e in past for r in e.get('Results',[]) if r['Driver']['driverId']==driver][-10:]
    teams=[r for e in past[-5:] for r in e.get('Results',[]) if r['Constructor']['constructorId']==team]
    circuits=[r for e in [e for e in past if e['Circuit']['circuitId']==race['Circuit']['circuitId']][-10:] for r in e.get('Results',[])]
    def stat(rows):
        known=[s for r in rows if (s:=nonfinish(r,status_map)) is not None]
        return (sum(known)+1)/(len(known)+5),len(known)
    d,n=stat(drivers); t,_=stat(teams); c,m=stat(circuits)
    return {'driver_nonfinish_rate':d,'team_nonfinish_rate':t,'circuit_nonfinish_rate':c,'driver_status_samples':n,'circuit_status_samples':m}


def enrich(frame,race,history,forecast,cutoff,status_map=None):
    if forecast.get('schema')!=SCHEMA or forecast.get('model')!='jma_gsm' or forecast.get('lead_days')!=3: raise ValueError('Incompatible forecast provenance')
    if forecast['race_id']!=f"{race['season']}-{int(race['round']):02d}": raise ValueError('Forecast race mismatch')
    at=datetime.fromisoformat(forecast['available_at'].replace('Z','+00:00')); valid=datetime.fromisoformat(forecast['valid_for'].replace('Z','+00:00'))
    if at.tzinfo is None or valid.tzinfo is None or not at<=cutoff<race_start(race): raise ValueError('Weather unavailable at prediction cutoff')
    if not 0<=(race_start(race)-valid).total_seconds()<3600: raise ValueError('Wrong forecast valid time')
    location=race['Circuit']['Location']
    if abs(float(location['lat'])-forecast['latitude'])>.001 or abs(float(location['long'])-forecast['longitude'])>.001: raise ValueError('Forecast circuit coordinate mismatch')
    for key in ['temperature_c','precipitation_mm','wind_kmh','humidity_pct']:
        if not isinstance(forecast.get(key),(int,float)) or not math.isfinite(forecast[key]): raise ValueError('Incomplete forecast values')
    if status_map is None: status_map=json.loads((FOLDER/'status-map.json').read_text())
    out=frame.copy()
    rel=[reliability(race,history,r.driver_id,r.constructor_id,cutoff,status_map) for r in frame.itertuples()]
    for col in RELIABILITY: out[col]=[r[col] for r in rel]
    for source,target in [('temperature_c',WEATHER[0]),('precipitation_mm',WEATHER[1]),('wind_kmh',WEATHER[2]),('humidity_pct',WEATHER[3])]: out[target]=forecast[source]
    rain=min(forecast['precipitation_mm'],20)/5; wind=min(forecast['wind_kmh'],100)/25; temp=(forecast['temperature_c']-20)/20
    out['rain_x_recent_finish']=rain*out.recent_finish; out['rain_x_recent_wins']=rain*out.recent_win_rate
    out['rain_x_team_form']=rain*out.team_recent_finish; out['wind_x_recent_finish']=wind*out.recent_finish
    out['temperature_x_recent_finish']=temp*out.recent_finish; out['rain_x_nonfinish_rate']=rain*out.driver_nonfinish_rate
    stage=frame.stage.iloc[0] if 'stage' in frame else 'Q'
    out['rain_x_session_gap']=rain*out['qualifying_gap_s' if stage=='Q' else stage.lower()+'_best_gap_pct']
    out['conditions_feature_version']=FEATURE_VERSION
    return out


def build(stage,history):
    source=ROOT/('data/processed/qualifying-v2/features.csv' if stage=='Q' else f'data/processed/practice-2018-2025/{stage.lower()}-features.csv')
    frame=pd.read_csv(source); lookup={f"{r['season']}-{int(r['round']):02d}":r for r in history}; rows=[]; coverage=[]
    for rid,group in frame.groupby('race_id',sort=False):
        path=FOLDER/(rid+'.json')
        try:
            if not path.exists(): raise ValueError('No complete archived forecast')
            forecast=json.loads(path.read_text())['forecast']; cutoff=datetime.fromisoformat(group.cutoff.iloc[0].replace('Z','+00:00'))
            rows.append(enrich(group,lookup[rid],history,forecast,cutoff)); coverage.append({'race_id':rid,'status':'included'})
        except (ValueError,KeyError) as exc: coverage.append({'race_id':rid,'status':'excluded','reason':str(exc)})
    if not rows: raise ValueError('No usable conditions data')
    result=pd.concat(rows,ignore_index=True); folder=ROOT/'data/processed/conditions'; folder.mkdir(parents=True,exist_ok=True)
    path=folder/(stage.lower()+'-features.csv'); result.to_csv(path,index=False)
    (folder/(stage.lower()+'-coverage.json')).write_text(json.dumps(coverage,indent=2))
    return result,path
