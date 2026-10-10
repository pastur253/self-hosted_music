from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from .contexts import cohort_key
from .contexts import Context
from .models import Track
from .profiles import TasteProfile

DEFAULT_WEIGHTS: dict[str, float] = {
    "affinity": 0.34,
    "genre_match": 0.22,
    "cooccurrence": 0.24,
    "cohort_match": 0.10,
    "novelty": 0.06,
    "recency_boost": 0.04,
    "rating": 0.0,
}


@dataclass(frozen=True, slots=True)
class Features:
    affinity: float
    genre_match: float
    cooccurrence: float
    cohort_match: float
    novelty: float
    recency_boost: float
    rating: float

    def as_dict(self) -> dict[str, float]:
        return {
            "affinity": round(self.affinity, 4),
            "genre_match": round(self.genre_match, 4),
            "cooccurrence": round(self.cooccurrence, 4),
            "cohort_match": round(self.cohort_match, 4),
            "novelty": round(self.novelty, 4),
            "recency_boost": round(self.recency_boost, 4),
            "rating": round(self.rating, 4),
        }


@dataclass(frozen=True, slots=True)
class ScoredTrack:
    track: Track
    score: float
    features: Features
    reasons: tuple[str, ...]


def extract_features(
    track: Track,
    profile: TasteProfile,
    context: Context,
    *,
    liked_ids: set[str],
    now: float | None = None,
) -> Features:
    moment = now if now is not None else time.time()
    stats = profile.track_stats(track.id)
    affinity = profile.affinity_by_id(track.id, liked_ids)
    genre_match = _genre_match(track, profile)
    cooccurrence = _cooccurrence(track, profile, liked_ids)
    cohort_match = profile.cohort_weight(cohort_key(context))
    novelty = _novelty(track, stats.plays_all, stats.loved or track.loved or track.id in liked_ids)
    recency = _recency(track, moment)
    rating = min(1.0, stats.rating / 5.0)
    return Features(affinity, genre_match, cooccurrence, cohort_match, novelty, recency, rating)


def score_track(features: Features, weights: dict[str, float] | None = None) -> float:
    active = {**DEFAULT_WEIGHTS, **(weights or {})}
    total_weight = sum(v for k, v in active.items() if k != "rating" and v)
    if total_weight <= 0:
        return 0.0
    raw = 0.0
    for name, value in active.items():
        if name == "rating":
            continue
        raw += float(getattr(features, name)) * value
    score = raw / total_weight
    score = score + features.rating * active.get("rating", 0.0) * 0.2
    return max(0.0, min(1.5, score))


def score_candidates(
    tracks: list[Track],
    profile: TasteProfile,
    context: Context,
    *,
    liked_ids: set[str],
    weights: dict[str, float] | None = None,
    now: float | None = None,
) -> list[ScoredTrack]:
    result: list[ScoredTrack] = []
    for track in tracks:
        features = extract_features(track, profile, context, liked_ids=liked_ids, now=now)
        score = score_track(features, weights)
        result.append(ScoredTrack(track, score, features, explain(features, track)))
    return result


def explain(features: Features, track: Track) -> tuple[str, ...]:
    reasons: list[str] = []
    if features.cooccurrence > 0.35:
        reasons.append("cooccurrence:liked_track")
    if features.affinity >= 0.55:
        reasons.append(f"high_affinity:plays_30d={_safe(track.play_count)}")
    if features.genre_match > 0.4 and track.genre:
        reasons.append(f"genre:{track.genre.lower()}")
    if features.novelty > 0.6:
        reasons.append("novelty:rare_played")
    if features.cohort_match > 0.5:
        reasons.append("cohort:context")
    if track.loved:
        reasons.append("loved")
    if not reasons:
        reasons.append("baseline")
    return tuple(reasons[:3])


def metrics_diversity(tracks: list[Track]) -> float:
    if len(tracks) <= 1:
        return 1.0
    artists = {t.artist or t.id for t in tracks}
    albums = {t.album or t.id for t in tracks}
    genre_component = len(artists) / len(tracks)
    album_component = len(albums) / len(tracks)
    return round(max(0.0, min(1.0, (genre_component + album_component) / 2)), 4)


def metrics_novelty(tracks: list[Track], known_ids: set[str]) -> float:
    if not tracks:
        return 0.0
    fresh = sum(1 for t in tracks if t.id not in known_ids)
    return round(fresh / len(tracks), 4)


def metrics_repeat_rate(track_ids: list[str], recent_ids: set[str]) -> float:
    if not track_ids:
        return 0.0
    return round(sum(1 for tid in track_ids if tid in recent_ids) / len(track_ids), 4)


def _genre_match(track: Track, profile: TasteProfile) -> float:
    if not profile.genre_weights:
        return 0.5
    tags = [tag.lower() for tag in track.tags] + ([track.genre.lower()] if track.genre else [])
    if not tags:
        return 0.5
    values = [profile.genre_weights.get(tag, 0.0) for tag in dict.fromkeys(tags)]
    return max(values) if values else 0.5


def _cooccurrence(track: Track, profile: TasteProfile, liked_ids: set[str]) -> float:
    if not liked_ids:
        return 0.0
    pairs = profile.cooccurrence.get(track.id, {})
    if not pairs:
        return 0.0
    total = sum(pairs.values()) or 1
    liked_sum = sum(weight for tid, weight in pairs.items() if tid in liked_ids)
    return min(1.0, liked_sum / math.sqrt(total))


def _novelty(track: Track, plays_all: int, loved: bool) -> float:
    if loved:
        return 0.15
    if plays_all == 0:
        return 1.0
    return max(0.0, 1.0 - min(1.0, plays_all / 20.0))


def _recency(track: Track, moment: float) -> float:
    reference = track.last_played or track.date_added
    if not reference:
        return 0.0
    age_days = max(0.0, (moment - reference) / 86_400)
    return round(math.exp(-age_days / 120.0), 4)


def _safe(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0