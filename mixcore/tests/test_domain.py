from __future__ import annotations

from mixcore.domain.contexts import build_context, classify_weather, resolve_time_slot
from mixcore.domain.generator import Generator, build_request, quality_gate
from mixcore.domain.models import EVENT_PLAY, PlayEvent, Track
from mixcore.domain.profiles import build_profile
from mixcore.domain.templates import get_template

NOW = 1_726_000_000.0


def _tracks(count: int = 120) -> list[Track]:
    genres = ["downtempo", "techno", "jazz", "ambient", "rock"]
    artists = [f"artist-{i % 12}" for i in range(count)]
    return [
        Track(
            id=f"t-{i}",
            title=f"track {i}",
            artist=artists[i],
            album=f"album-{i % 20}",
            artist_id=f"a-{i % 12}",
            album_id=f"al-{i % 20}",
            genre=genres[i % len(genres)],
            duration=180 + i,
            bpm=70 + (i % 80),
            year=1970 + (i % 55),
            date_added=NOW - (i % 60) * 86_400,
            tags=(genres[i % len(genres)],),
        )
        for i in range(count)
    ]


def _events(tracks: list[Track]) -> list[PlayEvent]:
    events: list[PlayEvent] = []
    for index, track in enumerate(tracks[:40]):
        events.append(PlayEvent(user_id="u1", track_id=track.id, kind=EVENT_PLAY, ts=NOW - index * 3600))
    for track in tracks[:10]:
        events.append(PlayEvent(user_id="u1", track_id=track.id, kind="love", ts=NOW - 100))
    return events


def _context(weather: str = "rain"):
    return build_context("u1", "Europe/Moscow", weather=weather, mode="algo", now=NOW)


def test_time_slot_resolution() -> None:
    from datetime import datetime

    assert resolve_time_slot(datetime(2026, 1, 1, 8)) == "morning"
    assert resolve_time_slot(datetime(2026, 1, 1, 13)) == "day"
    assert resolve_time_slot(datetime(2026, 1, 1, 19)) == "evening"
    assert resolve_time_slot(datetime(2026, 1, 1, 2)) == "night"


def test_weather_classification() -> None:
    assert classify_weather(0) == "clear"
    assert classify_weather(61) == "rain"
    assert classify_weather(95) == "storm"
    assert classify_weather(71) == "snow"
    assert classify_weather(None) == "unknown"
    assert classify_weather(0, temp_c=35) == "extreme_heat"


def test_profile_builds_from_events() -> None:
    tracks = _tracks()
    profile = build_profile("u1", _events(tracks), tracks, now=NOW)
    assert profile.total_plays == 40
    assert profile.genre_weights
    assert profile.cooccurrence
    assert profile.stats[tracks[0].id].plays_all == 1


def test_algo_generation_is_deterministic() -> None:
    tracks = _tracks()
    profile = build_profile("u1", _events(tracks), tracks, now=NOW)
    spec = get_template("daily_mix")
    assert spec is not None
    request = build_request(spec, tracks, profile, _context(), length=30, seed=42, now=NOW)
    first = Generator().run(request, mode="algo")
    second = Generator().run(request, mode="algo")
    assert first.track_ids == second.track_ids
    assert first.metrics == second.metrics


def test_algo_mode_has_no_ai_contribution() -> None:
    tracks = _tracks()
    profile = build_profile("u1", _events(tracks), tracks, now=NOW)
    spec = get_template("energy")
    assert spec is not None
    base = Generator().run(build_request(spec, tracks, profile, _context(), length=25, seed=7, now=NOW), mode="algo")
    with_external = Generator().run(
        build_request(
            spec,
            tracks,
            profile,
            _context(),
            length=25,
            seed=7,
            now=NOW,
            external_order=[t.id for t in tracks[:20]],
            external_influence=0.0,
        ),
        mode="algo",
    )
    assert base.track_ids == with_external.track_ids


def test_quality_gate_reports_repetition() -> None:
    problems = quality_gate({"diversity": 0.9, "novelty": 0.8, "repeat_rate": 0.4})
    assert any("repeat_rate" in problem for problem in problems)


def test_no_repeat_exclusion_applied() -> None:
    tracks = _tracks(40)
    profile = build_profile("u1", [], tracks, now=NOW)
    spec = get_template("daily_mix")
    assert spec is not None
    excluded = {track.id for track in tracks[:20]}
    result = Generator().run(
        build_request(spec, tracks, profile, _context(), length=15, seed=1, exclude_ids=excluded, known_ids={t.id for t in tracks}, now=NOW)
    )
    assert not excluded.intersection(result.track_ids)
    assert result.metrics["repeat_rate"] == 0.0


def test_forgotten_favorites_filter() -> None:
    tracks = _tracks(30)
    events = [PlayEvent(user_id="u1", track_id=t.id, kind=EVENT_PLAY, ts=NOW - 400 * 86_400) for t in tracks[:5]]
    events += [PlayEvent(user_id="u1", track_id=t.id, kind="love", ts=NOW - 400 * 86_400) for t in tracks[:5]]
    profile = build_profile("u1", events, tracks, now=NOW)
    spec = get_template("forgotten_favorites")
    assert spec is not None
    result = Generator().run(build_request(spec, tracks, profile, _context(), length=5, seed=3, now=NOW))
    assert set(result.track_ids).issubset({t.id for t in tracks[:5]})


def test_catalog_covers_required_templates() -> None:
    from mixcore.domain.templates import all_specs

    codes = {spec.code for spec in all_specs()}
    required = {
        "discover_weekly",
        "daily_mix",
        "weather_mix",
        "energy",
        "calm_morning",
        "night_drive",
        "retro_cohort",
        "release_radar",
        "forgotten_favorites",
        "loved_only",
    }
    assert required.issubset(codes)