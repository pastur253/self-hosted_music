from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .scoring import ScoredTrack

DEFAULT_MAX_ARTIST_SHARE = 0.34
DEFAULT_MAX_ALBUM_SHARE = 0.25


@dataclass(frozen=True, slots=True)
class DiversityRules:
    max_artist_share: float = DEFAULT_MAX_ARTIST_SHARE
    max_album_share: float = DEFAULT_MAX_ALBUM_SHARE
    max_consecutive_same_artist: int = 2
    prefer_energy_continuity: bool = True


def rerank(
    scored: list[ScoredTrack],
    *,
    length: int,
    rules: DiversityRules | None = None,
    seed: int = 0,
    penalty: float = 0.05,
) -> list[ScoredTrack]:
    """Жадный отбор с ограничениями разнообразия; детерминирован при фиксированном seed."""
    active = rules or DiversityRules()
    pool = sorted(scored, key=lambda item: (-item.score, item.track.id))
    if not pool:
        return []

    jitter = {item.track.id: _stable_jitter(seed, item.track.id) * penalty for item in pool}
    remaining = list(pool)
    chosen: list[ScoredTrack] = []
    artist_count: dict[str, int] = {}
    album_count: dict[str, int] = {}
    last_artist: str = ""
    streak = 0

    while remaining and len(chosen) < length:
        best_index = 0
        best_value = float("-inf")
        for index, item in enumerate(remaining):
            track = item.track
            artist = track.artist or track.id
            album = track.album or track.id
            if chosen:
                projected = len(chosen) + 1
                if artist_count.get(artist, 0) + 1 > active.max_artist_share * projected + 1e-9:
                    continue
                if album_count.get(album, 0) + 1 > active.max_album_share * projected + 1e-9:
                    continue
                if artist == last_artist and streak >= active.max_consecutive_same_artist:
                    continue
            value = item.score - jitter.get(track.id, 0.0)
            if chosen and active.prefer_energy_continuity:
                value -= _bpm_gap_penalty(chosen[-1], item)
            if value > best_value:
                best_value = value
                best_index = index
        picked = remaining.pop(best_index)
        chosen.append(picked)
        artist = picked.track.artist or picked.track.id
        album = picked.track.album or picked.track.id
        artist_count[artist] = artist_count.get(artist, 0) + 1
        album_count[album] = album_count.get(album, 0) + 1
        if artist == last_artist:
            streak += 1
        else:
            last_artist = artist
            streak = 1
    return chosen


def sequential_plan(scored: list[ScoredTrack], *, length: int) -> list[ScoredTrack]:
    ordered = sorted(scored, key=lambda item: (-item.score, item.track.id))
    return ordered[:length]


def apply_external_order(
    scored: list[ScoredTrack],
    order: list[str],
    *,
    length: int,
    limit_influence: float,
) -> list[ScoredTrack]:
    """Мягкое влияние внешнего источника (ИИ): влияет только порядок, жёсткие ограничения сохраняются (FR-3A.11)."""
    if limit_influence <= 0 or not order:
        return sequential_plan(scored, length=length)
    weight = min(1.0, limit_influence)
    ranked_ids = {tid: index for index, tid in enumerate(order)}
    rescored: list[ScoredTrack] = []
    for item in scored:
        bonus = 0.0
        if item.track.id in ranked_ids:
            position = ranked_ids[item.track.id]
            bonus = weight * (1.0 - position / max(1, len(order)))
        rescored.append(ScoredTrack(item.track, min(1.5, item.score + bonus), item.features, item.reasons))
    return rerank(rescored, length=length, seed=0, penalty=0.0)


def _stable_jitter(seed: int, track_id: str) -> float:
    digest = hashlib.blake2b(f"{seed}:{track_id}".encode(), digest_size=4).digest()
    return int.from_bytes(digest, "big") / 0xFFFFFFFF


def _bpm_gap_penalty(previous: ScoredTrack, current: ScoredTrack) -> float:
    left = previous.track.bpm
    right = current.track.bpm
    if not left or not right:
        return 0.0
    gap = abs(left - right) / max(left, right)
    return min(0.25, gap * 0.25)


def diversity_report(scored: list[ScoredTrack], picked: list[ScoredTrack]) -> dict[str, float]:
    picked_ids = {item.track.id for item in picked}
    total = len(scored) or 1
    return {
        "candidates": float(len(scored)),
        "selected": float(len(picked)),
        "coverage": round(len(picked_ids) / total, 4),
    }