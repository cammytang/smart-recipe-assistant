from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from threading import Barrier, Lock

import pytest
from fastapi.testclient import TestClient

from auth.security import COOKIE_NAME
from recipe_router import router, get_agent_factory
from services.memory import MemoryService
from services.memory_repository import MemoryRepository

ORIGIN = {'Origin': 'http://localhost:5173'}
ENDPOINTS = [('/memory', 'GET', None), ('/memory/confirm', 'POST', {'user_requirement': '清淡', 'dish_list': []}),
             ('/memory/clear', 'POST', None), ('/menu/plan', 'POST', {'topic': '晚餐'}),
             ('/menu/stream', 'POST', {'topic': '晚餐'}), ('/research', 'POST', {'topic': '晚餐'})]


@pytest.fixture
def recipe_app(app):
    app.include_router(router)
    app.state.observed = []
    lock = Lock()

    class FakeAgent:
        def __init__(self, config, memory):
            self.config = config
            self.memory = memory
            with lock:
                app.state.observed.append(self)

        def plan_menu(self, topic, context):
            self.context = context
            return [{'id': 1, 'name': '测试菜'}]

        def run(self, topic):
            self.context = self.memory.format_memory_for_prompt()
            return SimpleNamespace(menu_markdown='测试菜谱', dish_list=[], shopping_list=[])

        def run_stream(self, topic, dishes):
            self.context = self.memory.format_memory_for_prompt()
            self.dishes = dishes
            if topic == 'fail':
                raise RuntimeError('private database credentials and other user data')
            yield {'type': 'done'}

    app.dependency_overrides[get_agent_factory] = lambda: FakeAgent
    return app


@pytest.fixture
def browser(recipe_app):
    with TestClient(recipe_app) as browser:
        yield browser


def identity(browser, username):
    body = {'username': username, 'password': 'Example-password123!'}
    assert browser.post('/api/v1/users', json=body, headers=ORIGIN).status_code == 201
    browser.cookies.clear()
    response = browser.post('/api/v1/sessions', json=body, headers=ORIGIN)
    assert response.status_code == 201
    return response.json()['user']['id'], browser.cookies[COOKIE_NAME]


def as_user(browser, token):
    browser.cookies.clear()
    browser.cookies.set(COOKIE_NAME, token, domain='testserver.local', path='/')


def confirm(browser, text):
    return browser.post('/memory/confirm', json={'user_requirement': text, 'dish_list': []}, headers=ORIGIN)


@pytest.mark.parametrize('path,method,body', ENDPOINTS)
def test_every_endpoint_requires_login(browser, path, method, body):
    result = browser.request(method, path, json=body, headers=ORIGIN)
    assert result.status_code == 401
    assert result.json()['error']['code'] == 'UNAUTHENTICATED'
    assert 'text/event-stream' not in result.headers['content-type']
    assert not browser.app.state.observed


def test_memory_isolation_clear_and_repair(browser):
    alice_id, alice = identity(browser, 'alice')
    bob_id, bob = identity(browser, 'bob')
    as_user(browser, alice)
    result = confirm(browser, '清淡，虾过敏，土豆，两人餐')
    assert result.status_code == 200
    assert result.json()['memory']['version'] == 2
    assert result.json()['memory']['allergies'] == ['虾']
    as_user(browser, bob)
    assert browser.get('/memory').json()['memory']['allergies'] == []
    confirm(browser, '高蛋白，鸡蛋')
    before = browser.get('/memory').json()
    as_user(browser, alice)
    cleared = browser.post('/memory/clear', headers=ORIGIN)
    assert cleared.status_code == 200 and cleared.json()['memory']['allergies'] == []
    assert cleared.json()['memory']['version'] == 3
    as_user(browser, bob)
    assert browser.get('/memory').json() == before
    # A missing row is initialized for that user only.
    with browser.app.state.db_pool.connection() as connection:
        connection.execute('DELETE FROM user_memories WHERE user_id = %s', (alice_id,))
    as_user(browser, alice)
    assert browser.get('/memory').json()['memory']['version'] == 1
    with browser.app.state.db_pool.connection() as connection:
        assert connection.execute('SELECT count(*) AS n FROM user_memories WHERE user_id = %s', (bob_id,)).fetchone()['n'] == 1


def test_parallel_confirmations_merge_latest_row(browser):
    user_id, token = identity(browser, 'parallel')
    barrier = Barrier(2)
    def update(text):
        client = TestClient(browser.app)
        try:
            as_user(client, token)
            barrier.wait(timeout=5)
            return confirm(client, text).status_code
        finally:
            client.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(update, ['少油', '高蛋白'])) == [200, 200]
    memory = MemoryRepository(browser.app.state.db_pool, user_id).load()
    assert set(memory['diet_preferences']) == {'少油', '高蛋白'}
    assert memory['version'] == 3
    with browser.app.state.db_pool.connection() as connection:
        profile = connection.execute('SELECT profile FROM user_memories WHERE user_id = %s', (user_id,)).fetchone()['profile']
    assert 'version' not in profile and 'updated_at' not in profile


def test_planning_and_generation_use_only_current_snapshot(browser):
    alice_id, alice = identity(browser, 'alice')
    bob_id, bob = identity(browser, 'bob')
    as_user(browser, alice)
    confirm(browser, '少油')
    as_user(browser, bob)
    confirm(browser, '高蛋白')
    barrier = Barrier(2)
    def plan(token):
        client = TestClient(browser.app)
        try:
            as_user(client, token)
            barrier.wait(timeout=5)
            return client.post('/menu/plan', json={'topic': '晚餐'}, headers=ORIGIN)
        finally:
            client.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(plan, [alice, bob]))
    assert all(result.status_code == 200 for result in results)
    agents = browser.app.state.observed
    for user_id, expected, absent in [(alice_id, '少油', '高蛋白'), (bob_id, '高蛋白', '少油')]:
        agent = next(item for item in agents if user_id in item.config.notes_workspace)
        assert expected in agent.context and absent not in agent.context
        assert agent.memory.repository is None and agent.memory.memory_path is None
    as_user(browser, alice)
    assert browser.post('/research', json={'topic': '晚餐'}, headers=ORIGIN).status_code == 200
    assert browser.post('/menu/stream', json={'topic': '晚餐'}, headers=ORIGIN).status_code == 200
    assert browser.app.state.observed[-1].dishes is None
    assert '少油' in browser.app.state.observed[-1].context
    assert '高蛋白' not in browser.app.state.observed[-1].context
    supplied = {'id': 1, 'name': '青菜', 'note_id': '../../bob/secret', 'note_path': '/private/file',
                'stream_token': 'forged', 'memory_used': ['bob secret']}
    response = browser.post('/menu/stream', json={'topic': '晚餐', 'dish_list': [supplied]}, headers=ORIGIN)
    assert response.status_code == 200
    dish = browser.app.state.observed[-1].dishes[0]
    assert not dish.note_id and not dish.note_path and not dish.stream_token and not dish.memory_used
    # Client identity fields are rejected; identity never comes from input.
    assert browser.post('/menu/plan', json={'topic': '晚餐', 'user_id': bob_id}, headers=ORIGIN).status_code == 422
    assert browser.post('/memory/confirm', json={'user_requirement': '少油', 'user_id': bob_id}, headers=ORIGIN).status_code == 422


def test_origin_failure_stream_error_and_expiry(browser):
    _, token = identity(browser, 'alice')
    for path, method, body in ENDPOINTS:
        if method == 'POST':
            assert browser.request(method, path, json=body).status_code == 403
    # Business calls do not consume the registration/login limiter.
    for _ in range(25):
        assert browser.post('/memory/clear', headers=ORIGIN).status_code == 200
    response = browser.post('/menu/stream', json={'topic': 'fail'}, headers=ORIGIN)
    assert response.status_code == 200 and '"type": "error"' in response.text
    assert 'private' not in response.text
    with browser.app.state.db_pool.connection() as connection:
        connection.execute("UPDATE user_sessions SET expires_at = now() - interval '1 second'")
    for path, method, body in ENDPOINTS:
        assert browser.request(method, path, json=body, headers=ORIGIN).status_code == 401


def test_memory_failure_never_falls_back(browser, monkeypatch):
    identity(browser, 'alice')
    from psycopg import OperationalError
    def fail(_):
        raise OperationalError('private connection details')
    monkeypatch.setattr(MemoryRepository, 'load', fail)
    for path in ['/memory', '/menu/plan', '/menu/stream', '/research']:
        result = browser.get(path) if path == '/memory' else browser.post(path, json={'topic': '晚餐'}, headers=ORIGIN)
        assert result.status_code == 503
        assert 'private' not in result.text
    assert not browser.app.state.observed


def test_default_memory_has_no_file_access(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError('Unexpected filesystem access')
    monkeypatch.setattr(Path, 'open', fail)
    service = MemoryService()
    assert service.load_memory()['allergies'] == []
    service.update_from_confirmation('少油', [])
    assert MemoryService().load_memory()['diet_preferences'] == []
    assert service.load_memory()['diet_preferences'] == ['少油']


def test_note_paths_cannot_escape_workspace(tmp_path):
    from services.scoped_notes import ScopedNoteTool
    alice = ScopedNoteTool(workspace=str(tmp_path / 'alice'))
    bob = ScopedNoteTool(workspace=str(tmp_path / 'bob'))
    bob._get_note_path('secret').write_text('private preference')
    assert not alice._get_note_path('secret').exists()
    for identifier in ['../bob/secret', '/tmp/secret', '..', 'a/b', 'a\\b']:
        with pytest.raises(ValueError):
            alice._get_note_path(identifier)
    (tmp_path / 'alice' / 'link.md').symlink_to(tmp_path / 'bob' / 'secret.md')
    with pytest.raises(ValueError):
        alice._get_note_path('link')
