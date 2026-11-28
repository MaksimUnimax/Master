#!/usr/bin/env python3
"""Private, consistent migration/live copies; production is opened read-only.

No production records or key bytes are printed. Reports contain counts,
digests and boolean comparisons. Every copied database/key stays under a
0700 candidate/private* directory and must be excluded from deliverables.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from platform_core.identity import IdentityStore
from platform_core import podmasterye_domain as domain
from platform_core.podmasterye_market_links import Store

def quoted(name):return '"'+name.replace('"','""')+'"'

def signature(db,table,columns):
    rows=[]
    for row in db.execute('SELECT '+','.join(map(quoted,columns))+' FROM '+quoted(table)):
        values=[{'blob_sha256':hashlib.sha256(v).hexdigest(),'bytes':len(v)} if isinstance(v,bytes) else v for v in row]
        rows.append(json.dumps(values,sort_keys=True,ensure_ascii=False,separators=(',',':')))
    digest=hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest()
    return {'count':len(rows),'sha256':digest}

def backup(source,destination):
    if destination.exists():raise RuntimeError('Private destination already exists; refusing replacement')
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(destination) as dest:
        src.backup(dest)
    destination.chmod(0o600)

def integrity(path):
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        return {'integrity_ok':db.execute('PRAGMA integrity_check').fetchall()==[('ok',)],'foreign_key_errors':len(db.execute('PRAGMA foreign_key_check').fetchall())}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production-state',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    args=parser.parse_args();os.umask(0o077)
    source=args.production_state.resolve();candidate=args.candidate.resolve()
    if '/opt/podmasterye/candidates/' not in str(candidate) or source==candidate or not source.is_file():raise RuntimeError('Unexpected copy paths')
    private=candidate/'private-baseline';live=candidate/'private-live';proof=candidate/'evidence'
    for directory in (private,live):directory.mkdir(mode=0o700,parents=True,exist_ok=False)
    proof.mkdir(parents=True,exist_ok=True)
    before=private/'production-baseline.sqlite3';migrated=private/'migrated.sqlite3';restored=private/'rollback-restored.sqlite3'
    key=source.parent/'market-connections.key'
    if not key.is_file() or key.is_symlink():raise RuntimeError('Encryption key is unavailable')
    started=time.time();backup(source,before);backup(before,migrated)
    with sqlite3.connect(before.as_uri()+'?mode=ro',uri=True) as db:
        schema={name:[r[1] for r in db.execute('PRAGMA table_info('+quoted(name)+')')] for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        original={name:signature(db,name,cols) for name,cols in schema.items()}
        providers=dict(db.execute('SELECT provider,count(*) FROM pm_market_connections GROUP BY provider'))
    with IdentityStore(migrated) as identity:domain.init(identity)
    with sqlite3.connect(migrated.as_uri()+'?mode=ro',uri=True) as db:
        after={name:signature(db,name,cols) for name,cols in schema.items()}
    unchanged={name:original[name]==after[name] for name in original}
    backup(before,restored)
    with sqlite3.connect(restored.as_uri()+'?mode=ro',uri=True) as db:
        rollback=all(signature(db,name,cols)==original[name] for name,cols in schema.items())
    backup(migrated,live/'state.sqlite3')
    shutil.copyfile(key,live/'market-connections.key');(live/'market-connections.key').chmod(0o600)
    preserved_key=hashlib.sha256(key.read_bytes()).digest()==hashlib.sha256((live/'market-connections.key').read_bytes()).digest()
    decrypted=0
    with IdentityStore(live/'state.sqlite3') as identity:
        store=Store(identity,live)
        for cid,w,p,e in identity._db.execute('SELECT id,workspace,provider,encrypted FROM pm_market_connections'):
            fields=store.unpack(w,cid,p,e)
            if not isinstance(fields,dict) or not fields:raise RuntimeError('Copied key cannot be decrypted')
            decrypted+=1
    report={'schema':'market-preservation/v1','created_at':time.time(),'elapsed_seconds':time.time()-started,
            'production_open_mode':'read-only','snapshot_method':'SQLite backup API','private_data_excluded_from_delivery':True,
            'tables':{name:{'before':original[name],'after':after[name],'unchanged':unchanged[name]} for name in original},
            'all_original_tables_preserved':all(unchanged.values()),'keys_byte_identical':preserved_key,
            'encrypted_connections_decryptable':decrypted,'connections_by_provider':providers,'rollback_matches_baseline':rollback,
            'baseline':integrity(before),'migrated':integrity(migrated),'rollback':integrity(restored),'live_copy':integrity(live/'state.sqlite3')}
    (proof/'data-preservation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='tables'},ensure_ascii=False))
    if not all(unchanged.values()) or not preserved_key or not rollback or not all(report[k]['integrity_ok'] and report[k]['foreign_key_errors']==0 for k in ('baseline','migrated','rollback','live_copy')):raise SystemExit(2)

if __name__=='__main__':main()
