from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

LOGGER = logging.getLogger("mixcore.ws")

HEARTBEAT_SECONDS = 25


@dataclass(slots=True)
class Subscription:
    user_id: str
    playlists: set[str] = field(default_factory=set)
    mixes: set[str] = field(default_factory=set)
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=256))


class EventHub:
    """Внутрипроцессный pub/sub: один MixCore, без внешнего брокера (7.0.2)."""

    def __init__(self) -> None:
        self._subs: dict[WebSocket, Subscription] = {}

    def register(self, websocket: WebSocket, user_id: str) -> Subscription:
        sub = Subscription(user_id=user_id)
        self._subs[websocket] = sub
        return sub

    def unregister(self, websocket: WebSocket) -> None:
        self._subs.pop(websocket, None)

    def publish_playlist(self, playlist_id: str, event: dict[str, Any]) -> None:
        self._dispatch(lambda sub: playlist_id in sub.playlists, event)

    def publish_user(self, user_id: str, event: dict[str, Any]) -> None:
        self._dispatch(lambda sub: sub.user_id == user_id, event)

    def _dispatch(self, predicate: Any, event: dict[str, Any]) -> None:
        for sub in list(self._subs.values()):
            if not predicate(sub):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                LOGGER.warning("Очередь событий переполнена, событие %s пропущено", event.get("type"))


async def drain(websocket: WebSocket, sub: Subscription) -> None:
    while True:
        event = await sub.queue.get()
        await websocket.send_text(json.dumps(event, ensure_ascii=False))


async def keepalive(websocket: WebSocket, sub: Subscription) -> None:
    del sub
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        with contextlib.suppress(Exception):
            await websocket.send_text(json.dumps({"type": "ping", "ts": 0}))