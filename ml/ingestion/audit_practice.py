"""Cross-check practice archive times against the independently downloaded Kaggle table."""
import argparse
import csv
import io
import json
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from ml.features.practice import decode_archive
from ml.ingestion.practice_archive import DEFAULT_HISTORY,DEFAULT_OUTPUT

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kaggle',type=Path,required=True)
    args=parser.parse_args()
    history=json.loads(DEFAULT_HISTORY.read_text())['races']
    by_id={int(r['source_race_id']):r for r in history if int(r['season'])==2025}
    with zipfile.ZipFile(args.kaggle) as archive:
        def rows(name):
            path=next(n for n in archive.namelist() if Path(n).name==name)
            return list(csv.DictReader(io.StringIO(archive.read(path).decode('utf-8-sig'))))
        drivers={int(r['driverId']):r['driverRef'] for r in rows('drivers.csv')}
        practice=rows('practice_results.csv')
    summaries={}; differences=[]
    for row in practice:
        race=by_id.get(int(row['raceId']))
        if not race or row['session'] not in {'FP1','FP2','FP3'} or not row['bestLapTime']: continue
        key=f"2025-{int(race['round']):02d}-{row['session']}"
        path=DEFAULT_OUTPUT/(key+'.json')
        if not path.exists(): continue
        if key not in summaries:
            summaries[key]={d['driver_id']:d for d in decode_archive(json.loads(path.read_text()),race,row['session'])['drivers']}
        result=summaries[key].get(drivers.get(int(row['driverId'])))
        if not result or result['best_lap_ms'] is None: continue
        expected=pd.to_timedelta(row['bestLapTime']).total_seconds()*1000
        differences.append(abs(result['best_lap_ms']-expected))
    if len(differences)<100: raise ValueError('Insufficient overlap to independently cross-check units and identities')
    differences=np.array(differences)
    report={'comparison':'2025 FastF1-derived archive clean fastest laps vs downloaded Kaggle practice bestLapTime',
        'driver_session_pairs':len(differences),'sessions':len(summaries),'within_1ms_fraction':float((differences<=1.01).mean()),
        'within_1second_fraction':float((differences<=1000).mean()),'median_absolute_difference_ms':float(np.median(differences)),
        'notice':'Differences can reflect clean-lap filters, later timing corrections or source coverage. This does not prove historical publication availability.'}
    report['status']='passed' if report['within_1second_fraction']>=.8 else 'needs review'
    target=ROOT/'data/processed/practice-2018-2025/source-audit.json'
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    if report['status']!='passed': raise ValueError('Practice cross-source audit requires review')


if __name__=='__main__': main()
