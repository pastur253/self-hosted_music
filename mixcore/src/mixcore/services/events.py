from __future__ import annotations

import logging
import time
from collections.abc import Iterable

from ..domain.models import EVENT_LOVE, EVENT_PLAY, EVENT_RATE, EVENT_SKIP, PlayEvent
from ..storage.layout import Layout

LOGGER = logging.getLogger("mixcore.events")

MAX_EVENTS_PER_PASS = 50_000


class EventStore:
    """Зеркало событий из Subsonic-вызовов; единственный источник когорт и пропусков (NV-L15, R-17)."""

    def __init__(self, layout: Layout) -> None:
        self._layout = layout

    def record(self, event: PlayEvent) -> None:
        self._layout.play_events().append(event.to_dict(), timestamp=event.ts)

    def record_many(self, events: Iterable[PlayEvent]) -> int:
        count = 0
        for event in events:
            self.record(event)
            count += 1
        return count

    def for_user(self, user_id: str, *, since: float = 0.0, limit: int | None = None) -> list[PlayEvent]:
        collected: list[PlayEvent] = []
        for payload in self._layout.play_events().iter_range(since=since or None):
            if payload.get("user_id") != user_id:
                continue
            collected.append(PlayEvent.from_dict(payload))
        collected.sort(key=lambda item: item.ts)
        return collected[-limit:] if limit else collected

    def known_ids(self, user_id: str) -> set[str]:
        return {event.track_id for event in self.for_user(user_id)}

    def total(self) -> int:
        return self._layout.play_events().count()

    def compact(self) -> None:
        self._layout.play_events().compact_all()


def event_from_scrobble(
    user_id: str,
    track_id: str,
    submission: bool,
    timestamp_ms: int | None,
) -> PlayEvent:
    return PlayEvent(
        user_id=user_id,
        track_id=track_id,
        kind=EVENT_PLAY if submission else EVENT_SKIP,
        ts=(timestamp_ms / 1000.0) if timestamp_ms else time.time(),
    )


def event_from_star(user_id: str, track_id: str, starred: bool) -> PlayEvent:
    return PlayEvent(
        user_id=user_id,
        track_id=track_id,
        kind=EVENT_LOVE if starred else "unlove",
        ts=time.time(),
    )


def event_from_rating(user_id: str, track_id: str, rating: int) -> PlayEvent:
    return PlayEvent(
        user_id=user_id,
        track_id=track_id,
        kind=EVENT_RATE if rating > 0 else "unrate",
        ts=time.time(),
        rating=rating,
    )


KIND_MAP = {EVENT_PLAY, EVENT_SKIP, EVENT_LOVE, EVENT_RATE}