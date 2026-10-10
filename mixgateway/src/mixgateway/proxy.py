from __future__ import annotations

import logging
import re
from urllib.parse import urlencode

import httpx

LOGGER = logging.getLogger("mixgateway")

AUDIT = re.compile(r"^(getPlaylists|getPlaylist|getMusicFolders|ping|getScanStatus|getLicense|getOpenSubsonicExtensions)$")
REDIRECT_ENDPOINTS = re.compile(r"^(stream|download|getCoverArt|getAvatar)$")
TECH_PREFIXES = ("__mix_", "[mix]", "tmp-")


class SubsonicProxy:
    """Прозоксирование Subsonic API Navidrome с наблюдением событий и редиректами аудио (FR-5)."""

    def __init__(
        self,
        upstream: str,
        *,
        core_url: str = "",
        timeout: float = 60.0,
        token: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._upstream = upstream.rstrip("/")
        self._core_url = core_url.rstrip("/")
        self._timeout = timeout
        self._token = token
        self._client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> SubsonicProxy:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    def base_url(self) -> str:
        return f"{self._upstream}/rest"

    async def forward(self, method: str, query: dict[str, str]) -> httpx.Response:
        payload = await self._call(method, query)
        if REDIRECT_ENDPOINTS.match(method) and self._upstream:
            return httpx.Response(
                status_code=307,
                headers={
                    "Location": f"{self._upstream}/rest/{method}?{urlencode(query)}",
                    "Cache-Control": "no-store",
                },
            )
        await self._maybe_observe(method, query, payload)
        return httpx.Response(
            status_code=200,
            content=payload,
            headers={"Content-Type": "application/json", "X-Mix-Gateway": "subsonic"},
        )

    async def health(self) -> dict[str, object]:
        try:
            await self._client.get(
                f"{self._upstream}/rest/ping",
                params={"u": "healthz", "v": "1.16.1", "c": "mixgateway", "f": "json"},
            )
        except httpx.HTTPError as exc:
            return {"status": "down", "detail": str(exc)}
        return {"status": "up", "upstream": self._upstream}

    async def _call(self, method: str, query: dict[str, str]) -> bytes:
        url = f"{self._upstream}/rest/{method}"
        try:
            response = await self._client.get(url, params=query)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            LOGGER.warning("Upstream Navidrome недоступен для %s: %s", method, exc)
            return _error_payload(method, 0, "upstream unavailable")

    async def _maybe_observe(self, method: str, query: dict[str, str], payload: bytes) -> None:
        if not self._core_url or not self._token:
            return
        username = query.get("u", "")
        if not username:
            return
        try:
            import json

            envelope = json.loads(payload).get("subsonic-response", {})
        except ValueError:
            return
        events: list[dict[str, object]] = []
        if method == "scrobble":
            track_id = query.get("id", "")
            submission = query.get("submission") == "true"
            events.append(
                {
                    "user_id": username,
                    "track_id": track_id,
                    "kind": "play" if submission else "skip",
                    "ts": _now(),
                    "position_ms": 0,
                }
            )
        elif method in ("star", "unstar"):
            events.append(
                {
                    "user_id": username,
                    "track_id": query.get("id", ""),
                    "kind": "love" if method == "star" else "unlove",
                    "ts": _now(),
                    "position_ms": 0,
                }
            )
        elif method == "setRating":
            events.append(
                {
                    "user_id": username,
                    "track_id": query.get("id", ""),
                    "kind": "rate",
                    "ts": _now(),
                    "position_ms": 0,
                    "rating": int(query.get("rating", 0) or 0),
                }
            )
        elif method == "updatePlaylist":
            playlist_id = query.get("playlistId", "")
            events.append(
                {
                    "type": "playlist.external_change",
                    "user_id": username,
                    "playlist_id": playlist_id,
                    "ts": _now(),
                }
            )
        if not events:
            del envelope
            return
        try:
            await self._client.post(
                f"{self._core_url}/api/v1/events/observe",
                json={"events": events},
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=2.0,
            )
        except httpx.HTTPError as exc:
            LOGGER.debug("Не удалось передать наблюдение в MixCore: %s", exc)

    async def list_playlists(self, query: dict[str, str]) -> list[dict[str, object]]:
        import json

        payload = await self._call("getPlaylists", query)
        try:
            envelope = json.loads(payload).get("subsonic-response", {})
        except ValueError:
            return []
        raw = envelope.get("playlists", {}).get("playlist", [])
        items = raw if isinstance(raw, list) else [raw]
        return [item for item in items if not _is_technical(str(item.get("name", "")))]


def _is_technical(name: str) -> bool:
    return any(name.startswith(prefix) for prefix in TECH_PREFIXES)


def _now() -> float:
    import time

    return time.time()


def _error_payload(method: str, code: int, message: str) -> bytes:
    import json

    return json.dumps(
        {
            "subsonic-response": {
                "status": "failed",
                "version": "1.16.1",
                "type": "mixgateway",
                "serverVersion": "0.1.0",
                "error": {"code": code, "message": f"{method}: {message}"},
            }
        }
    ).encode()


def is_audit_method(method: str) -> bool:
    return bool(AUDIT.match(method))