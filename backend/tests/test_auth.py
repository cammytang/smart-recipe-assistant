from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.config import AuthConfig
from auth.dependencies import RateLimiter
from auth.errors import AuthError
from auth.router import router
from auth.security import COOKIE_NAME, token_digest, Passwords

ORIGIN = {'Origin': 'http://localhost:5173'}
PASSWORD = 'Test password 123!'


def register(client, username='cammy'):
    return client.post('/api/v1/users', json={'username': username, 'password': PASSWORD}, headers=ORIGIN)


def login(client, username='cammy', password=PASSWORD):
    return client.post('/api/v1/sessions', json={'username': username, 'password': password}, headers=ORIGIN)


def set_token(client, token):
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, token, domain='testserver.local', path='/')


def test_registration_and_cookie_lifecycle(client):
    result = register(client, ' Cammy ')
    assert result.status_code == 201
    assert result.json()['username'] == 'cammy'
    assert 'password' not in result.text
    service = client.app.state.auth_service
    with service.pool.connection() as connection:
        row = connection.execute('SELECT password_hash FROM users').fetchone()
        assert row['password_hash'].startswith('$argon2id$')
        assert PASSWORD not in row['password_hash']
        profile = connection.execute('SELECT profile FROM user_memories').fetchone()['profile']
        assert profile['allergies'] == [] and profile['common_serving_size'] is None
        assert connection.execute('SELECT count(*) AS n FROM user_sessions').fetchone()['n'] == 0
    assert register(client).status_code == 409
    result = login(client)
    assert result.status_code == 201
    cookie = result.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie and 'Path=/' in cookie
    assert 'Max-Age=604800' in cookie and 'Domain=' not in cookie
    token = client.cookies[COOKIE_NAME]
    assert token not in result.text
    with service.pool.connection() as connection:
        assert connection.execute('SELECT token_hash FROM user_sessions').fetchone()['token_hash'] == token_digest(token)
    assert client.get('/api/v1/users/me').json()['id'] == result.json()['user']['id']
    assert client.delete('/api/v1/sessions/current', headers=ORIGIN).status_code == 204
    assert COOKIE_NAME not in client.cookies
    set_token(client, token)
    assert client.get('/api/v1/users/me').status_code == 401
    response = client.delete('/api/v1/sessions/current', headers=ORIGIN)
    assert response.status_code == 204 and response.content == b''
    assert client.delete('/api/v1/sessions/current', headers=ORIGIN).status_code == 204


def test_invalid_credentials_sessions_and_rotation(client):
    register(client)
    a = login(client, password='incorrect-password')
    b = login(client, username='missing_user')
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    for token in ['', 'bad token', 'A' * 43]:
        set_token(client, token)
        assert client.get('/api/v1/users/me').status_code == 401
    login(client)
    first = client.cookies[COOKIE_NAME]
    assert login(client).status_code == 201
    second = client.cookies[COOKIE_NAME]
    assert first != second
    set_token(client, first)
    assert client.get('/api/v1/users/me').status_code == 401
    set_token(client, second)
    assert login(client, password='incorrect-password').status_code == 401
    assert client.get('/api/v1/users/me').status_code == 200
    with client.app.state.auth_service.pool.connection() as connection:
        connection.execute("UPDATE user_sessions SET expires_at = now() - interval '1 second'")
    assert client.get('/api/v1/users/me').status_code == 401
    assert client.app.state.auth_service.cleanup_expired() == 1


def test_users_and_devices_are_independent(client):
    register(client, 'alice')
    register(client, 'bob')
    login(client, 'alice')
    alice = client.cookies[COOKIE_NAME]
    client.cookies.clear()
    login(client, 'alice')
    another_device = client.cookies[COOKIE_NAME]
    login(client, 'bob')
    bob = client.cookies[COOKIE_NAME]
    assert client.get('/api/v1/users/me').json()['username'] == 'bob'
    set_token(client, another_device)
    assert client.get('/api/v1/users/me').status_code == 401
    set_token(client, alice)
    assert client.get('/api/v1/users/me').json()['username'] == 'alice'
    client.delete('/api/v1/sessions/current', headers=ORIGIN)
    set_token(client, bob)
    assert client.get('/api/v1/users/me').json()['username'] == 'bob'


def test_transaction_rolls_back(client):
    with client.app.state.auth_service.pool.connection() as connection:
        connection.execute('ALTER TABLE user_memories ADD CONSTRAINT reject_test CHECK (version < 0)')
    assert register(client).status_code == 500
    with client.app.state.auth_service.pool.connection() as connection:
        assert connection.execute('SELECT count(*) AS n FROM users').fetchone()['n'] == 0


def test_concurrent_duplicate_registration(client):
    # Reuse existing app without entering its lifespan a second time.
    def request(_):
        other = TestClient(client.app)
        try:
            return register(other).status_code
        finally:
            other.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(request, range(2)))
    assert sorted(statuses) == [201, 409]
    with client.app.state.auth_service.pool.connection() as connection:
        assert connection.execute('SELECT count(*) AS n FROM users').fetchone()['n'] == 1
        assert connection.execute('SELECT count(*) AS n FROM user_memories').fetchone()['n'] == 1


def bare_client():
    # Request policy tests require neither database nor AI dependencies.
    app = FastAPI()
    app.state.auth_config = AuthConfig('postgresql://unused/auth_test')
    app.state.auth_limiter = RateLimiter()
    app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize('body', [
    {'username': 'x', 'password': PASSWORD},
    {'username': 'cammy', 'password': 'short'},
    {'username': 'cammy', 'password': 'x' * 129},
    {'username': 'cammy', 'password': PASSWORD, 'user_id': 'another-user'},
    {'username': 'cammy', 'password': 12345678},
])
def test_validation_does_not_expose_input(body):
    with bare_client() as client:
        result = client.post('/api/v1/users', json=body, headers=ORIGIN)
    assert result.status_code == 422
    assert result.json()['error']['code'] == 'VALIDATION_ERROR'
    assert PASSWORD not in result.text
    assert result.headers['cache-control'] == 'no-store'


def test_origin_media_and_json_validation():
    with bare_client() as client:
        for headers in [{}, {'Origin': 'null'}, {'Origin': 'https://evil.example'}]:
            assert client.post('/api/v1/users', json={}, headers=headers).status_code == 403
            assert client.delete('/api/v1/sessions/current', headers=headers).status_code == 403
        assert client.post('/api/v1/users', content='password=secret', headers=ORIGIN).status_code == 415
        response = client.post('/api/v1/users', content='{"password":"sensitive",',
                               headers={**ORIGIN, 'Content-Type': 'application/json; charset=utf-8'})
        assert response.status_code == 422 and 'sensitive' not in response.text


def test_database_failure_is_not_success_or_unauthenticated(client):
    register(client)
    login(client)
    client.app.state.auth_service.pool.close()
    for result in [client.get('/api/v1/users/me'), login(client), register(client, 'other'),
                   client.delete('/api/v1/sessions/current', headers=ORIGIN)]:
        assert result.status_code == 503
        assert 'set-cookie' not in result.headers
        assert result.json()['error']['code'] == 'SERVICE_UNAVAILABLE'


def test_preflight_and_limits(client):
    response = client.options('/api/v1/users', headers={**ORIGIN, 'Access-Control-Request-Method': 'POST',
                                                     'Access-Control-Request-Headers': 'content-type'})
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == ORIGIN['Origin']
    for index in range(5):
        assert register(client, f'user_{index}').status_code == 201
    assert register(client, 'overflow').status_code == 429
    for _ in range(10):
        assert login(client, 'missing').status_code == 401
    assert login(client, 'missing').status_code == 429


def test_fixed_window_and_capacity():
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0], capacity=1)
    limiter.hit('key', 1, 60)
    with pytest.raises(AuthError) as error:
        limiter.hit('key', 1, 60)
    assert error.value.status == 429 and error.value.headers['Retry-After'] == '60'
    with pytest.raises(AuthError):
        limiter.hit('other', 1, 60)
    now[0] = 60
    limiter.hit('other', 1, 60)


def test_configuration_and_password_tools():
    for changes in [{'environment': 'production'}, {'allowed_origins': ('*',)},
                    {'allowed_origins': ('http://localhost:5173/path',)}, {'session_ttl': 0}]:
        with pytest.raises(ValueError):
            AuthConfig('postgresql://unused/auth_test', **changes)
    passwords = Passwords()
    encoded = passwords.hash('  Password123!  ')
    assert passwords.verify(encoded, '  Password123!  ')
    assert not passwords.verify(encoded, 'Password123!')
    assert not passwords.verify(None, 'Password123!')
