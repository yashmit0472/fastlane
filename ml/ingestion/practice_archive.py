"""Download pinned FastF1-derived practice JSON from TracingInsights; never execute it."""
import argparse
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import httpx

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_HISTORY=ROOT/'data/processed/kaggle-2018-2025/history.json'
DEFAULT_OUTPUT=ROOT/'data/raw/practice-archive'
STAGES={'FP1':'FirstPractice','FP2':'SecondPractice','FP3':'ThirdPractice'}


class Downloader:
    def __init__(self):
        self.client=httpx.Client(timeout=60,follow_redirects=True,headers={'User-Agent':'FASTLANE educational practice-model dataset'})
        self.lock=threading.Lock(); self.next_request=0

    def get(self,url):
        for attempt in range(4):
            with self.lock:
                time.sleep(max(0,self.next_request-time.monotonic()))
                self.next_request=time.monotonic()+.5
            try:
                response=self.client.get(url)
                if response.status_code in {429,500,502,503,504}:
                    delay=response.headers.get('Retry-After','')
                    time.sleep(min(float(delay) if delay.isdigit() else 2**(attempt+1),60)); continue
                response.raise_for_status()
                return response
            except httpx.TransportError:
                if attempt==3: raise
                time.sleep(2**attempt)
        raise RuntimeError(f'Source unavailable after retries: {url}')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history',type=Path,default=DEFAULT_HISTORY)
    parser.add_argument('--output-dir',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--seasons',nargs='+',type=int,default=list(range(2018,2026)))
    parser.add_argument('--limit',type=int)
    args=parser.parse_args(); args.output_dir.mkdir(parents=True,exist_ok=True)
    races=json.loads(args.history.read_text(encoding='utf-8'))['races']
    manifest_path=args.output_dir/'manifest.json'
    manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {'source':'TracingInsights FastF1-derived archive','repositories':{},'files':{}}
    downloader=Downloader()
    for year in args.seasons:
        if str(year) in manifest['repositories']: continue
        url=f'https://api.github.com/repos/TracingInsights/{year}/commits/main'
        commit=downloader.get(url).json()['sha']
        license_url=f'https://raw.githubusercontent.com/TracingInsights/{year}/{commit}/LICENSE'
        license_text=downloader.get(license_url).text
        (args.output_dir/f'LICENSE-{year}.txt').write_text(license_text,encoding='utf-8')
        manifest['repositories'][str(year)]={'commit':commit,'url':f'https://github.com/TracingInsights/{year}',
            'license_url':license_url,'license_sha256':hashlib.sha256(license_text.encode()).hexdigest()}
    tasks=[]
    for race in races:
        if int(race['season']) not in args.seasons or race.get('Sprint') or race.get('SprintResults'): continue
        for stage,field in STAGES.items():
            tasks.append((race,stage))
    if args.limit: tasks=tasks[:args.limit]
    def fetch(task):
        race,stage=task; year=str(race['season']); key=f"{year}-{int(race['round']):02d}-{stage}"
        commit=manifest['repositories'][year]['commit']
        path=quote(f"{race['raceName']}/Practice {stage[-1]}/session_laptimes.json",safe='/')
        url=f'https://raw.githubusercontent.com/TracingInsights/{year}/{commit}/{path}'
        target=args.output_dir/(key+'.json')
        try:
            if target.exists():
                content=target.read_bytes()
            else:
                content=downloader.get(url).content
                data=json.loads(content)
                if not isinstance(data,dict) or not isinstance(data.get('time'),list) or not data.get('drv'):
                    raise ValueError('Expected lap-wise JSON arrays')
                temporary=target.with_suffix('.tmp'); temporary.write_bytes(content); temporary.replace(target)
            return key,{'status':'downloaded','url':url,'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}
        except Exception as exc:
            return key,{'status':'unavailable','url':url,'error':str(exc)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for index,(key,status) in enumerate(pool.map(fetch,tasks),1):
            manifest['files'][key]=status
            manifest['updated_at']=datetime.now(timezone.utc).isoformat()
            temporary=manifest_path.with_suffix('.tmp'); temporary.write_text(json.dumps(manifest,indent=2),encoding='utf-8'); temporary.replace(manifest_path)
            print(f"{index}/{len(tasks)} {key}: {status['status']}",flush=True)
    print(json.dumps({'requested':len(tasks),'downloaded':sum(v['status']=='downloaded' for v in manifest['files'].values()),'manifest':str(manifest_path)},indent=2))


if __name__=='__main__': main()
