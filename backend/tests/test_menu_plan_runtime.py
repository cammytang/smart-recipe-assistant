"""Load real menu dependencies; replace only model execution, with no database writes."""
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.dependencies import get_current_user
from auth.config import AuthConfig
from auth.router import AuthRoute
from config import Configuration
from recipe_router import router, get_memory_service
from services.memory import MemoryService


def test_menu_plan_loads_real_agent(monkeypatch, tmp_path):
    from hello_agents import ToolAwareSimpleAgent

    config = Configuration(
        llm_provider='qwen', llm_api_key='offline-test-key',
        llm_base_url='http://127.0.0.1:1/v1', llm_model_id='offline-test',
        notes_workspace=str(tmp_path),
    )
    monkeypatch.setattr(Configuration, 'from_env', lambda **kwargs: config)
    monkeypatch.setattr(ToolAwareSimpleAgent, 'run', lambda self, prompt:
                        '{"tasks":[{"title":"清炒土豆丝","intent":"清淡", "query":"土豆丝做法"}]}')
    app = FastAPI()
    app.state.auth_config = AuthConfig('postgresql:///unused_test', environment='test')
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {
        'id': '00000000-0000-0000-0000-000000000001', 'username': 'test_user',
    }
    app.dependency_overrides[get_memory_service] = lambda: MemoryService()
    with TestClient(app) as client:
        response = client.post('/menu/plan', json={'topic': '两个人吃土豆，清淡一点'},
                               headers={'Origin': 'http://localhost:5173'})
    assert response.status_code == 200, response.text
    assert response.json()['dish_list'][0]['name'] == '清炒土豆丝'


def test_unexpected_error_logs_location_without_sensitive_message(caplog):
    app = FastAPI()
    app.router.route_class = AuthRoute

    @app.get('/failure')
    def failure():
        raise RuntimeError('private-cookie-and-password')

    with caplog.at_level(logging.ERROR, logger='auth.router'), TestClient(app) as client:
        response = client.get('/failure')
    assert response.status_code == 500
    assert 'RuntimeError' in caplog.text
    assert '(failure)' in caplog.text
    assert 'private-cookie-and-password' not in caplog.text + response.text
