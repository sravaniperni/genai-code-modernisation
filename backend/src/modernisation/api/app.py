from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from modernisation.api.routers import overview, repositories, tasks, webhooks
from modernisation.config import get_settings
from modernisation.log import configure_logging
from modernisation.telemetry import configure_tracing


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    configure_tracing(settings)
    app = FastAPI(title="Codebase Modernisation Platform", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["authorization", "content-type"],
    )
    app.include_router(overview.router)
    app.include_router(repositories.router)
    app.include_router(tasks.router)
    app.include_router(webhooks.router)
    return app
