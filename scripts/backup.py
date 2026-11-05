"""Consistent application backup with integrity manifest; never overwrites a live store."""
import argparse
import hashlib
import json
import os
import sqlite3
import zipfile
from datetime import datetime,timezone
from pathlib import Path
from sqlalchemy import create_engine,select,func
from sqlalchemy.pool import NullPool
from apps.api.database import Base,engine as default_engine,ROOT

TABLES=['races','snapshots','system_state']


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def backup(output,engine=default_engine,include_models=True):
    output=Path(output).resolve(); output.mkdir(parents=True,exist_ok=False)
    snapshot_engine=engine; sqlite_copy=None
    if engine.dialect.name=='sqlite':
        source=engine.url.database
        if not source or source==':memory:': raise ValueError('A file-backed SQLite database is required')
        sqlite_copy=output/'serving.db'
        with sqlite3.connect(source) as live,sqlite3.connect(sqlite_copy) as saved:
            live.backup(saved)
            if saved.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('SQLite backup integrity failed')
        snapshot_engine=create_engine('sqlite:///'+sqlite_copy.as_posix())
    dump=output/'serving.jsonl'; counts={}
    with snapshot_engine.connect() as connection:
        if engine.dialect.name=='postgresql': connection=connection.execution_options(isolation_level='REPEATABLE READ')
        with connection.begin(),dump.open('w',encoding='utf-8') as stream:
            for name in TABLES:
                table=Base.metadata.tables[name]; count=0
                for row in connection.execute(select(table)).mappings():
                    stream.write(json.dumps({'table':name,'row':dict(row)},ensure_ascii=False)+'\n'); count+=1
                counts[name]=count
    if sqlite_copy: snapshot_engine.dispose()
    files=[dump]+([sqlite_copy] if sqlite_copy else [])
    if include_models:
        archive=output/'model-and-history.zip'
        sources=[]
        for folder in [ROOT/'ml/artifacts',ROOT/'docs',ROOT/'data/processed',ROOT/'data/raw/entries',ROOT/'data/raw/weather-forecasts',ROOT/'data/raw/race-conditions',ROOT/'data/raw/live']:
            if folder.exists(): sources.extend(p for p in folder.rglob('*') if p.is_file() and p.suffix in {'.json','.csv','.cbm','.pkl','.md','.pdf','.txt'})
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for path in sources: z.write(path,path.relative_to(ROOT).as_posix())
        files.append(archive)
    manifest={'schema':'fastlane-backup-v1','created_at':datetime.now(timezone.utc).isoformat(),'database':engine.dialect.name,'rows':counts,'files':{p.name:sha(p) for p in files}}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    verify(output); return manifest


def verify(folder):
    folder=Path(folder).resolve(); manifest=json.loads((folder/'manifest.json').read_text())
    if manifest.get('schema')!='fastlane-backup-v1': raise ValueError('Unknown backup schema')
    for name,expected in manifest['files'].items():
        path=(folder/name).resolve()
        if not path.is_relative_to(folder) or sha(path)!=expected: raise ValueError('Backup file integrity mismatch')
        if path.suffix=='.zip':
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None: raise ValueError('Backup archive CRC failed')
    return manifest


def restore(folder,database_url):
    manifest=verify(folder); target=create_engine(database_url,poolclass=NullPool)
    Base.metadata.create_all(target)
    with target.begin() as connection:
        if any(connection.scalar(select(func.count()).select_from(Base.metadata.tables[t])) for t in TABLES): raise ValueError('Restore target must be empty; existing data will not be overwritten')
        counts={t:0 for t in TABLES}
        with (Path(folder)/'serving.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                item=json.loads(line); table=Base.metadata.tables[item['table']]
                if item['table'] not in TABLES: raise ValueError('Unexpected backup table')
                connection.execute(table.insert().values(**item['row'])); counts[item['table']]+=1
        if counts!=manifest['rows']: raise ValueError('Backup row counts differ')
        if target.dialect.name=='postgresql':
            from sqlalchemy import text
            connection.execute(text("SELECT setval(pg_get_serial_sequence('snapshots','id'), COALESCE((SELECT MAX(id) FROM snapshots),1), EXISTS(SELECT 1 FROM snapshots))"))
    target.dispose(); return counts


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--output',type=Path); p.add_argument('--verify',type=Path); p.add_argument('--restore',type=Path); p.add_argument('--database-url'); a=p.parse_args()
    if a.restore:
        if not a.database_url: p.error('Restore requires an explicit --database-url pointing to an empty database')
        print(json.dumps(restore(a.restore,a.database_url)))
    elif a.verify: print(json.dumps(verify(a.verify),indent=2))
    else:
        folder=a.output or ROOT/'data/backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
        print(json.dumps(backup(folder),indent=2))


if __name__=='__main__': main()
