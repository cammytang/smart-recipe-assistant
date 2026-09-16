import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


@pytest.fixture
def database_url():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL is not configured; PostgreSQL integration test not executed')
    info = conninfo_to_dict(url)
    if 'test' not in info.get('dbname', '').lower() or url == os.getenv('DATABASE_URL'):
        pytest.fail('TEST_DATABASE_URL must identify a dedicated test database')
    schema = 'auth_test_' + uuid4().hex
    # Only a newly generated schema is mutated, never pre-existing tables.
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        connection.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        ddl = (Path(__file__).resolve().parents[1] / 'database/init.sql').read_text()
        connection.execute(ddl)
    try:
        yield make_conninfo(url, options=f'-c search_path={schema}')
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


@pytest.fixture
def app(database_url):
    from auth.app import create_auth_app
    from auth.config import AuthConfig
    return create_auth_app(AuthConfig(database_url, environment='test'))


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        yield client
