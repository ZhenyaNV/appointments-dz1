from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.db import connection, initialize
from app.auth import hash_password
from tests.conftest import require_test_database

@pytest.fixture(autouse=True)
def database():
    with connection() as db:
        require_test_database(db.execute('SELECT current_database() AS name').fetchone()['name'])
    initialize()
    with connection() as db:
        db.execute('TRUNCATE appointments, slots, specialists, services, sessions, users RESTART IDENTITY CASCADE')
        db.execute('INSERT INTO users(username,password_hash) VALUES (%s,%s)', ('demo', hash_password('demo12345')))
        db.execute("INSERT INTO services(name,duration_minutes) VALUES ('Консультация',30),('Длинный приём',90)")
        db.execute("INSERT INTO specialists(name,service_ids) VALUES ('Иванов',ARRAY[1,2]),('Петров',ARRAY[1])")
        db.execute("INSERT INTO slots(specialist_id,start_at,end_at) VALUES (1,'2026-10-05 09:00+03','2026-10-05 10:00+03'),(1,'2026-10-05 09:15+03','2026-10-05 10:15+03'),(2,'2026-10-05 09:00+03','2026-10-05 10:00+03')")

@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c

@pytest.fixture
def authorized(client):
    assert client.post('/api/login', json={'username':'demo','password':'demo12345'}).status_code == 200
    return client

def book(c, slot=1, service=1):
    return c.post('/api/appointments', json={'slot_id':slot,'service_id':service,'client_name':'Тестовый клиент'})

def test_authorization_is_required(client):
    for path in ['/api/me','/api/appointments','/api/services','/api/specialists','/api/slots?service_id=1','/api/summary']:
        assert client.get(path).status_code == 401

def test_wrong_password_is_rejected(client):
    assert client.post('/api/login',json={'username':'demo','password':'wrong'}).status_code == 401

def test_expired_session_is_rejected(authorized):
    with connection() as db: db.execute("UPDATE sessions SET expires_at=now()-interval '1 minute'")
    assert authorized.get('/api/me').status_code == 401

def test_logout_revokes_session(authorized):
    assert authorized.post('/api/logout').status_code == 200
    assert authorized.get('/api/me').status_code == 401

def test_list_pagination_filter_and_card(authorized):
    created = book(authorized).json()
    result = authorized.get('/api/appointments?page=1&size=1&status=active').json()
    assert result['total'] == 1
    assert len(result['items']) == 1
    assert result['items'][0]['specialist_name'] == 'Иванов'
    card = authorized.get('/api/appointments/'+str(created['id'])).json()
    assert card['service_name'] == 'Консультация'
    assert card['client_name'] == 'Тестовый клиент'
    assert authorized.get('/api/appointments?page=2&size=1').json()['items'] == []

def test_invalid_parameters_are_rejected(authorized):
    for query in ['page=0','size=0','size=101','status=other','from_at=2026-10-06T00:00:00%2B03:00&to_at=2026-10-05T00:00:00%2B03:00','from_at=2026-10-05T00:00:00']:
        assert authorized.get('/api/appointments?'+query).status_code == 422
    assert authorized.get('/api/summary?from_at=2026-10-06T00:00:00%2B03:00&to_at=2026-10-05T00:00:00%2B03:00').status_code == 422

def test_cancellation_releases_slot_and_keeps_history(authorized):
    created = book(authorized)
    assert created.status_code == 201
    aid=created.json()['id']
    assert authorized.post(f'/api/appointments/{aid}/cancel').json()['status'] == 'cancelled'
    assert authorized.post(f'/api/appointments/{aid}/cancel').status_code == 409
    assert book(authorized).status_code == 201
    assert authorized.get('/api/appointments?status=cancelled').json()['total'] == 1

def test_overlapping_slots_cannot_be_booked(authorized):
    assert book(authorized).status_code == 201
    assert book(authorized,slot=2).status_code == 409

def test_service_duration_and_support_are_validated(authorized):
    assert book(authorized,service=2).status_code == 409
    assert book(authorized,slot=3,service=2).status_code == 409
    assert book(authorized,slot=999).status_code == 404

def test_summary_rates_and_empty_period(authorized):
    first=book(authorized).json()['id']
    authorized.post(f'/api/appointments/{first}/cancel')
    assert book(authorized).status_code == 201
    summary=authorized.get('/api/summary').json()
    assert summary['total_appointments'] == 2
    assert summary['cancellation_rate'] == 50.0
    assert summary['specialists'][0]['booked_minutes'] == 30
    empty=authorized.get('/api/summary?from_at=2027-01-01T00:00:00%2B03:00&to_at=2027-01-02T00:00:00%2B03:00').json()
    assert empty['total_appointments'] == 0
    assert empty['utilization'] == 0

def test_clipped_period_counts_only_time_inside_period(authorized):
    book(authorized)
    r=authorized.get('/api/summary?from_at=2026-10-05T09:15:00%2B03:00&to_at=2026-10-05T09:30:00%2B03:00').json()
    assert r['specialists'][0]['booked_minutes'] == 15
    assert r['total_appointments'] == 1

def test_simultaneous_booking_allows_one_winner(authorized):
    cookies=dict(authorized.cookies)
    def attempt(_):
        with TestClient(create_app()) as c:
            c.cookies.update(cookies)
            return book(c).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt,range(2))) == [201,409]

def test_metrics_are_present_and_static_is_not_cached(authorized):
    r=authorized.get('/api/appointments')
    assert 'sql;' in r.headers['server-timing']
    assert r.headers['cache-control'] == 'no-store'

def test_first_assignment_has_only_primary_key_indexes(authorized):
    with connection() as db:
        extra=db.execute("SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='evgenii_nevokshenov' AND NOT i.indisprimary").fetchall()
    assert extra == []
