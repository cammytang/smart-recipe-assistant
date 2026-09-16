"""Standalone auth application, without loading recipe/AI infrastructure."""
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import auth_lifespan
from .config import AuthConfig
from .router import router


def create_auth_app(config=None):
    if config is None:
        load_dotenv(Path(__file__).resolve().parents[2] / '.env')
        config = AuthConfig.from_env()
    app = FastAPI(title='Recipe Authentication', lifespan=auth_lifespan)
    app.state.auth_config = config
    app.add_middleware(CORSMiddleware, allow_origins=list(config.allowed_origins),
                       allow_credentials=True, allow_methods=['GET', 'POST', 'DELETE'],
                       allow_headers=['Content-Type'])
    app.include_router(router)
    return app
