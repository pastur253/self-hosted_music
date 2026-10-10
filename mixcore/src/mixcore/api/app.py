from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import Settings
from ..runtime import build_runtime, configure_logging
from .routes import register_routes

LOGGER = logging.getLogger("mixcore.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    configure_logging(resolved.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.runtime = await build_runtime(resolved)
        try:
            yield
        finally:
            await app.state.runtime.aclose()
            app.state.runtime.lock.release()

    app = FastAPI(
        title="MixCore",
        version=resolved.version,
        description="Генератор миксов и синтезов, реестр совместных плейлистов поверх Navidrome",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_routes(app)
    return app