from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx

from .ai import AIEnsemble, NullAI, OllamaAI
from .config import Settings
from .navidrome.subsonic import SubsonicClient
from .services.collab import CollabService
from .services.events import EventStore
from .services.library import LibraryService
from .services.mix_service import MixService
from .services.scheduler import MixScheduler
from .services.weather import WeatherService, build_provider
from .storage.layout import Layout
from .storage.lock import WriterLock

LOGGER = logging.getLogger("mixcore")


@dataclass(slots=True)
class Runtime:
    settings: Settings
    layout: Layout
    client: SubsonicClient
    library: LibraryService
    events: EventStore
    weather: WeatherService
    ai: AIEnsemble
    mixes: MixService
    collab: CollabService
    scheduler: MixScheduler
    lock: WriterLock
    started_at: float = field(default_factory=time.time)

    async def aclose(self) -> None:
        await self.scheduler.stop()
        await self.client.aclose()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )


async def build_runtime(settings: Settings, *, with_scheduler: bool = True) -> Runtime:
    layout = Layout.create(settings.state_dir)
    layout.schema.check()

    lock = WriterLock(layout.lock_path)
    lock.acquire()

    client = SubsonicClient(
        settings.navidrome_url,
        settings.navidrome_user,
        settings.navidrome_password,
        client=httpx.AsyncClient(timeout=20.0),
    )
    library = LibraryService(layout, client)
    events = EventStore(layout)
    weather = WeatherService(layout, build_provider(settings.weather_provider, settings.weather_api_key))
    modules: list[Any] = [NullAI()]
    if settings.llm_enabled:
        modules.append(
            OllamaAI(
                settings.llm_url,
                settings.llm_model,
                timeout_ms=settings.ai_timeout_ms,
                client=httpx.AsyncClient(timeout=settings.ai_timeout_ms / 1000.0),
            )
        )
    ai = AIEnsemble(modules, max_influence=settings.llm_max_influence)
    mixes = MixService(settings, layout, client, library, events, weather, ai)
    collab = CollabService(layout, client)
    scheduler = MixScheduler(layout, mixes, library)

    runtime = Runtime(
        settings=settings,
        layout=layout,
        client=client,
        library=library,
        events=events,
        weather=weather,
        ai=ai,
        mixes=mixes,
        collab=collab,
        scheduler=scheduler,
        lock=lock,
    )
    if with_scheduler:
        await scheduler.start()
    return runtime


@asynccontextmanager
async def runtime_context(settings: Settings | None = None):
    resolved = settings or Settings.from_env()
    configure_logging(resolved.log_level)
    runtime = await build_runtime(resolved)
    try:
        yield runtime
    finally:
        await runtime.aclose()
        runtime.lock.release()


async def check_health(runtime: Runtime) -> dict[str, Any]:
    navidrome = await runtime.client.health()
    ai_status = await runtime.ai.status()
    mode, modules, degraded = await runtime.mixes.mode()
    tracks = len(runtime.library.cached())
    return {
        "status": "ok" if navidrome.get("status") == "up" else "degraded",
        "version": runtime.settings.version,
        "schema_version": runtime.layout.schema.read(),
        "synth_mode": runtime.settings.synth_mode,
        "effective_mode": mode,
        "enabled_modules": modules,
        "degraded_reason": degraded,
        "navidrome": navidrome,
        "ai": [{"name": s.name, "available": s.available, "reason": s.reason} for s in ai_status],
        "weather_provider": runtime.weather.provider_name,
        "library_tracks": tracks,
        "storage": {
            "state_dir": str(runtime.layout.root),
            "play_events": runtime.events.total(),
            "mode": "files",
        },
        "uptime_seconds": round(time.time() - runtime.started_at, 1),
    }


async def run_selftest(runtime: Runtime) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    checks["navidrome_ping"] = (await runtime.client.health()).get("status") == "up"
    checks["lock_held"] = runtime.lock._fd is not None  # noqa: SLF001
    checks["templates_loaded"] = len(runtime.layout.synth_templates.load() or {}) >= 0
    checks["cache_readable"] = isinstance(runtime.library.cached(), list)
    mode, modules, _ = await runtime.mixes.mode()
    checks["algo_mode_available"] = mode in ("algo", "hybrid", "ai")
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "mode": mode,
        "modules": modules,
    }


def run(coro: Any) -> Any:
    return asyncio.run(coro)