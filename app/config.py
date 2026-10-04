import os
import re
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://app:local-study-password@db:5432/evgenii_nevokshenov')
SCHEMA = os.getenv('DB_SCHEMA', 'evgenii_nevokshenov')
if not re.fullmatch(r'[a-z][a-z0-9_]*', SCHEMA):
    raise RuntimeError('Invalid schema')
DEMO_PASSWORD = os.getenv('DEMO_PASSWORD', 'demo12345')
