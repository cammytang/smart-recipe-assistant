"""FastAPI entrypoint exposing the DeepResearchAgent via HTTP."""

from __future__ import annotations

from contextlib import asynccontextmanager
import sys
from typing import Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from config import Configuration, SearchAPI
from database import auth_lifespan
from auth.config import AuthConfig
from auth.router import router as auth_router
from recipe_router import router as recipe_router

import os
from dotenv import load_dotenv

# main.py 在 src 内，../ 就是项目根目录，直接找到 .env
env_file = os.path.join(os.path.dirname(__file__), "../.env")
load_dotenv(dotenv_path=env_file)


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


def _mask_secret(value: Optional[str], visible: int = 4) -> str:
    """Mask sensitive tokens while keeping leading and trailing characters."""
    if not value:
        return "unset"

    if len(value) <= visible * 2:
        return "*" * len(value)

    return f"{value[:visible]}...{value[-visible:]}"


def create_app() -> FastAPI:
    auth_config = AuthConfig.from_env()

    @asynccontextmanager
    async def lifespan(application):
        async with auth_lifespan(application):
            log_startup_configuration()
            yield

    app = FastAPI(title="HelloAgents Deep Researcher", lifespan=lifespan)
    app.state.auth_config = auth_config
    app.include_router(auth_router)
    app.include_router(recipe_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(auth_config.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
