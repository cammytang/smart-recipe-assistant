"""Authenticated recipe routes; no AI service is loaded before authentication."""
import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from auth.dependencies import check_origin, get_current_user
from auth.router import AuthRoute
from config import Configuration
from models import DishItem
from recipe_schemas import (ResearchRequest, MenuStreamRequest, MenuPlanResponse,
                            MemoryConfirmRequest, MemoryResponse, ResearchResponse)
from services.memory import MemoryService
from services.memory_repository import MemoryRepository


class ProtectedRoute(AuthRoute):
    request_guard = staticmethod(check_origin)


router = APIRouter(route_class=ProtectedRoute, tags=['Recipes'],
                   dependencies=[Depends(get_current_user)])


def get_memory_service(request: Request, user=Depends(get_current_user)):
    return MemoryService(repository=MemoryRepository(request.app.state.db_pool, user['id']))


def agent_factory(config, memory_service):
    from agent import DeepResearchAgent
    return DeepResearchAgent(config=config, memory_service=memory_service)


def create_agent(payload, user, memory, factory):
    overrides = {'search_api': payload.search_api} if payload.search_api is not None else {}
    config = Configuration.from_env(overrides=overrides)
    # Server-generated user/run directories also prevent concurrent index-file races.
    workspace = Path(config.notes_workspace or './notes').resolve() / 'users' / str(UUID(str(user['id']))) / uuid4().hex
    config = config.model_copy(update={'notes_workspace': str(workspace)})
    # The agent gets a request snapshot; no DB connection remains open during generation.
    return factory(config, MemoryService(snapshot=memory))


def get_agent_factory():
    return agent_factory


@router.get('/memory', response_model=MemoryResponse)
def get_memory(service=Depends(get_memory_service)):
    memory = service.load_memory()
    return MemoryResponse(memory=memory, memory_summary=service.summarize_for_ui(memory))


@router.post('/memory/confirm', response_model=MemoryResponse)
def confirm_memory(payload: MemoryConfirmRequest, service=Depends(get_memory_service)):
    memory = service.update_from_confirmation(payload.user_requirement, payload.dish_list)
    return MemoryResponse(memory=memory, memory_summary=service.summarize_for_ui(memory))


@router.post('/memory/clear', response_model=MemoryResponse)
def clear_memory(service=Depends(get_memory_service)):
    memory = service.clear_memory()
    return MemoryResponse(memory=memory, memory_summary=service.summarize_for_ui(memory))


@router.post('/menu/plan', response_model=MenuPlanResponse)
def plan_menu(payload: ResearchRequest, user=Depends(get_current_user),
              service=Depends(get_memory_service), factory=Depends(get_agent_factory)):
    memory = service.load_memory()
    agent = create_agent(payload, user, memory, factory)
    dishes = agent.plan_menu(payload.topic, service.format_memory_for_prompt(memory))
    return MenuPlanResponse(dish_list=dishes, memory=memory, memory_summary=service.summarize_for_ui(memory))


@router.post('/research', response_model=ResearchResponse)
def research(payload: ResearchRequest, user=Depends(get_current_user),
             service=Depends(get_memory_service), factory=Depends(get_agent_factory)):
    agent = create_agent(payload, user, service.load_memory(), factory)
    result = agent.run(payload.topic)
    fields = ('id', 'name', 'intent', 'query', 'status', 'ingredients', 'cook_steps',
              'cook_time', 'calories', 'tips', 'source_links', 'note_id', 'note_path')
    return ResearchResponse(menu_markdown=result.menu_markdown or '',
                            dish_list=[{key: getattr(item, key) for key in fields} for item in result.dish_list],
                            shopping_list=result.shopping_list)


@router.post('/menu/stream')
def stream_menu(payload: MenuStreamRequest, user=Depends(get_current_user),
                service=Depends(get_memory_service), factory=Depends(get_agent_factory)):
    agent = create_agent(payload, user, service.load_memory(), factory)
    # Ignore all client-provided note IDs, paths, stream tokens and remembered metadata.
    dishes = None if payload.dish_list is None else [
        DishItem(id=item.id, name=item.name, intent=item.intent,
                 query=item.query or payload.topic, status='pending')
        for item in payload.dish_list
    ]

    def events():
        try:
            for event in agent.run_stream(payload.topic, dishes):
                yield f'data: {json.dumps(event, ensure_ascii=False)}\n\n'
        except Exception:
            yield 'data: ' + json.dumps({'type': 'error', 'detail': '菜谱生成失败，请稍后重试'}, ensure_ascii=False) + '\n\n'

    return StreamingResponse(events(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
