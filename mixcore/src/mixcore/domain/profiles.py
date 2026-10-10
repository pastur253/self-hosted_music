from __future__ import annotations

import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .models import EVENT_LOVE, EVENT_PLAY, EVENT_RATE, EVENT_SKIP, PlayEvent, Track

WINDOW_SHORT_DAYS = 7
WINDOW_LONG_DAYS = 30
NEUTRAL_WEIGHT = 0.5


@dataclass(slots=True)
class TrackStats:
    plays_7d: int = 0
    plays_30d: int = 0
    plays_all: int = 0
    skips_30d: int = 0
    last_played: float | None = None
    loved: bool = False
    rating: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "plays_7d": self.plays_7d,
            "plays_30d": self.plays_30d,
            "plays_all": self.plays_all,
            "skips_30d": self.skips_30d,
            "last_played": self.last_played,
            "loved": self.loved,
            "rating": self.rating,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TrackStats:
        return cls(
            plays_7d=int(payload.get("plays_7d", 0) or 0),
            plays_30d=int(payload.get("plays_30d", 0) or 0),
            plays_all=int(payload.get("plays_all", 0) or 0),
            skips_30d=int(payload.get("skips_30d", 0) or 0),
            last_played=payload.get("last_played"),
            loved=bool(payload.get("loved", False)),
            rating=int(payload.get("rating", 0) or 0),
        )


@dataclass(slots=True)
class TasteProfile:
    user_id: str
    updated_at: float
    stats: dict[str, TrackStats] = field(default_factory=dict)
    genre_weights: dict[str, float] = field(default_factory=dict)
    artist_weights: dict[str, float] = field(default_factory=dict)
    feature_weights: dict[str, float] = field(default_factory=dict)
    cohort_weights: dict[str, float] = field(default_factory=dict)
    cooccurrence: dict[str, dict[str, float]] = field(default_factory=dict)
    total_plays: int = 0
    sessions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "updated_at": self.updated_at,
            "stats": {k: v.to_dict() for k, v in self.stats.items()},
            "genre_weights": self.genre_weights,
            "artist_weights": self.artist_weights,
            "feature_weights": self.feature_weights,
            "cohort_weights": self.cohort_weights,
            "cooccurrence": self.cooccurrence,
            "total_plays": self.total_plays,
            "sessions": self.sessions,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TasteProfile:
        return cls(
            user_id=str(payload.get("user_id", "")),
            updated_at=float(payload.get("updated_at", 0.0) or 0.0),
            stats={k: TrackStats.from_dict(v) for k, v in dict(payload.get("stats", {})).items()},
            genre_weights={str(k): float(v) for k, v in dict(payload.get("genre_weights", {})).items()},
            artist_weights={str(k): float(v) for k, v in dict(payload.get("artist_weights", {})).items()},
            feature_weights={str(k): float(v) for k, v in dict(payload.get("feature_weights", {})).items()},
            cohort_weights={str(k): float(v) for k, v in dict(payload.get("cohort_weights", {})).items()},
            cooccurrence={str(k): {str(i): float(w) for i, w in dict(v).items()} for k, v in dict(payload.get("cooccurrence", {})).items()},
            total_plays=int(payload.get("total_plays", 0) or 0),
            sessions=int(payload.get("sessions", 0) or 0),
        )

    def track_stats(self, track_id: str) -> TrackStats:
        return self.stats.get(track_id, TrackStats())

    def neighbours(self, track_id: str, limit: int = 50) -> list[tuple[str, float]]:
        pairs = self.cooccurrence.get(track_id, {})
        return sorted(pairs.items(), key=lambda item: item[1], reverse=True)[:limit]

    def cohort_weight(self, cohort: str) -> float:
        return self.cohort_weights.get(cohort, NEUTRAL_WEIGHT)

    def affinity(self, track: Track) -> float:
        stats = self.track_stats(track.id)
        score = 0.0
        if track.loved or stats.loved:
            score += 0.35
        score += 0.2 * min(1.0, stats.rating / 5.0)
        score += 0.3 * _log_norm(stats.plays_30d, cap=25)
        score -= 0.25 * _log_norm(stats.skips_30d, cap=10)
        if stats.last_played:
            age_days = (time.time() - stats.last_played) / 86_400
            score += 0.15 * math.exp(-age_days / 45.0)
        return max(0.0, min(1.0, score))

    def affinity_by_id(self, track_id: str, liked_ids: set[str]) -> float:
        stats = self.track_stats(track_id)
        score = 0.0
        if stats.loved or track_id in liked_ids:
            score += 0.35
        score += 0.2 * min(1.0, stats.rating / 5.0)
        score += 0.3 * _log_norm(stats.plays_30d, cap=25)
        score -= 0.25 * _log_norm(stats.skips_30d, cap=10)
        return max(0.0, min(1.0, score))


def build_profile(
    user_id: str,
    events: list[PlayEvent],
    tracks: dict[str, Track] | list[Track],
    *,
    session_gap_seconds: int = 1800,
    now: float | None = None,
) -> TasteProfile:
    moment = now if now is not None else time.time()
    index = tracks if isinstance(tracks, dict) else {track.id: track for track in tracks}
    stats: dict[str, TrackStats] = defaultdict(TrackStats)
    genre_raw: Counter[str] = Counter()
    artist_raw: Counter[str] = Counter()
    cohort_raw: Counter[str] = Counter()
    feature_raw: Counter[str] = Counter()
    cooccurrence: dict[str, Counter[str]] = defaultdict(Counter)
    ordered = sorted(events, key=lambda e: e.ts)
    session: list[str] = []
    session_last_ts = 0.0
    sessions_closed = 0

    for event in ordered:
        if session and (event.ts - session_last_ts) > session_gap_seconds:
            _close_session(session, cooccurrence)
            sessions_closed += 1
            session = []
        session.append(event.track_id)
        session_last_ts = event.ts
        entry = stats[event.track_id]
        if event.kind == EVENT_PLAY:
            entry.plays_all += 1
            if _within(event.ts, moment, WINDOW_SHORT_DAYS):
                entry.plays_7d += 1
            if _within(event.ts, moment, WINDOW_LONG_DAYS):
                entry.plays_30d += 1
            entry.last_played = max(entry.last_played or 0.0, event.ts)
            track = index.get(event.track_id)
            if track:
                for tag in _tags_of(track):
                    genre_raw[tag] += 1
                if track.artist:
                    artist_raw[track.artist] += 1
                if track.bpm:
                    feature_raw["bpm_bucket"] += 1
                feature_raw["duration_bucket"] += 1
            cohort_raw[f"slot:{_hour_bucket(event.ts)}"] += 1
        elif event.kind == EVENT_SKIP:
            if _within(event.ts, moment, WINDOW_LONG_DAYS):
                entry.skips_30d += 1
        elif event.kind == EVENT_LOVE:
            entry.loved = True
        elif event.kind == EVENT_RATE:
            entry.rating = max(entry.rating, event.rating)
    _close_session(session, cooccurrence)
    sessions_count = max(1, sessions_closed + 1)
    profile = TasteProfile(
        user_id=user_id,
        updated_at=moment,
        stats=dict(stats),
        genre_weights=_normalize(genre_raw),
        artist_weights=_normalize(artist_raw),
        feature_weights=_normalize(feature_raw),
        cohort_weights=_normalize(cohort_raw),
        cooccurrence={k: dict(v) for k, v in cooccurrence.items()},
        total_plays=sum(1 for e in ordered if e.kind == EVENT_PLAY),
        sessions=sessions_count,
    )
    return profile


def _close_session(session: list[str], cooccurrence: dict[str, Counter[str]]) -> None:
    unique = list(dict.fromkeys(session))
    for source in unique:
        for target in unique:
            if source == target:
                continue
            cooccurrence[source][target] += 1


def _tags_of(track: Track) -> list[str]:
    tags = [tag.strip().lower() for tag in track.tags if tag.strip()]
    if track.genre.strip():
        tags.append(track.genre.strip().lower())
    return list(dict.fromkeys(tags))


def _normalize(counter: Counter[str]) -> dict[str, float]:
    total = sum(counter.values())
    if not total:
        return {}
    top = max(counter.values())
    return {key: round(value / top, 4) for key, value in counter.items()}


def _within(ts: float, moment: float, days: int) -> bool:
    return moment - ts <= days * 86_400


def _hour_bucket(ts: float) -> str:
    return time.strftime("%H", time.localtime(ts))[:2]


def _log_norm(value: int, *, cap: int) -> float:
    if value <= 0:
        return 0.0
    return math.log1p(value) / math.log1p(cap)