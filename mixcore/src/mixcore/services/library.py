from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from ..domain.models import Track
from ..navidrome.subsonic import SubsonicClient, parse_song
from ..storage.layout import Layout

LOGGER = logging.getLogger("mixcore.library")

PAGE_SIZE = 500
MAX_TRACKS = 500_000


@dataclass(slots=True)
class LibraryStats:
    total: int
    synced_at: float
    duration_hours: float
    full_sync: bool


class LibraryService:
    """Кэш метаданных библиотеки в ./data/mixcore/cache (пересобираемый, AC-N11)."""

    def __init__(self, layout: Layout, client: SubsonicClient) -> None:
        self._layout = layout
        self._client = client
        self._memory: dict[str, Track] = {}

    def cached(self) -> list[Track]:
        if self._memory:
            return list(self._memory.values())
        payload = self._layout.track_meta.load() or {}
        tracks = [Track.from_dict(item) for item in payload.get("tracks", [])]
        self._memory = {track.id: track for track in tracks}
        return tracks

    def index(self) -> dict[str, Track]:
        if not self._memory:
            self.cached()
        return self._memory

    def known_ids(self) -> set[str]:
        return set(self.index().keys())

    def starred_ids(self) -> set[str]:
        return {track.id for track in self.index().values() if track.loved}

    async def sync(self, *, full: bool = True, max_tracks: int = MAX_TRACKS) -> LibraryStats:
        started = time.time()
        tracks: dict[str, Track] = {}
        offset = 0
        truncated = False
        while offset < max_tracks:
            page = await self._client.search("", limit=PAGE_SIZE, offset=offset)
            if not page:
                break
            for item in page:
                parsed = parse_song(item)
                if not parsed["id"]:
                    continue
                existing = tracks.get(parsed["id"])
                track = Track.from_dict(_merge(parsed, existing))
                tracks[track.id] = track
            offset += len(page)
            if len(page) < PAGE_SIZE:
                break
            if len(tracks) >= max_tracks:
                truncated = True
                break

        starred = await self._safe(self._client.get_starred(), [])
        starred_map = {str(item.get("id", "")): True for item in starred}
        for track_id in starred_map:
            if track_id in tracks:
                current = tracks[track_id]
                tracks[track_id] = Track(**{**_as_dict(current), "loved": True})

        merged = {track.id: track for track in self.cached()}
        merged.update(tracks)
        self._memory = merged
        duration = sum(track.duration for track in merged.values()) / 3600.0
        self._layout.track_meta.save(
            {
                "synced_at": started,
                "tracks": [track.to_dict() for track in merged.values()],
            }
        )
        LOGGER.info(
            "Библиотека синхронизирована: треков=%d новых=%d прервано=%s",
            len(merged),
            len(tracks),
            truncated,
        )
        return LibraryStats(
            total=len(merged),
            synced_at=started,
            duration_hours=round(duration, 2),
            full_sync=full,
        )

    async def _safe(self, coro: object, default: object) -> object:
        try:
            return await coro  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Не удалось получить данные Navidrome: %s", exc)
            return default


def _merge(parsed: dict[str, object], existing: Track | None) -> dict[str, object]:
    result = dict(parsed)
    if existing is None:
        return result
    current = _as_dict(existing)
    for key in ("loved", "rating", "play_count", "last_played", "bpm", "year"):
        if not result.get(key) and current.get(key):
            result[key] = current[key]
    return result


def _as_dict(track: Track) -> dict[str, object]:
    return track.to_dict()