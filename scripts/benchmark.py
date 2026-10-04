"""Run real baseline measurements in a separate *_measure database."""
import argparse
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from app.config import DATABASE_URL, DEMO_PASSWORD


def percentiles(samples):
    if not samples: raise ValueError('No samples')
    ordered=sorted(samples)
    return {'p50':statistics.median(ordered),'p95':ordered[math.ceil(.95*len(ordered))-1],'max':ordered[-1]}


def run_series(operation,warmup,repeats,expected):
    if repeats<20: raise ValueError('At least 20 measured repetitions required')
    samples=[]
    for i in range(warmup+repeats):
        start=time.perf_counter()
        response=operation()
        elapsed=(time.perf_counter()-start)*1000
        if response.status_code!=expected:
            raise RuntimeError(f'Expected {expected}, received {response.status_code}: {response.text[:200]}')
        timing=response.headers.get('server-timing','')
        server=re.search(r'app;dur=([\d.]+)',timing)
        sql=re.search(r'sql;dur=([\d.]+)',timing)
        queries=re.search(r'queries;desc="(\d+)"',timing)
        if not (server and sql and queries): raise RuntimeError('Missing timing metrics')
        server_ms=float(server[1]); sql_ms=float(sql[1])
        if i>=warmup:
            samples.append({'http_ms':elapsed,'server_ms':server_ms,'sql_ms':sql_ms,
                            'code_ms':max(0,server_ms-sql_ms),'queries':int(queries[1]),'status':response.status_code})
    return {'samples':samples,**{key:percentiles([s[key] for s in samples]) for key in ('http_ms','server_ms','sql_ms','code_ms','queries')}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats',type=int,default=30)
    parser.add_argument('--warmup',type=int,default=5)
    args=parser.parse_args()
    if args.repeats<20 or args.warmup<1: parser.error('repeats>=20 and warmup>=1')
    info=conninfo_to_dict(DATABASE_URL)
    target=info['dbname']+'_measure'
    if not re.fullmatch(r'[a-z][a-z0-9_]*',target): raise RuntimeError('Invalid database name')
    admin=make_conninfo(DATABASE_URL,dbname='postgres')
    with psycopg.connect(admin,autocommit=True) as db:
        if not db.execute('SELECT 1 FROM pg_database WHERE datname=%s',(target,)).fetchone():
            db.execute(f'CREATE DATABASE {target}')
    os.environ['DATABASE_URL']=make_conninfo(DATABASE_URL,dbname=target)
    # Import after choosing the isolated database, including db's captured config.
    import app.config as config
    config.DATABASE_URL=os.environ['DATABASE_URL']
    import app.db as database
    database.DATABASE_URL=config.DATABASE_URL
    from scripts.seed import seed_dataset, dataset_fingerprint, counts
    database.initialize()
    result={'metadata':{'account':'demo','warmup':args.warmup,'repeats':args.repeats,'p95_method':'nearest rank',
                        'database':target,'python':platform.python_version(),'platform':platform.platform(),
                        'started_at':datetime.now(timezone(timedelta(hours=3))).isoformat(),
                        'sql_method':'Client execute + fetchall; includes transfer/decode, excludes opening connection and commit',
                        'server_method':'ASGI middleware wall time; code = server - SQL; HTTP includes full receive',
                        'pip_freeze':subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True).splitlines()},'datasets':{}}
    with database.connection() as db: result['metadata']['postgres']=db.execute('SELECT version() AS v').fetchone()['v']
    for size in ('small','work'):
        with database.connection() as db:
            original=seed_dataset(db,size,reset=True)
            fingerprint=dataset_fingerprint(db)
            second=seed_dataset(db,size,reset=True)
            reproduced=dataset_fingerprint(db)==fingerprint
            if original!=second or not reproduced: raise RuntimeError('Seed is not reproducible')
            base={'counts':original,'fingerprint':fingerprint,'reproduced':reproduced}
        env=dict(os.environ)
        server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8090','--no-access-log'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            with httpx.Client(base_url='http://127.0.0.1:8090',timeout=120) as client:
                for _ in range(200):
                    try:
                        if client.get('/health').status_code==200: break
                    except httpx.ConnectError: pass
                    time.sleep(.1)
                else: raise RuntimeError('Measurement server did not start')
                credentials={'username':'demo','password':DEMO_PASSWORD}
                def sign_in():
                    return client.post('/api/login',json=credentials)
                sign_in().raise_for_status()
                n=args.warmup+args.repeats
                with database.connection() as db:
                    # Isolated fixture slots only for writes, beyond generated schedule.
                    fixture_ids=[]
                    for i in range(2*n):
                        start=datetime(2027,6,1,9,tzinfo=timezone(timedelta(hours=3)))+timedelta(hours=i)
                        fixture_ids.append(db.execute('INSERT INTO slots(specialist_id,start_at,end_at) VALUES (1,%s,%s) RETURNING id',(start,start+timedelta(hours=1))).fetchone()['id'])
                cancellation_ids=[]
                for slot in fixture_ids[:n]:
                    response=client.post('/api/appointments',json={'slot_id':slot,'service_id':1,'client_name':'Подготовка отмены'})
                    response.raise_for_status(); cancellation_ids.append(response.json()['id'])
                operations={}
                def record(key,method,path,fn,expected=200):
                    print(f'{size}: {key}',flush=True)
                    operations[key]={'method':method,'path':path,'expected_status':expected,**run_series(fn,args.warmup,args.repeats,expected)}
                record('login','POST','/api/login',sign_in)
                def sign_out():
                    # Untimed setup uses a separate request but the HTTP timer includes setup if in operation.
                    return client.post('/api/logout')
                # Separate preparation from timed logout with a one-call wrapper measured below.
                logout_samples=[]
                for i in range(n):
                    sign_in().raise_for_status()
                    start=time.perf_counter(); response=sign_out(); elapsed=(time.perf_counter()-start)*1000
                    if response.status_code!=200: raise RuntimeError('Logout failed')
                    timing=response.headers['server-timing']
                    server_ms=float(re.search(r'app;dur=([\d.]+)',timing)[1]); sql_ms=float(re.search(r'sql;dur=([\d.]+)',timing)[1])
                    if i>=args.warmup: logout_samples.append({'http_ms':elapsed,'server_ms':server_ms,'sql_ms':sql_ms,'code_ms':max(0,server_ms-sql_ms),'queries':int(re.search(r'queries;desc="(\d+)"',timing)[1]),'status':200})
                operations['logout']={'method':'POST','path':'/api/logout','expected_status':200,'samples':logout_samples,**{key:percentiles([s[key] for s in logout_samples]) for key in ('http_ms','server_ms','sql_ms','code_ms','queries')}}
                sign_in().raise_for_status()
                for key,path in [('me','/api/me'),('services','/api/services'),('specialists','/api/specialists'),
                                 ('list','/api/appointments?page=1&size=20'),('card','/api/appointments/2'),
                                 ('slots','/api/slots?service_id=1&from_at=2026-10-01T00%3A00%3A00%2B03%3A00&to_at=2026-10-08T00%3A00%3A00%2B03%3A00&page=1&size=20'),
                                 ('summary','/api/summary')]:
                    record(key,'GET',path,lambda p=path:client.get(p))
                create_ids=iter(fixture_ids[n:])
                record('create','POST','/api/appointments',lambda:client.post('/api/appointments',json={'slot_id':next(create_ids),'service_id':1,'client_name':'Замер бронирования'}),201)
                cancel_ids=iter(cancellation_ids)
                record('cancel','POST','/api/appointments/{id}/cancel',lambda:client.post(f'/api/appointments/{next(cancel_ids)}/cancel'))
                with database.connection() as db: base['final_counts']=counts(db)
                base['write_fixture']={'added_slots':2*n,'prepared_appointments':n,'created_during_warmup':args.warmup,'created_during_series':args.repeats,'cancelled_during_warmup':args.warmup,'cancelled_during_series':args.repeats}
                base['operations']=operations; result['datasets'][size]=base
                Path('results').mkdir(exist_ok=True)
                Path('results/measurements.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        finally:
            server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired: server.kill();server.wait()
    print('Completed: results/measurements.json',flush=True)

if __name__=='__main__': main()
