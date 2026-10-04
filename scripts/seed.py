"""Deterministic datasets. Reset requires explicit --reset."""
import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from app.config import DEMO_PASSWORD
from app.db import connection, initialize

SIZES={'small':(10,10,500,300),'work':(200,30,200000,60000)}
BASE=datetime(2026,10,1,9,tzinfo=timezone(timedelta(hours=3)))
TABLES=('specialists','services','slots','appointments')


def counts(db):
    return {table:db.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n'] for table in TABLES}


def dataset_fingerprint(db):
    # Stable SQL representation and ordered identifiers; no random sessions/password salt.
    return {t:db.execute(f"SELECT md5(coalesce(string_agg(row_to_json(r)::text, E'\\n' ORDER BY id),'')) AS hash FROM {t} r").fetchone()['hash'] for t in TABLES}


def seed_dataset(db,size,reset=False):
    if size not in SIZES: raise ValueError('Expected small or work')
    if not reset and db.execute('SELECT count(*) AS n FROM users').fetchone()['n']:
        return counts(db)
    if reset: db.execute('TRUNCATE appointments,slots,specialists,services,sessions,users RESTART IDENTITY CASCADE')
    n_spec,n_services,n_slots,n_appointments=SIZES[size]
    # Fixed salt is only for deterministic demo fixtures, never for new user passwords.
    salt='6f7074696d697a6174696f6e2d647a3100'
    password_hash=salt+':'+hashlib.pbkdf2_hmac('sha256',DEMO_PASSWORD.encode(),bytes.fromhex(salt),120000).hex()
    db.execute('INSERT INTO users(username,password_hash) VALUES (%s,%s)',('demo',password_hash))
    services=[]
    labels=['Консультация','Диагностика','Повторный приём','Расширенный приём']
    durations=[20,30,45,60]
    for i in range(1,n_services+1): services.append((i,f'{labels[(i-1)%4]} {i}',durations[(i-1)%4]))
    with db.raw.cursor() as cur:
        with cur.copy('COPY services(id,name,duration_minutes) FROM STDIN') as copy:
            for row in services: copy.write_row(row)
        supported={}
        with cur.copy('COPY specialists(id,name,service_ids) FROM STDIN') as copy:
            surnames=['Иванов','Петрова','Смирнов','Кузнецова','Соколов','Попова','Орлов','Волкова','Морозов','Фёдорова']
            for sid in range(1,n_spec+1):
                ids=sorted({1,*[i for i in range(2,n_services+1) if (sid+i)%3==0]})
                supported[sid]=ids
                copy.write_row((sid,f'{surnames[(sid-1)%10]} · специалист {sid}',ids))
        with cur.copy('COPY slots(id,specialist_id,start_at,end_at) FROM STDIN') as copy:
            for i in range(n_slots):
                sid=i%n_spec+1; turn=i//n_spec
                start=BASE+timedelta(days=turn//8,hours=turn%8)
                copy.write_row((i+1,sid,start,start+timedelta(hours=1)))
        with cur.copy('COPY appointments(id,slot_id,service_id,specialist_id,client_name,start_at,end_at,status,created_at,cancelled_at) FROM STDIN') as copy:
            for i in range(n_appointments):
                sid=i%n_spec+1; turn=i//n_spec
                start=BASE+timedelta(days=turn//8,hours=turn%8)
                choices=supported[sid]; service_id=choices[(i//n_spec)%len(choices)]
                duration=durations[(service_id-1)%4]
                cancelled=i%5==0
                copy.write_row((i+1,i+1,service_id,sid,f'Клиент {i+1:06}',start,start+timedelta(minutes=duration),
                                'cancelled' if cancelled else 'active',BASE-timedelta(days=1),BASE if cancelled else None))
    for table in ('users','services','specialists','slots','appointments'):
        db.execute(f"SELECT setval(pg_get_serial_sequence('{table}','id'),(SELECT max(id) FROM {table}))")
        db.execute(f'ANALYZE {table}')
    return counts(db)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size',choices=SIZES,default='small')
    parser.add_argument('--reset',action='store_true',help='Replace all data in the selected database')
    args=parser.parse_args()
    initialize()
    with connection() as db:
        result=seed_dataset(db,args.size,args.reset)
        print(json.dumps({'size':args.size,'counts':result,'fingerprint':dataset_fingerprint(db)},ensure_ascii=False,indent=2))
