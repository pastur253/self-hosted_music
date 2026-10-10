from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from ..domain.models import MixDefinition
from ..storage.layout import Layout

LOGGER = logging.getLogger("mixcore.scheduler")

SYNC_INTERVAL_SECONDS = 900
COMPACT_HOUR = 4


@dataclass(slots=True)
class SchedulerState:
    started_at: float
    tasks_run: int = 0
    failures: int = 0
    last_error: str = ""
    last_run_at: float = 0.0


class MixScheduler:
    """Планировщик в процессе MixCore: расписание миксов, синхронизация библиотеки, компакция журналов."""

    def __init__(self, layout: Layout, service: Any, library: Any, *, interval: int = 60) -> None:
        self._layout = layout
        self._service = service
        self._library = library
        self._interval = interval
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[Any]] = []
        self.state = SchedulerState(started_at=time.time())

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._tasks = [
            loop.create_task(self._loop_ticks(), name="mixcore-ticks"),
            loop.create_task(self._loop_hourly(), name="mixcore-hourly"),
        ]
        LOGGER.info("Планировщик запущен: интервал=%ss", self._interval)

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()

    def mixes(self) -> list[MixDefinition]:
        result: list[MixDefinition] = []
        for mix_id in self._layout.mix_ids():
            raw = self._layout.mix(mix_id).load()
            if raw:
                result.append(MixDefinition.from_dict(raw))
        return result

    def due_mixes(self, now: float | None = None) -> list[MixDefinition]:
        moment = now if now is not None else time.time()
        return [
            mix
            for mix in self.mixes()
            if mix.enabled and _is_due(mix.schedule, moment)
        ]

    async def run_due(self, *, force: bool = False) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for mix in self.mixes() if force else self.due_mixes():
            if not mix.enabled:
                continue
            try:
                outcome = await self._service.generate(mix)
                self.state.tasks_run += 1
                self.state.last_run_at = moment_now()
                results.append(
                    {
                        "mix_id": outcome.mix_id,
                        "title": outcome.title,
                        "tracks": len(outcome.track_ids),
                        "mode": outcome.mode,
                        "problems": outcome.quality_problems,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                self.state.failures += 1
                self.state.last_error = f"{type(exc).__name__}: {exc}"
                LOGGER.exception("Не удалось сгенерировать микс %s", mix.mix_id)
        return results

    async def _loop_ticks(self) -> None:
        last_sync = 0.0
        while not self._stop.is_set():
            try:
                await self.run_due()
                if moment_now() - last_sync > SYNC_INTERVAL_SECONDS:
                    await self._library.sync()
                    last_sync = moment_now()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.state.failures += 1
                self.state.last_error = str(exc)
                LOGGER.exception("Ошибка цикла планировщика")
            await asyncio.sleep(self._interval)

    async def _loop_hourly(self) -> None:
        while not self._stop.is_set():
            now = time.localtime()
            if now.tm_hour == COMPACT_HOUR and now.tm_min < self._interval:
                try:
                    self._layout.play_events().compact_all()
                    self._layout.mix_runs().compact_all()
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("Компакция не выполнена: %s", exc)
            await asyncio.sleep(self._interval)


def _is_due(schedule: str, moment: float) -> bool:
    if not schedule:
        return False
    hour, _, day = schedule.partition(":")
    try:
        target_hour = int(hour)
    except ValueError:
        return False
    local = time.localtime(moment)
    if target_hour != local.tm_hour:
        return False
    if not day:
        return local.tm_min < 5
    return int(day) == local.tm_mday and local.tm_min < 5


def moment_now() -> float:
    return time.time()