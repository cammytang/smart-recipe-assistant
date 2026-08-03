"""FastAPI entrypoint exposing the DeepResearchAgent via HTTP."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Iterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from config import Configuration, SearchAPI
from agent import DeepResearchAgent
from models import DishItem
from services.memory import MemoryService

import os
from dotenv import load_dotenv

# main.py 在 src 内，../ 就是项目根目录，直接找到 .env
env_file = os.path.join(os.path.dirname(__file__), "../.env")
load_dotenv(dotenv_path=env_file)

tavily_api_key = os.getenv("TAVILY_API_KEY")
print(f'🔧 初始化TAVILY_API_KEY: {tavily_api_key}')

# 添加控制台日志处理程序
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <4}</level> | <cyan>using_function:{function}</cyan> | <cyan>{file}:{line}</cyan> | <level>{message}</level>",
    colorize=True,
)


# 添加错误日志文件处理程序
logger.add(
    "logs/error.log",
    level="ERROR",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <4}</level> | <cyan>using_function:{function}</cyan> | <cyan>{file}:{line}</cyan> | <level>{message}</level>",
    colorize=True,
)

# DeepResearch 深度研究 Agent 的 FastAPI 后端入口文件（main.py）
# 作用：把 DeepResearchAgent 封装成 HTTP 接口，前端 / Postman 发 POST 请求就能启动自动全网调研，
# 同时提供普通同步接口 + SSE 流式实时推送接口，配套环境加载、日志、跨域、健康检查、入参校验、敏感信息脱敏、全局异常捕获整套工程化能力。


class ResearchRequest(BaseModel):
    """Payload for triggering a research run."""

    topic: str = Field(..., description="Research topic supplied by the user")
    search_api: SearchAPI | None = Field(
        default=None,
        description="Override the default search backend configured via env",
    )


class DishItemPayload(BaseModel):
    """Dish item accepted from the menu planning confirmation step."""

    id: int
    name: str
    intent: str = ""
    query: str = ""
    status: str = "pending"
    note_id: str | None = None
    note_path: str | None = None
    stream_token: str | None = None
    memory_used: list[str] = Field(default_factory=list)
    memory_conflicts: list[str] = Field(default_factory=list)


class MenuStreamRequest(ResearchRequest):
    """Payload for streaming a menu run after optional user confirmation."""

    dish_list: list[DishItemPayload] | None = Field(
        default=None,
        description="User-confirmed dish list. If omitted, backend plans automatically.",
    )


class MenuPlanResponse(BaseModel):
    """Response containing only the planned dish list."""

    dish_list: list[dict[str, Any]] = Field(default_factory=list)
    memory_summary: list[str] = Field(default_factory=list)
    memory: dict[str, Any] = Field(default_factory=dict)


class MemoryConfirmRequest(BaseModel):
    """Payload for writing confirmed planning outcomes to long-term memory."""

    user_requirement: str
    dish_list: list[dict[str, Any]] = Field(default_factory=list)


class MemoryResponse(BaseModel):
    """Memory state returned to the frontend."""

    memory: dict[str, Any] = Field(default_factory=dict)
    memory_summary: list[str] = Field(default_factory=list)


class ResearchResponse(BaseModel):
    """HTTP response containing the generated report and structured tasks."""

    menu_markdown: str = Field(
        ..., description="Markdown-formatted menu report including sections"
    )
    dish_list: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured dish items with notes and sources",
    )
    shopping_list: list[str] = Field(
        default_factory=list,
        description="Structured shopping list generated from selected recipes",
    )


def _mask_secret(value: Optional[str], visible: int = 4) -> str:
    """Mask sensitive tokens while keeping leading and trailing characters."""
    if not value:
        return "unset"

    if len(value) <= visible * 2:
        return "*" * len(value)

    return f"{value[:visible]}...{value[-visible:]}"


def _build_config(payload: ResearchRequest) -> Configuration:
    overrides: Dict[str, Any] = {}

    if payload.search_api is not None:
        overrides["search_api"] = payload.search_api

    return Configuration.from_env(overrides=overrides)


def create_app() -> FastAPI:
    app = FastAPI(title="HelloAgents Deep Researcher")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def log_startup_configuration() -> None:
        config = Configuration.from_env()

        if config.llm_provider == "ollama":
            base_url = config.sanitized_ollama_url()
        elif config.llm_provider == "lmstudio":
            base_url = config.lmstudio_base_url
        else:
            base_url = config.llm_base_url or "unset"

        logger.info(
            "DeepResearch configuration loaded: provider=%s model=%s base_url=%s search_api=%s "
            "max_loops=%s fetch_full_page=%s tool_calling=%s strip_thinking=%s api_key=%s",
            config.llm_provider,
            config.resolved_model() or "unset",
            base_url,
            (config.search_api.value if isinstance(config.search_api, SearchAPI) else config.search_api),
            config.max_web_research_loops,
            config.fetch_full_page,
            config.use_tool_calling,
            config.strip_thinking_tokens,
            _mask_secret(config.llm_api_key),
        )

    @app.get("/healthz")
    def health_check() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/memory", response_model=MemoryResponse)
    def get_memory() -> MemoryResponse:
        memory_service = MemoryService()
        memory = memory_service.load_memory()
        return MemoryResponse(
            memory=memory,
            memory_summary=memory_service.summarize_for_ui(memory),
        )

    @app.post("/memory/confirm", response_model=MemoryResponse)
    def confirm_memory(payload: MemoryConfirmRequest) -> MemoryResponse:
        memory_service = MemoryService()
        memory = memory_service.update_from_confirmation(
            payload.user_requirement,
            payload.dish_list,
        )
        return MemoryResponse(
            memory=memory,
            memory_summary=memory_service.summarize_for_ui(memory),
        )

    @app.post("/memory/clear", response_model=MemoryResponse)
    def clear_memory() -> MemoryResponse:
        memory_service = MemoryService()
        memory = memory_service.clear_memory()
        return MemoryResponse(
            memory=memory,
            memory_summary=memory_service.summarize_for_ui(memory),
        )

    @app.post("/research", response_model=ResearchResponse)
    def run_research(payload: ResearchRequest) -> ResearchResponse:
        try:
            config = _build_config(payload)
            agent = DeepResearchAgent(config=config)
            result = agent.run(payload.topic)
        except ValueError as exc:  # Likely due to unsupported configuration
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive guardrail
            raise HTTPException(status_code=500, detail="Research failed") from exc

        dish_payload = [
            {
                "id": item.id,
                "name": item.name,
                "intent": item.intent,
                "query": item.query,
                "status": item.status,
                "ingredients": item.ingredients,
                "cook_steps": item.cook_steps,
                "cook_time": item.cook_time,
                "calories": item.calories,
                "tips": item.tips,
                "source_links": item.source_links,
                "note_id": item.note_id,
                "note_path": item.note_path,
            }
            for item in result.dish_list
        ]

        return ResearchResponse(
            menu_markdown=(result.menu_markdown or ""),
            dish_list=dish_payload,
            shopping_list=result.shopping_list,
        )

    @app.post("/menu/plan", response_model=MenuPlanResponse)
    def plan_menu(payload: ResearchRequest) -> MenuPlanResponse:
        try:
            config = _build_config(payload)
            agent = DeepResearchAgent(config=config)
            memory_service = MemoryService()
            memory = memory_service.load_memory()
            memory_context = memory_service.format_memory_for_prompt(memory)
            dish_list = agent.plan_menu(payload.topic, memory_context)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive guardrail
            logger.exception("Menu planning failed")
            raise HTTPException(status_code=500, detail="Menu planning failed") from exc

        return MenuPlanResponse(
            dish_list=dish_list,
            memory=memory,
            memory_summary=memory_service.summarize_for_ui(memory),
        )

    @app.post("/menu/stream")
    def stream_research(payload: MenuStreamRequest) -> StreamingResponse:
        try:
            config = _build_config(payload)
            agent = DeepResearchAgent(config=config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        confirmed_dishes = None
        if payload.dish_list is not None:
            confirmed_dishes = [
                DishItem(
                    id=item.id,
                    name=item.name,
                    intent=item.intent,
                    query=item.query or payload.topic,
                    status="pending",
                    note_id=item.note_id,
                    note_path=item.note_path,
                    stream_token=item.stream_token,
                    memory_used=item.memory_used,
                    memory_conflicts=item.memory_conflicts,
                )
                for item in payload.dish_list
            ]

        def event_iterator() -> Iterator[str]:
            try:
                for event in agent.run_stream(payload.topic, confirmed_dishes):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as exc:  # pragma: no cover - defensive guardrail
                logger.exception("Streaming research failed")
                error_payload = {"type": "error", "detail": str(exc)}
                yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_iterator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
