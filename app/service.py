from collections import defaultdict
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from app.rules import validate_booking, summary_metrics

DEFAULT_FROM = datetime(2026,10,1,tzinfo=timezone(timedelta(hours=3)))
DEFAULT_TO = datetime(2028,1,1,tzinfo=timezone(timedelta(hours=3)))

CARD_SQL='''SELECT a.*, s.name AS specialist_name, v.name AS service_name, v.duration_minutes,
 sl.start_at AS slot_start, sl.end_at AS slot_end FROM appointments a
 JOIN specialists s ON s.id=a.specialist_id JOIN services v ON v.id=a.service_id
 JOIN slots sl ON sl.id=a.slot_id'''


def check_period(from_at, to_at):
    if any(x.tzinfo is None or x.utcoffset() is None for x in (from_at,to_at)):
        raise HTTPException(422,'Укажите часовой пояс даты')
    if from_at >= to_at:
        raise HTTPException(422,'Начало периода должно быть раньше конца')


def card(db, aid):
    result=db.execute(CARD_SQL+' WHERE a.id=%s',(aid,)).fetchone()
    if not result: raise HTTPException(404,'Запись не найдена')
    return result


def list_appointments(db, page, size, status, specialist_id, from_at, to_at):
    check_period(from_at,to_at)
    clauses=['a.start_at < %s','a.end_at > %s']
    params=[to_at,from_at]
    if status:
        clauses.append('a.status=%s'); params.append(status)
    if specialist_id:
        clauses.append('a.specialist_id=%s'); params.append(specialist_id)
    where=' WHERE '+' AND '.join(clauses)
    total=db.execute('SELECT count(*) AS total FROM appointments a'+where,params).fetchone()['total']
    rows=db.execute(CARD_SQL+where+' ORDER BY a.start_at,a.id LIMIT %s OFFSET %s',params+[size,(page-1)*size]).fetchall()
    return {'items':rows,'total':total,'page':page,'size':size}


def free_slots(db, service_id, specialist_id, from_at, to_at, page, size):
    check_period(from_at,to_at)
    if to_at-from_at>timedelta(days=31): raise HTTPException(422,'Поиск слотов ограничен 31 днём')
    service=db.execute('SELECT * FROM services WHERE id=%s',(service_id,)).fetchone()
    if not service: raise HTTPException(404,'Услуга не найдена')
    params=[service_id,from_at,to_at,service['duration_minutes'],service['duration_minutes']]
    specialist_filter=''
    if specialist_id:
        specialist_filter=' AND sl.specialist_id=%s'; params.append(specialist_id)
    # Direct set query. No cache, secondary indexes, or SQL calls per row.
    base=''' FROM slots sl JOIN specialists s ON s.id=sl.specialist_id
        LEFT JOIN appointments a ON a.specialist_id=sl.specialist_id AND a.status='active'
          AND a.start_at < sl.start_at + make_interval(mins => %s)
          AND a.end_at > sl.start_at
        WHERE %s=ANY(s.service_ids) AND sl.start_at>=%s AND sl.start_at<%s
          AND sl.end_at-sl.start_at>=make_interval(mins => %s) AND a.id IS NULL'''
    # Place duration parameter first, to follow SQL placeholders.
    sqlparams=[params[3],params[0],params[1],params[2],params[4]]+params[5:]
    base+=specialist_filter
    total=db.execute('SELECT count(*) AS total'+base,sqlparams).fetchone()['total']
    rows=db.execute('SELECT sl.*, s.name AS specialist_name'+base+' ORDER BY sl.start_at,sl.id LIMIT %s OFFSET %s',sqlparams+[size,(page-1)*size]).fetchall()
    return {'items':rows,'total':total,'page':page,'size':size}


def book(db, data):
    slot=db.execute('SELECT * FROM slots WHERE id=%s',(data.slot_id,)).fetchone()
    if not slot: raise HTTPException(404,'Слот не найден')
    specialist=db.execute('SELECT * FROM specialists WHERE id=%s FOR UPDATE',(slot['specialist_id'],)).fetchone()
    service=db.execute('SELECT * FROM services WHERE id=%s',(data.service_id,)).fetchone()
    if not service: raise HTTPException(404,'Услуга не найдена')
    start=data.start_at or slot['start_at']
    try: validate_booking(service['duration_minutes'],slot['start_at'],slot['end_at'],start,data.service_id in specialist['service_ids'])
    except ValueError as e: raise HTTPException(409,str(e)) from e
    end=start+timedelta(minutes=service['duration_minutes'])
    conflict=db.execute("SELECT id FROM appointments WHERE specialist_id=%s AND status='active' AND start_at<%s AND end_at>%s LIMIT 1",(slot['specialist_id'],end,start)).fetchone()
    if conflict: raise HTTPException(409,'На это время уже существует запись')
    aid=db.execute('''INSERT INTO appointments(slot_id,service_id,specialist_id,client_name,start_at,end_at,status)
        VALUES (%s,%s,%s,%s,%s,%s,'active') RETURNING id''',
        (data.slot_id,data.service_id,slot['specialist_id'],data.client_name.strip(),start,end)).fetchone()['id']
    return card(db,aid)


def cancel(db, aid):
    row=db.execute('SELECT * FROM appointments WHERE id=%s FOR UPDATE',(aid,)).fetchone()
    if not row: raise HTTPException(404,'Запись не найдена')
    if row['status']=='cancelled': raise HTTPException(409,'Запись уже отменена')
    db.execute("UPDATE appointments SET status='cancelled',cancelled_at=now() WHERE id=%s",(aid,))
    return card(db,aid)


def interval_minutes(start, end, from_at, to_at):
    return max(0,(min(end,to_at)-max(start,from_at)).total_seconds()/60)


def summary(db, from_at, to_at):
    check_period(from_at,to_at)
    specialists=db.execute('SELECT id,name FROM specialists ORDER BY id').fetchall()
    slots=db.execute('SELECT specialist_id,start_at,end_at FROM slots WHERE start_at<%s AND end_at>%s ORDER BY specialist_id,start_at',(to_at,from_at)).fetchall()
    appointments=db.execute('SELECT specialist_id,start_at,end_at,status FROM appointments WHERE start_at<%s AND end_at>%s',(to_at,from_at)).fetchall()
    schedule=defaultdict(list)
    for sl in slots: schedule[sl['specialist_id']].append((max(sl['start_at'],from_at),min(sl['end_at'],to_at)))
    available={}
    for sid, intervals in schedule.items():
        # Merge overlapping schedule slots; never count the same minute twice.
        merged=[]
        for start,end in intervals:
            if merged and start<=merged[-1][1]: merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
            else: merged.append((start,end))
        available[sid]=sum((end-start).total_seconds()/60 for start,end in merged)
    totals=defaultdict(lambda:{'booked_minutes':0,'total':0,'cancelled':0})
    for a in appointments:
        t=totals[a['specialist_id']]; t['total']+=1
        if a['status']=='cancelled': t['cancelled']+=1
        else: t['booked_minutes']+=interval_minutes(a['start_at'],a['end_at'],from_at,to_at)
    rows=[]
    for s in specialists:
        t=totals[s['id']]; av=available.get(s['id'],0)
        rows.append({**s,**t,'available_minutes':av,**summary_metrics(t['booked_minutes'],av,t['cancelled'],t['total'])})
    booked=sum(r['booked_minutes'] for r in rows); av=sum(available.values())
    total=len(appointments); cancelled=sum(r['cancelled'] for r in rows)
    return {'from_at':from_at,'to_at':to_at,'total_appointments':total,'cancelled':cancelled,
            'booked_minutes':booked,'available_minutes':av,**summary_metrics(booked,av,cancelled,total),'specialists':rows}
