from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from ..ai import AIEnsemble
from ..config import Settings
from ..domain.contexts import Context, build_context
from ..domain.generator import GenerationResult, Generator, build_request, quality_gate
from ..domain.models import MixDefinition, MixRun, Track, UserSettings
from ..domain.naming import describe
from ..domain.profiles import TasteProfile, build_profile
from ..domain.templates import get_template, render_title
from ..navidrome.subsonic import SubsonicClient
from ..storage.layout import Layout
from .events import EventStore
from .library import LibraryService
from .weather import WeatherService

LOGGER = logging.getLogger("mixcore.mix")

HISTORY_LIMIT = 5_000


@dataclass(slots=True)
class GenerateOutcome:
    mix_id: str
    title: str
    description: str
    track_ids: list[str]
    metrics: dict[str, float]
    mode: str
    enabled_modules: list[str]
    degraded_reason: str
    quality_problems: list[str]
    stage_counts: dict[str, int]
    context: dict[str, Any]
    playlist_id: str
    written: bool


class MixService:
    def __init__(
        self,
        settings: Settings,
        layout: Layout,
        client: SubsonicClient,
        library: LibraryService,
        events: EventStore,
        weather: WeatherService,
        ai: AIEnsemble | None = None,
    ) -> None:
        self._settings = settings
        self._layout = layout
        self._client = client
        self._library = library
        self._events = events
        self._weather = weather
        self._ai = ai or AIEnsemble([], max_influence=settings.llm_max_influence)
        self._generator = Generator()

    async def mode(self) -> tuple[str, list[str], str]:
        statuses = await self._ai.status()
        available = [s.name for s in statuses if s.available]
        unavailable = [f"{s.name}:{s.reason}" for s in statuses if not s.available]
        if self._settings.effective_synth_mode == "algo":
            return "algo", [], ";".join(unavailable)
        if available:
            return "hybrid", available, ";".join(unavailable)
        return "algo", [], ";".join(unavailable)

    def user(self, user_id: str) -> UserSettings:
        payload = self._layout.users.load() or {}
        entry = payload.get(user_id, {})
        return UserSettings.from_dict({"user_id": user_id, **entry})

    def save_user(self, settings: UserSettings) -> UserSettings:
        payload = self._layout.users.load() or {}
        payload[settings.user_id] = settings.to_dict()
        self._layout.users.save(payload)
        return settings

    def profile(self, user_id: str) -> TasteProfile | None:
        raw = self._layout.profile(user_id).load()
        return TasteProfile.from_dict(raw) if raw else None

    def rebuild_profile(self, user_id: str, *, now: float | None = None) -> TasteProfile:
        events = self._events.for_user(user_id, limit=HISTORY_LIMIT)
        tracks = self._library.index()
        profile = build_profile(user_id, events, tracks, now=now)
        self._layout.profile(user_id).save(profile.to_dict())
        return profile

    async def context_for(self, user_id: str) -> Context:
        settings = self.user(user_id)
        weather_code = "unknown"
        detail: dict[str, object] = {}
        stale = False
        if settings.weather_enabled:
            data = await self._weather.current(settings.latitude, settings.longitude)
            weather_code = await self._weather.code_for(settings.latitude, settings.longitude)
            detail = data
            stale = bool(data.get("stale"))
        mode, _, _ = await self.mode()
        return build_context(
            user_id,
            settings.timezone,
            weather=weather_code,
            weather_detail=detail,
            weather_stale=stale,
            mode=mode,
        )

    def recent_mix_track_ids(self, user_id: str, *, limit_runs: int = 6) -> set[str]:
        runs = self._layout.mix_runs().iter_range()
        collected: list[dict[str, Any]] = [record for record in runs if record.get("mix_id", "").startswith(f"{user_id}:")]
        collected.sort(key=lambda item: float(item.get("ts", 0)), reverse=True)
        excluded: set[str] = set()
        for record in collected[:limit_runs]:
            excluded.update(record.get("track_ids", []))
        return excluded

    async def generate(
        self,
        mix: MixDefinition,
        *,
        dry_run: bool = False,
        now: float | None = None,
        seed: int | None = None,
    ) -> GenerateOutcome:
        moment = now if now is not None else time.time()
        template = get_template(mix.template_code)
        if template is None:
            raise ValueError(f"Неизвестный шаблон синтеза: {mix.template_code!r}")
        profile = self.profile(mix.owner_id) or self.rebuild_profile(mix.owner_id, now=moment)
        context = await self.context_for(mix.owner_id)
        mode, modules, degraded = await self.mode()

        tracks = self._library.cached()
        if not tracks:
            tracks = await self._sync_library()
        known = {track.id for track in tracks}
        exclude_days = self._settings.no_repeat_days
        exclude = self._recent_exclusions(mix.owner_id, known, exclude_days, now=moment)
        liked = self._liked_ids(profile, self._library.starred_ids())
        effective_seed = seed if seed is not None else _period_seed(mix, moment)

        request = build_request(
            template,
            tracks,
            profile,
            context,
            length=mix.length or template.length,
            seed=effective_seed,
            exclude_ids=exclude,
            liked_ids=liked,
            known_ids=known,
            now=moment,
        )

        external_order: list[str] | None = None
        title_override = ""
        description_override = ""
        if mode != "algo":
            payload = [
                {"id": t.id, "title": t.title, "artist": t.artist, "tags": list(t.tags), "bpm": t.bpm}
                for t in request.tracks[:400]
            ]
            ai_result = await self._ai.enrich(
                context=f"{context.time_slot}/{context.weather}/{template.code}",
                tracks=payload,
            )
            if ai_result.available:
                external_order = ai_result.track_order
                title_override = ai_result.title
                description_override = ai_result.description
            else:
                degraded = ";".join(filter(None, [degraded, f"ai:{ai_result.reason}"]))

        if external_order and mode != "algo":
            request.external_order = external_order
            request.external_influence = self._settings.llm_max_influence

        result: GenerationResult = self._generator.run(
            request,
            mode="algo" if external_order is None else mode,
            enabled_modules=modules,
            degraded_reason=degraded,
        )

        title = title_override or render_title(template, context, extra={"date": _date(moment)})
        description = description_override or describe(result.tracks, context, title)
        playlist_id = mix.navidrome_playlist_id
        written = False
        if not dry_run and result.track_ids:
            playlist_id = await self._write_playlist(playlist_id, mix, title, description, result.track_ids)
            written = True

        problems = quality_gate(result.metrics)
        run = MixRun(
            mix_id=mix.mix_id,
            ts=moment,
            mode=result.mode,
            enabled_modules=tuple(result.enabled_modules),
            degraded_reason=result.degraded_reason,
            seed=result.seed,
            context=result.context,
            track_ids=tuple(result.track_ids),
            metrics=result.metrics,
        )
        self._layout.mix_runs().append(run.to_dict(), timestamp=moment)
        self._layout.outbox().append(
            {
                "topic": "mix.generated",
                "mix_id": mix.mix_id,
                "ts": moment,
                "mode": result.mode,
                "title": title,
                "track_count": len(result.track_ids),
            }
        )
        return GenerateOutcome(
            mix_id=mix.mix_id,
            title=title,
            description=description,
            track_ids=result.track_ids,
            metrics=result.metrics,
            mode=result.mode,
            enabled_modules=result.enabled_modules,
            degraded_reason=result.degraded_reason,
            quality_problems=problems,
            stage_counts=result.stage_counts,
            context=result.context,
            playlist_id=playlist_id,
            written=written,
        )

    async def _sync_library(self) -> list[Track]:
        await self._library.sync()
        return self._library.cached()

    def _recent_exclusions(
        self,
        user_id: str,
        known: set[str],
        days: int,
        *,
        now: float | None = None,
    ) -> set[str]:
        if days <= 0:
            return set()
        horizon = (now if now is not None else time.time()) - days * 86_400
        excluded: set[str] = set()
        for record in self._layout.mix_runs().iter_range(since=horizon):
            if not record.get("mix_id", "").startswith(f"{user_id}:"):
                continue
            excluded.update(track_id for track_id in record.get("track_ids", []) if track_id in known)
        return excluded

    def _liked_ids(self, profile: TasteProfile, starred: set[str]) -> set[str]:
        liked = set(starred)
        liked.update(track_id for track_id, stats in profile.stats.items() if stats.loved)
        liked.update(track_id for track_id, stats in profile.stats.items() if stats.rating >= 4)
        return liked

    async def _write_playlist(
        self,
        playlist_id: str,
        mix: MixDefinition,
        title: str,
        description: str,
        track_ids: list[str],
    ) -> str:
        if playlist_id:
            await self._client.replace_playlist_tracks(playlist_id, track_ids)
            await self._client.update_playlist(playlist_id, name=title, comment=description)
            return playlist_id
        created = await self._client.create_playlist(name=title, track_ids=track_ids, public=True)
        await self._client.update_playlist(created, name=title, comment=description)
        updated = mix.to_dict()
        updated["navidrome_playlist_id"] = created
        self._layout.mix(mix.mix_id).save(updated)
        return created


def _period_seed(mix: MixDefinition, moment: float) -> int:
    if mix.template_code in ("daily_mix", "weather_mix", "calm_morning", "night_drive"):
        return int(moment // 86_400)
    return int(moment // (7 * 86_400))


def _date(moment: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(moment))