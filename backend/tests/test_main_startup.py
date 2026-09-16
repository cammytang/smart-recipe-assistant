"""Exercise the real startup callback without any database or AI calls."""
from contextlib import asynccontextmanager
from importlib import import_module

from fastapi.testclient import TestClient


def test_startup_logging_does_not_prevent_serving_health(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql:///unused_test')
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.setenv('AUTH_COOKIE_SECURE', 'false')
    monkeypatch.setenv('AUTH_ALLOWED_ORIGINS', 'http://localhost:5173')
    main = import_module('main')

    @asynccontextmanager
    async def no_database(_app):
        yield

    monkeypatch.setattr(main, 'auth_lifespan', no_database)
    monkeypatch.setattr(main.Configuration, 'from_env', lambda **kwargs: main.Configuration())
    with TestClient(main.create_app()) as client:
        response = client.get('/healthz')
        assert response.status_code == 200
        assert response.json() == {'status': 'ok'}
