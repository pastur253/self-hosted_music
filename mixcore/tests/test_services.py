from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from mixcore.config import Settings
from mixcore.domain.models import EVENT_PLAY, CollabMember, PlayEvent, Track, UserSettings
from mixcore.domain.profiles import build_profile
from mixcore.services.collab import CollabService, NotFound, PermissionDenied, apply_op
from mixcore.services.events import EventStore
from mixcore.services.library import LibraryService
from mixcore.services.mix_service import MixService
from mixcore.services.weather import NullWeatherProvider, WeatherService
from mixcore.storage.layout import Layout

NOW = 1_726_000_000.0


class FakeSubsonic:
    def __init__(self) -> None:
        self.playlists: dict[str, dict[str, object]] = {}
        self.events: list[dict[str, object]] = []

    async def ping(self) -> bool:
        return True

    async def health(self) -> dict[str, object]:
        return {"status": "up"}

    async def create_playlist(self, *, name: str, track_ids=(), public: bool = True) -> str:
        pid = f"pl-{len(self.playlists) + 1}"
        self.playlists[pid] = {"id": pid, "name": name, "tracks": list(track_ids), "public": public}
        return pid

    async def update_playlist(self, playlist_id: str, *, name: str | None = None, comment: str | None = None) -> None:
        entry = self.playlists.setdefault(playlist_id, {"id": playlist_id, "tracks": []})
        if name is not None:
            entry["name"] = name
        if comment is not None:
            entry["comment"] = comment

    async def replace_playlist_tracks(self, playlist_id: str, track_ids) -> None:
        entry = self.playlists.setdefault(playlist_id, {"id": playlist_id})
        entry["tracks"] = list(track_ids)

    async def search(self, query: str, *, limit: int = 500, offset: int = 0) -> list[dict[str, object]]:
        return []

    async def get_starred(self) -> list[dict[str, object]]:
        return []


def _tracks(count: int = 90) -> list[Track]:
    genres = ["downtempo", "techno", "jazz", "ambient", "rock"]
    return [
        Track(
            id=f"t-{i}",
            title=f"track {i}",
            artist=f"artist-{i % 15}",
            album=f"album-{i % 25}",
            artist_id=f"a-{i % 15}",
            genre=genres[i % len(genres)],
            duration=200 + i,
            bpm=70 + (i % 90),
            year=1980 + (i % 45),
            date_added=NOW - (i % 90) * 86_400,
            tags=(genres[i % len(genres)],),
        )
        for i in range(count)
    ]


def _runtime(tmp_path: Path) -> tuple[MixService, CollabService, Layout, FakeSubsonic]:
    settings = Settings.from_env({"MIX_STATE_DIR": str(tmp_path / "state")})
    layout = Layout.create(settings.state_dir)
    client = FakeSubsonic()
    tracks = _tracks()
    layout.track_meta.save({"synced_at": NOW, "tracks": [t.to_dict() for t in tracks]})
    library = LibraryService(layout, client)  # type: ignore[arg-type]
    events = EventStore(layout)
    weather = WeatherService(layout, NullWeatherProvider())
    service = MixService(settings, layout, client, library, events, weather)  # type: ignore[arg-type]
    collab = CollabService(layout, client)  # type: ignore[arg-type]
    service.save_user(UserSettings(user_id="alice", timezone="UTC", role="user"))
    for index, track in enumerate(tracks[:30]):
        events.record(PlayEvent(user_id="alice", track_id=track.id, kind=EVENT_PLAY, ts=NOW - index * 1800))
    service.rebuild_profile("alice", now=NOW)
    return service, collab, layout, client


def test_generate_writes_playlist_to_navidrome(tmp_path: Path) -> None:
    from mixcore.domain.models import MixDefinition

    service, _, _, client = _runtime(tmp_path)
    mix = MixDefinition(
        mix_id="alice:daily_mix",
        name="Микс дня",
        owner_id="alice",
        template_code="daily_mix",
        length=25,
    )
    outcome = asyncio.run(service.generate(mix, now=NOW))

    assert outcome.written is True
    assert outcome.playlist_id
    assert len(outcome.track_ids) == 25
    assert len(set(outcome.track_ids)) == 25
    assert client.playlists[outcome.playlist_id]["tracks"] == outcome.track_ids
    assert client.playlists[outcome.playlist_id]["comment"]


def test_generate_is_deterministic_for_same_seed(tmp_path: Path) -> None:
    from mixcore.domain.models import MixDefinition

    outcomes = []
    for index in range(2):
        service, _, _, _ = _runtime(tmp_path / f"case{index}")
        mix = MixDefinition(
            mix_id="alice:energy",
            name="Энергия",
            owner_id="alice",
            template_code="energy",
            length=20,
        )
        outcomes.append(asyncio.run(service.generate(mix, dry_run=True, now=NOW, seed=99)))
    assert outcomes[0].track_ids == outcomes[1].track_ids
    assert outcomes[0].metrics == outcomes[1].metrics


def test_jitter_is_stable_across_processes() -> None:
    import importlib
    import subprocess
    import sys

    code = (
        "import sys; sys.path.insert(0, 'mixcore/src');"
        "from mixcore.domain.diversity import _stable_jitter;"
        "print(_stable_jitter(7, 't-42'))"
    )
    first = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    second = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert first.stdout.strip() == second.stdout.strip()
    del importlib
    from mixcore.domain.diversity import _stable_jitter

    assert 0.0 <= _stable_jitter(7, "t-42") <= 1.0


def test_dry_run_does_not_touch_navidrome(tmp_path: Path) -> None:
    service, _, _, client = _runtime(tmp_path)
    from mixcore.domain.models import MixDefinition

    mix = MixDefinition(
        mix_id="alice:daily_mix",
        name="Микс дня",
        owner_id="alice",
        template_code="daily_mix",
        length=15,
    )
    outcome = asyncio.run(service.generate(mix, dry_run=True, now=NOW))
    assert outcome.written is False
    assert client.playlists == {}


def test_generated_mix_is_reported_in_algo_mode(tmp_path: Path) -> None:
    service, _, layout, _ = _runtime(tmp_path)
    from mixcore.domain.models import MixDefinition

    mix = MixDefinition(
        mix_id="alice:daily_mix",
        name="Микс дня",
        owner_id="alice",
        template_code="daily_mix",
        length=10,
    )
    outcome = asyncio.run(service.generate(mix, dry_run=True, now=NOW))
    assert outcome.mode == "algo"
    assert outcome.enabled_modules == []
    runs = list(layout.mix_runs().iter_range())
    assert runs[-1]["mode"] == "algo"
    assert runs[-1]["track_ids"]


def test_repeat_tracks_are_excluded_on_second_run(tmp_path: Path) -> None:
    service, _, _, _ = _runtime(tmp_path)
    from mixcore.domain.models import MixDefinition

    mix = MixDefinition(
        mix_id="alice:daily_mix",
        name="Микс дня",
        owner_id="alice",
        template_code="daily_mix",
        length=10,
    )
    first = asyncio.run(service.generate(mix, now=NOW))
    second = asyncio.run(service.generate(mix, now=NOW))
    assert not set(first.track_ids).intersection(second.track_ids)
    assert second.metrics["repeat_rate"] == 0.0


def test_collab_operations_are_journalled_and_synced(tmp_path: Path) -> None:
    _, collab, layout, client = _runtime(tmp_path)
    playlist = asyncio.run(collab.create(owner_id="alice", name="Общий", track_ids=["t-1", "t-2"]))
    collab.set_members(playlist.playlist_id, "alice", [("bob", "editor"), ("carol", "viewer")])

    outcome = asyncio.run(
        collab.apply_operation(
            playlist.playlist_id,
            actor_id="bob",
            op="track.added",
            payload={"track_ids": ["t-3"], "position": 1},
        )
    )
    assert outcome.applied is True
    assert collab.tracks(playlist.playlist_id) == ["t-1", "t-3", "t-2"]
    assert client.playlists[playlist.navidrome_playlist_id]["tracks"] == ["t-1", "t-3", "t-2"]

    duplicate = asyncio.run(
        collab.apply_operation(
            playlist.playlist_id,
            actor_id="bob",
            op="track.added",
            payload={"track_ids": ["t-3"]},
            op_id=outcome.op.op_id,
        )
    )
    assert duplicate.duplicate is True

    ops = collab.ops_since(playlist.playlist_id, 0)
    assert [op["seq"] for op in ops] == sorted(op["seq"] for op in ops)
    assert len(layout.collab_ops(playlist.playlist_id).read_all()) == 2


def test_collab_permissions_are_enforced(tmp_path: Path) -> None:
    _, collab, _, _ = _runtime(tmp_path)
    playlist = asyncio.run(collab.create(owner_id="alice", name="Общий"))
    collab.set_members(playlist.playlist_id, "alice", [("bob", "editor"), ("carol", "viewer")])

    with pytest.raises(PermissionDenied):
        asyncio.run(
            collab.apply_operation(
                playlist.playlist_id, actor_id="carol", op="track.added", payload={"track_ids": ["t-9"]}
            )
        )

    with pytest.raises(PermissionDenied):
        collab.set_members(playlist.playlist_id, "bob", [("dave", "editor")])

    with pytest.raises(NotFound):
        asyncio.run(
            collab.apply_operation("pl-missing", actor_id="alice", op="track.added", payload={"track_ids": ["t-1"]})
        )


def test_ops_since_supports_reconnect(tmp_path: Path) -> None:
    _, collab, _, _ = _runtime(tmp_path)
    playlist = asyncio.run(collab.create(owner_id="alice", name="Общий"))
    for index in range(5):
        asyncio.run(
            collab.apply_operation(
                playlist.playlist_id,
                actor_id="alice",
                op="track.added",
                payload={"track_ids": [f"t-{index}"]},
            )
        )
    tail = collab.ops_since(playlist.playlist_id, 3)
    assert [op["seq"] for op in tail] == [4, 5]


def test_apply_op_semantics() -> None:
    from mixcore.domain.models import CollabOp

    def op(name: str, payload: dict[str, object], seq: int = 1) -> CollabOp:
        return CollabOp(
            playlist_id="pl-1", seq=seq, op=name, actor_id="alice", op_id=f"op-{seq}", ts=time.time(), payload=payload
        )

    tracks = ["a", "b", "c"]
    tracks = apply_op(tracks, op("track.added", {"track_ids": ["d"], "position": 1}))
    assert tracks == ["a", "d", "b", "c"]
    tracks = apply_op(tracks, op("track.removed", {"indexes": [0]}, seq=2))
    assert tracks == ["d", "b", "c"]
    tracks = apply_op(tracks, op("track.moved", {"from": 2, "to": 0}, seq=3))
    assert tracks == ["c", "d", "b"]
    tracks = apply_op(tracks, op("playlist.replaced", {"track_ids": ["z"]}, seq=4))
    assert tracks == ["z"]


def test_weather_service_degrades_to_unknown(tmp_path: Path) -> None:
    layout = Layout.create(tmp_path)
    service = WeatherService(layout, NullWeatherProvider())
    assert asyncio.run(service.code_for(None, None)) == "unknown"
    data = asyncio.run(service.current(None, None))
    assert data["stale"] is True


def test_profile_rebuild_is_stored_and_reused(tmp_path: Path) -> None:
    service, _, layout, _ = _runtime(tmp_path)
    profile = service.profile("alice")
    assert profile is not None
    assert layout.profile("alice").exists()
    assert profile.total_plays == 30


def test_user_settings_roundtrip(tmp_path: Path) -> None:
    service, _, _, _ = _runtime(tmp_path)
    service.save_user(UserSettings(user_id="bob", timezone="Europe/Berlin", weather_enabled=True, latitude=52.5, longitude=13.4))
    stored = service.user("bob")
    assert stored.timezone == "Europe/Berlin"
    assert stored.weather_enabled is True


def test_collab_members_persisted(tmp_path: Path) -> None:
    _, collab, layout, _ = _runtime(tmp_path)
    playlist = asyncio.run(collab.create(owner_id="alice", name="Общий"))
    collab.set_members(playlist.playlist_id, "alice", [("bob", "editor")])
    raw = layout.collab_members.load() or {}
    assert CollabMember.from_dict(raw[playlist.playlist_id][1]).role == "editor"