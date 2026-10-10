from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"
COLLAB_ROLES = (ROLE_OWNER, ROLE_EDITOR, ROLE_VIEWER)

EVENT_PLAY = "play"
EVENT_SKIP = "skip"
EVENT_LOVE = "love"
EVENT_RATE = "rate"
EVENT_BOOKMARK = "bookmark"


@dataclass(frozen=True, slots=True)
class Track:
    id: str
    title: str = ""
    artist: str = ""
    album: str = ""
    album_id: str = ""
    artist_id: str = ""
    genre: str = ""
    duration: float = 0.0
    bpm: float | None = None
    year: int | None = None
    date_added: float = 0.0
    tags: tuple[str, ...] = ()
    loved: bool = False
    rating: int = 0
    play_count: int = 0
    last_played: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "album_id": self.album_id,
            "artist_id": self.artist_id,
            "genre": self.genre,
            "duration": self.duration,
            "bpm": self.bpm,
            "year": self.year,
            "date_added": self.date_added,
            "tags": list(self.tags),
            "loved": self.loved,
            "rating": self.rating,
            "play_count": self.play_count,
            "last_played": self.last_played,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Track:
        return cls(
            id=str(payload["id"]),
            title=str(payload.get("title", "")),
            artist=str(payload.get("artist", "")),
            album=str(payload.get("album", "")),
            album_id=str(payload.get("album_id", "")),
            artist_id=str(payload.get("artist_id", "")),
            genre=str(payload.get("genre", "")),
            duration=float(payload.get("duration", 0.0) or 0.0),
            bpm=_opt_float(payload.get("bpm")),
            year=_opt_int(payload.get("year")),
            date_added=float(payload.get("date_added", 0.0) or 0.0),
            tags=tuple(payload.get("tags", ()) or ()),
            loved=bool(payload.get("loved", False)),
            rating=int(payload.get("rating", 0) or 0),
            play_count=int(payload.get("play_count", 0) or 0),
            last_played=_opt_float(payload.get("last_played")),
        )


@dataclass(frozen=True, slots=True)
class PlayEvent:
    user_id: str
    track_id: str
    kind: str
    ts: float
    position_ms: int = 0
    rating: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "track_id": self.track_id,
            "kind": self.kind,
            "ts": self.ts,
            "position_ms": self.position_ms,
            "rating": self.rating,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlayEvent:
        return cls(
            user_id=str(payload["user_id"]),
            track_id=str(payload["track_id"]),
            kind=str(payload["kind"]),
            ts=float(payload["ts"]),
            position_ms=int(payload.get("position_ms", 0) or 0),
            rating=int(payload.get("rating", 0) or 0),
        )


@dataclass(frozen=True, slots=True)
class UserSettings:
    user_id: str
    timezone: str = "UTC"
    latitude: float | None = None
    longitude: float | None = None
    weather_enabled: bool = False
    role: str = "user"
    navidrome_username: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "timezone": self.timezone,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "weather_enabled": self.weather_enabled,
            "role": self.role,
            "navidrome_username": self.navidrome_username,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> UserSettings:
        return cls(
            user_id=str(payload["user_id"]),
            timezone=str(payload.get("timezone", "UTC")),
            latitude=_opt_float(payload.get("latitude")),
            longitude=_opt_float(payload.get("longitude")),
            weather_enabled=bool(payload.get("weather_enabled", False)),
            role=str(payload.get("role", "user")),
            navidrome_username=str(payload.get("navidrome_username", "")),
        )


@dataclass(frozen=True, slots=True)
class MixDefinition:
    mix_id: str
    name: str
    owner_id: str
    template_code: str = ""
    length: int = 30
    schedule: str = ""
    context_types: tuple[str, ...] = ("time_slot",)
    rules: dict[str, Any] = field(default_factory=dict)
    navidrome_playlist_id: str = ""
    enabled: bool = True
    title_template: str = "{name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mix_id": self.mix_id,
            "name": self.name,
            "owner_id": self.owner_id,
            "template_code": self.template_code,
            "length": self.length,
            "schedule": self.schedule,
            "context_types": list(self.context_types),
            "rules": self.rules,
            "navidrome_playlist_id": self.navidrome_playlist_id,
            "enabled": self.enabled,
            "title_template": self.title_template,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MixDefinition:
        return cls(
            mix_id=str(payload["mix_id"]),
            name=str(payload["name"]),
            owner_id=str(payload["owner_id"]),
            template_code=str(payload.get("template_code", "")),
            length=int(payload.get("length", 30)),
            schedule=str(payload.get("schedule", "")),
            context_types=tuple(payload.get("context_types", ("time_slot",))),
            rules=dict(payload.get("rules", {})),
            navidrome_playlist_id=str(payload.get("navidrome_playlist_id", "")),
            enabled=bool(payload.get("enabled", True)),
            title_template=str(payload.get("title_template", "{name}")),
        )


@dataclass(frozen=True, slots=True)
class CollabPlaylist:
    playlist_id: str
    navidrome_playlist_id: str
    name: str
    description: str = ""
    owner_id: str = ""
    created_seq: int = 0
    next_seq: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "playlist_id": self.playlist_id,
            "navidrome_playlist_id": self.navidrome_playlist_id,
            "name": self.name,
            "description": self.description,
            "owner_id": self.owner_id,
            "created_seq": self.created_seq,
            "next_seq": self.next_seq,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CollabPlaylist:
        return cls(
            playlist_id=str(payload["playlist_id"]),
            navidrome_playlist_id=str(payload.get("navidrome_playlist_id", "")),
            name=str(payload.get("name", "")),
            description=str(payload.get("description", "")),
            owner_id=str(payload.get("owner_id", "")),
            created_seq=int(payload.get("created_seq", 0)),
            next_seq=int(payload.get("next_seq", 1)),
        )


@dataclass(frozen=True, slots=True)
class CollabMember:
    playlist_id: str
    user_id: str
    role: str = ROLE_VIEWER

    def to_dict(self) -> dict[str, Any]:
        return {"playlist_id": self.playlist_id, "user_id": self.user_id, "role": self.role}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CollabMember:
        return cls(
            playlist_id=str(payload["playlist_id"]),
            user_id=str(payload["user_id"]),
            role=str(payload.get("role", ROLE_VIEWER)),
        )


@dataclass(frozen=True, slots=True)
class CollabOp:
    playlist_id: str
    seq: int
    op: str
    actor_id: str
    op_id: str
    ts: float
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "playlist_id": self.playlist_id,
            "seq": self.seq,
            "op": self.op,
            "actor_id": self.actor_id,
            "op_id": self.op_id,
            "ts": self.ts,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CollabOp:
        return cls(
            playlist_id=str(payload["playlist_id"]),
            seq=int(payload["seq"]),
            op=str(payload["op"]),
            actor_id=str(payload.get("actor_id", "")),
            op_id=str(payload.get("op_id", "")),
            ts=float(payload.get("ts", 0.0)),
            payload=dict(payload.get("payload", {})),
        )


@dataclass(frozen=True, slots=True)
class MixRun:
    mix_id: str
    ts: float
    mode: str
    enabled_modules: tuple[str, ...]
    degraded_reason: str
    seed: int
    context: dict[str, Any]
    track_ids: tuple[str, ...]
    metrics: dict[str, float]
    status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mix_id": self.mix_id,
            "ts": self.ts,
            "mode": self.mode,
            "enabled_modules": list(self.enabled_modules),
            "degraded_reason": self.degraded_reason,
            "seed": self.seed,
            "context": self.context,
            "track_ids": list(self.track_ids),
            "metrics": self.metrics,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MixRun:
        return cls(
            mix_id=str(payload["mix_id"]),
            ts=float(payload.get("ts", 0.0)),
            mode=str(payload.get("mode", "algo")),
            enabled_modules=tuple(payload.get("enabled_modules", ())),
            degraded_reason=str(payload.get("degraded_reason", "")),
            seed=int(payload.get("seed", 0)),
            context=dict(payload.get("context", {})),
            track_ids=tuple(payload.get("track_ids", ())),
            metrics={k: float(v) for k, v in dict(payload.get("metrics", {})).items()},
            status=str(payload.get("status", "ok")),
        )


def _opt_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None