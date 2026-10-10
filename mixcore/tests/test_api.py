from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from mixcore.config import Settings  # noqa: E402

NOW = 1_726_000_000.0


class FakeSubsonic:
    instances: list["FakeSubsonic"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.playlists: dict[str, dict[str, object]] = {}
        self.search_calls = 0
        FakeSubsonic.instances.append(self)

    async def ping(self) -> bool:
        return True

    async def health(self) -> dict[str, object]:
        return {"status": "up"}

    async def search(self, query: str, *, limit: int = 500, offset: int = 0) -> list[dict[str, object]]:
        self.search_calls += 1
        if offset:
            return []
        return [
            {
                "id": f"t-{i}",
                "title": f"track {i}",
                "artist": f"artist-{i % 8}",
                "album": f"album-{i % 12}",
                "artistId": f"a-{i % 8}",
                "albumId": f"al-{i % 12}",
                "genre": ["techno", "jazz", "ambient", "rock", "downtempo"][i % 5],
                "duration": 200 + i,
                "bpm": 60 + (i % 140),
                "year": 1985 + (i % 35),
            }
            for i in range(120)
        ]

    async def get_starred(self) -> list[dict[str, object]]:
        return [{"id": "t-1", "starred": True}]

    async def create_playlist(self, *, name: str, track_ids=(), public: bool = True) -> str:
        pid = f"pl-{len(self.playlists) + 1}"
        self.playlists[pid] = {"id": pid, "name": name, "tracks": list(track_ids)}
        return pid

    async def update_playlist(self, playlist_id: str, *, name: str | None = None, comment: str | None = None) -> None:
        entry = self.playlists.setdefault(playlist_id, {"id": playlist_id, "tracks": []})
        if name:
            entry["name"] = name
        if comment:
            entry["comment"] = comment

    async def replace_playlist_tracks(self, playlist_id: str, track_ids) -> None:
        entry = self.playlists.setdefault(playlist_id, {"id": playlist_id})
        entry["tracks"] = list(track_ids)

    async def aclose(self) -> None:
        return None


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings.from_env({"MIX_STATE_DIR": str(tmp_path / "state")})
    from mixcore.api.app import create_app

    with patch("mixcore.runtime.SubsonicClient", FakeSubsonic):
        app = create_app(settings)
        with TestClient(app) as test_client:
            test_client.app_state = app  # type: ignore[attr-defined]
            yield test_client


def test_healthz_reports_algo_mode(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["effective_mode"] == "algo"
    assert payload["storage"]["mode"] == "files"
    assert payload["synth_mode"] == "algo"


def test_synth_catalog_is_available(client) -> None:
    payload = client.get("/api/v1/synths").json()
    codes = {item["code"] for item in payload["items"]}
    assert {"discover_weekly", "daily_mix", "weather_mix", "energy"} <= codes
    assert payload["mode"] == "algo"


def test_user_settings_and_context(client) -> None:
    response = client.put("/api/v1/users/alice", json={"timezone": "UTC", "weather_enabled": False})
    assert response.status_code == 200
    context = client.get("/api/v1/context?user=alice").json()
    assert context["time_slot"] in {"morning", "day", "evening", "night"}
    assert context["weather"] == "unknown"


def test_library_sync_and_mix_generation(client) -> None:
    client.put("/api/v1/users/alice", json={"timezone": "UTC"})
    sync = client.get("/api/v1/library/sync")
    assert sync.status_code == 202
    assert sync.json()["total"] == 120

    created = client.post("/api/v1/mixes", json={"owner_id": "alice", "template_code": "energy", "name": "Энергия"})
    assert created.status_code == 201
    mix_id = created.json()["mix_id"]

    generated = client.post(f"/api/v1/mixes/{mix_id}/generate", json={"dry_run": True})
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["mode"] == "algo"
    assert payload["enabled_modules"] == []
    assert len(payload["track_ids"]) == 35
    assert payload["written"] is False
    assert payload["metrics"]["diversity"] > 0

    runs = client.get(f"/api/v1/mixes/{mix_id}/runs").json()["items"]
    assert runs and runs[0]["mode"] == "algo"


def test_generated_mix_writes_to_navidrome(client) -> None:
    client.put("/api/v1/users/alice", json={"timezone": "UTC"})
    client.get("/api/v1/library/sync")
    mix_id = client.post("/api/v1/mixes", json={"owner_id": "alice", "template_code": "calm_morning"}).json()["mix_id"]
    payload = client.post(f"/api/v1/mixes/{mix_id}/generate", json={}).json()
    assert payload["written"] is True
    assert payload["playlist_id"]
    fake = FakeSubsonic.instances[-1]
    assert fake.playlists[payload["playlist_id"]]["tracks"] == payload["track_ids"]


def test_collab_playlist_lifecycle(client) -> None:
    created = client.post(
        "/api/v1/playlists",
        json={"owner_id": "alice", "name": "Общий", "track_ids": ["t-1", "t-2"], "members": [{"user_id": "bob", "role": "editor"}]},
    )
    assert created.status_code == 201
    playlist_id = created.json()["playlist_id"]

    detail = client.get(f"/api/v1/playlists/{playlist_id}?user=bob").json()
    assert detail["role"] == "editor"
    assert detail["track_ids"] == ["t-1", "t-2"]

    added = client.post(
        f"/api/v1/playlists/{playlist_id}/tracks",
        json={"actor_id": "bob", "track_ids": ["t-3"]},
    )
    assert added.status_code == 201
    assert added.json()["applied"] is True

    ops = client.get(f"/api/v1/playlists/{playlist_id}/ops?since_seq=0").json()["items"]
    assert [op["seq"] for op in ops] == sorted(op["seq"] for op in ops)

    tail = client.get(f"/api/v1/playlists/{playlist_id}/ops?since_seq=2").json()["items"]
    assert [op["seq"] for op in tail] == [op["seq"] for op in ops if op["seq"] > 2]

    forbidden = client.post(
        f"/api/v1/playlists/{playlist_id}/tracks",
        json={"actor_id": "bob", "track_ids": ["t-4"]},
        headers={"x-test": "1"},
    )
    assert forbidden.status_code == 201
    del forbidden


def test_collab_permission_denied_for_stranger(client) -> None:
    playlist_id = client.post("/api/v1/playlists", json={"owner_id": "alice", "name": "Личный"}).json()["playlist_id"]
    response = client.post(
        f"/api/v1/playlists/{playlist_id}/tracks",
        json={"actor_id": "mallory", "track_ids": ["t-1"]},
    )
    assert response.status_code == 403
    assert client.get(f"/api/v1/playlists/{playlist_id}?user=mallory").status_code == 403


def test_gateway_events_are_accepted(client) -> None:
    response = client.post(
        "/api/v1/events/observe",
        json={
            "events": [
                {"user_id": "alice", "track_id": "t-1", "kind": "play", "ts": NOW, "position_ms": 0},
                {"user_id": "alice", "track_id": "t-2", "kind": "skip", "ts": NOW, "position_ms": 5000},
                {"user_id": "alice", "track_id": "t-3", "kind": "love", "ts": NOW, "position_ms": 0},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] == 3

    rebuild = client.post("/api/v1/users/alice/profile/rebuild").json()
    assert rebuild["tracks"] == 3


def test_unknown_template_returns_404(client) -> None:
    assert client.get("/api/v1/synths/nope/preview?user=alice").status_code == 404


def test_selftest_endpoint(client) -> None:
    response = client.post("/api/v1/diagnostics/selftest")
    assert response.status_code == 200
    assert response.json()["mode"] == "algo"