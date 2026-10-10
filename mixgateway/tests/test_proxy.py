from __future__ import annotations

import json

import httpx
import pytest

from mixgateway.proxy import SubsonicProxy, is_audit_method


def _ok_envelope(method: str) -> dict[str, object]:
    return {"subsonic-response": {"status": "ok", "version": "1.16.1", "type": method}}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_forward_passes_json_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_envelope("ping"))

    async with SubsonicProxy("http://upstream", client=_client(handler)) as proxy:
        response = await proxy.forward("ping", {"u": "alice"})
    assert response.status_code == 200
    assert response.headers["X-Mix-Gateway"] == "subsonic"
    assert json.loads(response.content)["subsonic-response"]["status"] == "ok"


@pytest.mark.anyio
async def test_stream_is_redirected_without_buffering() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_ok_envelope("stream"))

    async with SubsonicProxy("http://upstream:4533", client=_client(handler)) as proxy:
        response = await proxy.forward("stream", {"u": "alice", "id": "t-1"})

    assert response.status_code == 307
    assert response.headers["Location"].startswith("http://upstream:4533/rest/stream")
    assert "u=alice" in response.headers["Location"]


@pytest.mark.anyio
async def test_upstream_failure_returns_subsonic_error_envelope() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with SubsonicProxy("http://upstream", client=_client(handler)) as proxy:
        response = await proxy.forward("getPlaylists", {"u": "alice"})

    payload = json.loads(response.content)["subsonic-response"]
    assert payload["status"] == "failed"
    assert payload["error"]["message"].startswith("getPlaylists:")


@pytest.mark.anyio
async def test_health_reports_down_on_connection_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with SubsonicProxy("http://upstream", client=_client(handler)) as proxy:
        assert (await proxy.health())["status"] == "down"


@pytest.mark.anyio
async def test_health_reports_up() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_envelope("ping"))

    async with SubsonicProxy("http://upstream", client=_client(handler)) as proxy:
        assert (await proxy.health())["status"] == "up"


def test_audit_methods_are_recognized() -> None:
    assert is_audit_method("getPlaylists")
    assert is_audit_method("ping")
    assert not is_audit_method("scrobble")


@pytest.mark.anyio
async def test_technical_playlists_are_hidden() -> None:
    payload = {
        "subsonic-response": {
            "status": "ok",
            "playlists": {
                "playlist": [
                    {"id": "1", "name": "__mix_internal"},
                    {"id": "2", "name": "[mix] Открытия недели"},
                    {"id": "3", "name": "Мой плейлист"},
                ]
            },
        }
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with SubsonicProxy("http://upstream", client=_client(handler)) as proxy:
        items = await proxy.list_playlists({"u": "alice"})

    assert [item["name"] for item in items] == ["Мой плейлист"]