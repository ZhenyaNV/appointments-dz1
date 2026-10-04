from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from time import perf_counter
import psycopg
from psycopg.rows import dict_row
from app.config import DATABASE_URL, SCHEMA

metrics = ContextVar('metrics', default=None)

class Database:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=None):
        start = perf_counter()
        try:
            cursor = self.raw.execute(sql, params)
            rows = cursor.fetchall() if cursor.description else []
            return Result(rows)
        finally:
            state = metrics.get()
            if state is not None:
                state['sql_ms'] += (perf_counter()-start)*1000
                state['queries'] += 1

class Result:
    def __init__(self, rows): self.rows = rows
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows

@contextmanager
def connection():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, options=f'-c search_path={SCHEMA},public') as raw:
        yield Database(raw)

def initialize():
    with connection() as db:
        db.execute(f'CREATE SCHEMA IF NOT EXISTS {SCHEMA}')
        db.execute(Path(__file__).with_name('schema.sql').read_text())
