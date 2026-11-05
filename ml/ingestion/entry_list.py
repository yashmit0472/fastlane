"""Import a reviewed FIA main entry table; reserves remain separate."""
import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.parse import urljoin
from html.parser import HTMLParser
import io
import httpx
from ml.ingestion.jolpica import ROOT


def normalized(value):
    return re.sub('[^a-z0-9]','',unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().lower())


def parse_entries(text,raw,reference):
    if f"{raw['season']} {raw['raceName'].upper()}" not in ' '.join(text.upper().split()): raise ValueError('FIA document event identity does not match')
    main=text.split('In addition to the list of cars and drivers')[0]
    parsed=re.findall(r'^\s*(\d{1,3})\s+([A-Z]{3})\s+(.+?)\s+([A-Z]{3})\s+(.+)$',main,re.M)
    by_code={e['abbreviation']:e for e in reference}; entries=[]; conflicts=[]
    for number,code,name,_,team in parsed:
        if code not in by_code: raise ValueError('Unknown entrant identity requires mapping: '+code)
        entry=by_code[code].copy()
        if not normalized(entry['name']).endswith(normalized(name)) and normalized(name) not in normalized(entry['name']): raise ValueError('Entry name and identifier disagree: '+code)
        aliases={'red_bull':'redbull','rb':'racingbulls','racing_bulls':'racingbulls','aston_martin':'astonmartin'}
        team_token=aliases.get(entry['constructor_id'],normalized(entry['team']).replace('f1team',''))
        if not team_token or team_token not in normalized(team): raise ValueError('Constructor mapping needs review: '+code)
        if int(number)!=entry['number']: conflicts.append(f"{code}: FIA table number {number}, timing metadata number {entry['number']}; timing number retained, identity matched by code and name.")
        entry['document_number']=int(number); entry['document_team']=team; entries.append(entry)
    if len(entries)!=len(reference) or len({e['driver_id'] for e in entries})!=len(entries): raise ValueError('FIA main table does not cover the reference field uniquely')
    return entries,conflicts


def candidate_documents(html,raw):
    class Links(HTMLParser):
        def __init__(self): super().__init__(); self.urls=[]
        def handle_starttag(self,tag,attrs):
            if tag=='a':
                href=dict(attrs).get('href',''); url=urljoin('https://www.fia.com',href)
                if urlparse(url).hostname in {'www.fia.com','fia.com'}: self.urls.append(url)
    parser=Links(); parser.feed(html)
    token=normalized(str(raw['season'])+raw['raceName'])
    return list(dict.fromkeys(u for u in parser.urls if '/decision-document/' in u and token in normalized(u) and 'entry_list' in u.lower() and urlparse(u).path.endswith('.pdf')))


def refresh_entries(raw,reference):
    """Discover actual FIA links; leave unverified / unavailable rosters provisional."""
    folder=ROOT/'data/raw/entries'; folder.mkdir(parents=True,exist_ok=True)
    path=folder/f"{raw['season']}-{int(raw['round']):02d}.json"
    now=datetime.now(timezone.utc)
    if path.exists() and (now-datetime.fromisoformat(json.loads(path.read_text())['available_at'])).total_seconds()<3600: return
    with httpx.Client(timeout=15,follow_redirects=True) as client:
        response=client.get('https://www.fia.com/documents/championship'); response.raise_for_status()
        candidates=candidate_documents(response.text,raw)
        if len(candidates)!=1: return
        response=client.get(candidates[0]); response.raise_for_status(); content=response.content
    if not content.startswith(b'%PDF') or len(content)>3_000_000: raise ValueError('Unexpected FIA document response')
    from pypdf import PdfReader
    text='\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)
    entries,conflicts=parse_entries(text,raw,reference)
    payload={'race_id':f"{raw['season']}-{int(raw['round']):02d}",'source_url':candidates[0],
        'available_at':datetime.now(timezone.utc).isoformat(),'source_sha256':hashlib.sha256(content).hexdigest(),
        'entries':entries,'metadata_conflicts':conflicts,'policy':'FIA main entries; FP1-only reserves excluded; unknown identities and constructor changes require review.'}
    (folder/(payload['race_id']+'-fia.pdf')).write_bytes(content)
    temporary=path.with_suffix('.tmp'); temporary.write_text(json.dumps(payload,indent=2),encoding='utf-8'); temporary.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--race-id',required=True); parser.add_argument('--text',type=Path,required=True)
    parser.add_argument('--pdf',type=Path,required=True); parser.add_argument('--source-url',required=True); args=parser.parse_args()
    if urlparse(args.source_url).hostname not in {'www.fia.com','fia.com'}: raise ValueError('A primary FIA source URL is required')
    season,round_number=args.race_id.split('-'); source=json.loads((ROOT/f'data/raw/live/{season}-source.json').read_text())
    raw=next(r for r in source['calendar'] if int(r['round'])==int(round_number))
    from ml.live.refresh import entries_from
    prior=sorted([r for r in source['results'] if int(r['round'])<int(round_number)],key=lambda r:int(r['round']))[-1]
    entries,conflicts=parse_entries(args.text.read_text(encoding='utf-8'),raw,entries_from(prior['Results']))
    result={'race_id':args.race_id,'source_url':args.source_url,'available_at':datetime.now(timezone.utc).isoformat(),
        'source_sha256':hashlib.sha256(args.pdf.read_bytes()).hexdigest(),'entries':entries,'metadata_conflicts':conflicts,
        'policy':'Reviewed FIA main event entries only; the separate FP1 reserve table is excluded. Availability is our actual retrieval/import time, not an inferred historical publication timestamp.'}
    path=ROOT/'data/raw/entries'/(args.race_id+'.json'); path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Imported',len(entries),'main entries;',len(conflicts),'numbering conflicts flagged;',path)


if __name__=='__main__': main()
