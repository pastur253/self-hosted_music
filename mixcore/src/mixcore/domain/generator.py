from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .contexts import Context, cohort_key
from .diversity import DiversityRules, rerank, sequential_plan
from .models import Track
from .profiles import TasteProfile
from .scoring import ScoredTrack, metrics_diversity, metrics_novelty, metrics_repeat_rate, score_candidates
from .templates import TemplateSpec

PLAY_SKIP_THRESHOLD_RATIO = 0.7


@dataclass(slots=True)
class GenerationRequest:
    template: TemplateSpec
    tracks: list[Track]
    profile: TasteProfile
    context: Context
    length: int
    seed: int
    exclude_ids: set[str] = field(default_factory=set)
    liked_ids: set[str] = field(default_factory=set)
    known_ids: set[str] = field(default_factory=set)
    external_order: list[str] | None = None
    external_influence: float = 0.0
    now: float | None = None
    candidate_pool: int = 400


@dataclass(slots=True)
class GenerationResult:
    track_ids: list[str]
    tracks: list[Track]
    metrics: dict[str, float]
    mode: str
    enabled_modules: list[str]
    degraded_reason: str
    seed: int
    context: dict[str, Any]
    stage_counts: dict[str, int]
    reasons: dict[str, list[str]]


class Generator:
    def __init__(self, *, candidate_pool: int = 400) -> None:
        self.candidate_pool = candidate_pool

    def run(
        self,
        request: GenerationRequest,
        *,
        mode: str = "algo",
        enabled_modules: Iterable[str] = (),
        degraded_reason: str = "",
    ) -> GenerationResult:
        moment = request.now if request.now is not None else time.time()
        stage_counts: dict[str, int] = {}

        candidates = self._candidates(request)
        stage_counts["candidates"] = len(candidates)

        filtered = [t for t in candidates if self._passes_filters(t, request)]
        stage_counts["after_filters"] = len(filtered)

        excluded = self._apply_exclusions(filtered, request)
        stage_counts["after_exclusions"] = len(excluded)

        scored = score_candidates(
            excluded,
            request.profile,
            request.context,
            liked_ids=request.liked_ids,
            weights=request.template.weights,
            now=moment,
        )
        pool = self._shortlist(scored, request.candidate_pool)
        stage_counts["after_scoring"] = len(pool)

        if mode == "algo" or not request.external_order:
            picked = rerank(pool, length=request.length, rules=DiversityRules(), seed=request.seed)
        else:
            from .diversity import apply_external_order

            picked = apply_external_order(
                pool,
                request.external_order,
                length=request.length,
                limit_influence=request.external_influence,
            )
        stage_counts["selected"] = len(picked)

        metrics = self._metrics(picked, request)
        reasons = {item.track.id: list(item.reasons) for item in picked}
        return GenerationResult(
            track_ids=[item.track.id for item in picked],
            tracks=[item.track for item in picked],
            metrics=metrics,
            mode=mode,
            enabled_modules=list(enabled_modules),
            degraded_reason=degraded_reason,
            seed=request.seed,
            context={
                "user_id": request.context.user_id,
                "time_slot": request.context.time_slot,
                "weather": request.context.weather,
                "cohort": cohort_key(request.context),
                "template": request.template.code,
                "local_time": request.context.local_time,
            },
            stage_counts=stage_counts,
            reasons=reasons,
        )

    def _candidates(self, request: GenerationRequest) -> list[Track]:
        return list(request.tracks)

    def _passes_filters(self, track: Track, request: GenerationRequest) -> bool:
        filters = request.template.filters
        stats = request.profile.track_stats(track.id)
        plays_all = stats.plays_all or track.play_count

        if "max_plays_all" in filters and plays_all > int(filters["max_plays_all"]):
            return False
        if "min_plays_all" in filters and plays_all < int(filters["min_plays_all"]):
            return False
        if filters.get("loved_only") and not (stats.loved or track.loved):
            return False
        if "bpm_min" in filters and (not track.bpm or track.bpm < float(filters["bpm_min"])):
            return False
        if "bpm_max" in filters and (not track.bpm or track.bpm > float(filters["bpm_max"])):
            return False
        if "min_duration" in filters and track.duration < float(filters["min_duration"]):
            return False
        if "max_duration" in filters and track.duration > float(filters["max_duration"]):
            return False
        if "decade" in filters:
            decade = int(filters["decade"])
            if not track.year or not (decade <= track.year < decade + 10):
                return False
        if "days_added" in filters:
            days = float(filters["days_added"])
            reference = track.date_added or 0.0
            if not reference or (request.now or time.time()) - reference > days * 86_400:
                return False
        if "plays_7d_min" in filters and stats.plays_7d < int(filters["plays_7d_min"]):
            return False
        if "min_days_since_play" in filters:
            last = stats.last_played or track.last_played
            if not last:
                return False
            days = float(filters["min_days_since_play"])
            if (request.now or time.time()) - last < days * 86_400:
                return False
        floor = filters.get("novelty_floor")
        if floor is not None and plays_all > 3:
            return False
        return True

    def _apply_exclusions(self, tracks: list[Track], request: GenerationRequest) -> list[Track]:
        if not request.exclude_ids:
            return tracks
        return [t for t in tracks if t.id not in request.exclude_ids]

    def _shortlist(self, scored: list[ScoredTrack], limit: int) -> list[ScoredTrack]:
        if limit <= 0 or len(scored) <= limit:
            return scored
        return sorted(scored, key=lambda item: (-item.score, item.track.id))[:limit]

    def _metrics(self, picked: list[ScoredTrack], request: GenerationRequest) -> dict[str, float]:
        tracks = [item.track for item in picked]
        return {
            "diversity": metrics_diversity(tracks),
            "novelty": metrics_novelty(tracks, request.known_ids),
            "repeat_rate": metrics_repeat_rate([item.track.id for item in picked], request.exclude_ids),
        }


def build_request(
    template: TemplateSpec,
    tracks: list[Track],
    profile: TasteProfile,
    context: Context,
    *,
    length: int,
    seed: int,
    exclude_ids: set[str] | None = None,
    liked_ids: set[str] | None = None,
    known_ids: set[str] | None = None,
    now: float | None = None,
    external_order: list[str] | None = None,
    external_influence: float = 0.0,
) -> GenerationRequest:
    return GenerationRequest(
        template=template,
        tracks=tracks,
        profile=profile,
        context=context,
        length=max(1, length),
        seed=seed,
        exclude_ids=set(exclude_ids or ()),
        liked_ids=set(liked_ids or ()),
        known_ids=set(known_ids or ()),
        now=now,
        external_order=external_order,
        external_influence=external_influence,
    )


def quality_gate(metrics: dict[str, float], *, min_diversity: float = 0.6, min_novelty: float = 0.3) -> list[str]:
    problems: list[str] = []
    if metrics.get("diversity", 0.0) < min_diversity:
        problems.append(f"diversity={metrics.get('diversity')} < {min_diversity}")
    if metrics.get("novelty", 0.0) < min_novelty:
        problems.append(f"novelty={metrics.get('novelty')} < {min_novelty}")
    if metrics.get("repeat_rate", 0.0) > 0.05:
        problems.append(f"repeat_rate={metrics.get('repeat_rate')} > 0.05")
    return problems


__all__ = [
    "GenerationRequest",
    "GenerationResult",
    "Generator",
    "build_request",
    "quality_gate",
    "sequential_plan",
]