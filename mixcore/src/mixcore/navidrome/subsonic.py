from __future__ import annotations

import hashlib
import logging
import secrets
from collections.abc import Sequence
from typing import Any

import httpx

LOGGER = logging.getLogger("mixcore.navidrome")

CLIENT_NAME = "mixcore"
CLIENT_VERSION = "0.1.0"
API_VERSION = "1.16.1"


class NavidromeError(RuntimeError):
    def __init__(self, code: int, message: str, *, method: str = "") -> None:
        super().__init__(f"Navidrome {method or 'api'}: [{code}] {message}")
        self.code = code
        self.message = message
        self.method = method


class NavidromeUnavailable(NavidromeError):
    pass


class SubsonicClient:
    """Клиент Subsonic API Navidrome (публичный документированный контракт, NV-L02)."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> SubsonicClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    def _auth(self) -> dict[str, str]:
        salt = secrets.token_hex(8)
        token = hashlib.md5(f"{self._password}{salt}".encode(), usedforsecurity=False).hexdigest()
        return {
            "u": self._username,
            "t": token,
            "s": salt,
            "v": API_VERSION,
            "c": CLIENT_NAME,
            "f": "json",
        }

    async def call(self, method: str, **params: Any) -> dict[str, Any]:
        query = {key: _flatten(value) for key, value in params.items() if value is not None}
        query.update(self._auth())
        try:
            response = await self._client.get(f"{self._base_url}/rest/{method}", params=query)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NavidromeUnavailable(0, f"недоступен: {exc}", method=method) from exc
        payload = response.json()
        envelope = payload.get("subsonic-response", {})
        if envelope.get("status") != "ok":
            error = envelope.get("error") or {}
            raise NavidromeError(int(error.get("code", 500)), str(error.get("message", "unknown")), method=method)
        return envelope

    async def ping(self) -> bool:
        await self.call("ping")
        return True

    async def get_user(self) -> dict[str, Any]:
        return _first(await self.call("getUser"), "user")

    async def get_music_folders(self) -> list[dict[str, Any]]:
        return _all(await self.call("getMusicFolders"), "musicFolder")

    async def search(self, query: str, *, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        payload = await self.call("search3", query=query, songCount=limit, artistCount=0, albumCount=0, offset=offset)
        return _all(payload, "song")

    async def get_random_songs(self, *, size: int = 50, genre: str | None = None) -> list[dict[str, Any]]:
        return _all(await self.call("getRandomSongs", size=size, genre=genre), "song")

    async def get_songs_by_genre(self, genre: str, *, count: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        payload = await self.call("getSongsByGenre", genre=genre, count=count, offset=offset)
        return _all(payload, "song")

    async def get_starred(self) -> list[dict[str, Any]]:
        return _all(await self.call("getStarred2"), "song")

    async def get_album_list(self, *, size: int = 500, offset: int = 0, genre: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"type": "newest" if not genre else "byGenre", "size": size, "offset": offset}
        if genre:
            params["genre"] = genre
        return _all(await self.call("getAlbumList2", **params), "album")

    async def get_similar_songs(self, artist_id: str, count: int = 50) -> list[dict[str, Any]]:
        payload = await self.call("getSimilarSongs2", artistId=artist_id, count=count)
        return _all(payload, "song")

    async def get_top_songs(self, artist: str, count: int = 50) -> list[dict[str, Any]]:
        payload = await self.call("getTopSongs", artist=artist, count=count)
        return _all(payload, "song")

    async def get_now_playing(self) -> list[dict[str, Any]]:
        return _all(await self.call("getNowPlaying"), "entry")

    async def get_playlists(self) -> list[dict[str, Any]]:
        return _all(await self.call("getPlaylists"), "playlist")

    async def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        return _first(await self.call("getPlaylist", id=playlist_id), "playlist")

    async def create_playlist(self, *, name: str, track_ids: Sequence[str] = (), public: bool = True) -> str:
        payload = await self.call("createPlaylist", name=name, songId=list(track_ids) or None)
        return str(payload.get("playlist", {}).get("id", ""))

    async def update_playlist(self, playlist_id: str, *, name: str | None = None, comment: str | None = None) -> None:
        params: dict[str, Any] = {"playlistId": playlist_id}
        if name is not None:
            params["playlist"] = name
        if comment is not None:
            params["comment"] = comment
        await self.call("updatePlaylist", **params)

    async def replace_playlist_tracks(self, playlist_id: str, track_ids: Sequence[str]) -> None:
        await self.call("updatePlaylist", playlistId=playlist_id, songId=list(track_ids))

    async def add_to_playlist(self, playlist_id: str, track_ids: Sequence[str]) -> None:
        await self.call("updatePlaylist", playlistId=playlist_id, songIdToAdd=list(track_ids))

    async def remove_from_playlist(self, playlist_id: str, indexes: Sequence[int]) -> None:
        await self.call("updatePlaylist", playlistId=playlist_id, songIndexToRemove=list(indexes))

    async def delete_playlist(self, playlist_id: str) -> None:
        await self.call("deletePlaylist", id=playlist_id)

    async def scrobble(self, track_id: str, *, submission: bool, timestamp_ms: int | None = None) -> None:
        await self.call(
            "scrobble",
            id=track_id,
            time=timestamp_ms,
            submission="true" if submission else "false",
        )

    async def star(self, track_id: str, star: bool = True) -> None:
        await self.call("star" if star else "unstar", id=track_id)

    async def set_rating(self, track_id: str, rating: int) -> None:
        await self.call("setRating", id=track_id, rating=rating)

    async def create_bookmark(self, track_id: str, position_ms: int) -> None:
        await self.call("createBookmark", id=track_id, position=position_ms)

    async def get_bookmarks(self) -> list[dict[str, Any]]:
        return _all(await self.call("getBookmarks"), "bookmark")

    async def health(self) -> dict[str, Any]:
        try:
            await self.ping()
        except NavidromeError as exc:
            return {"status": "down", "detail": exc.message}
        return {"status": "up", "version": API_VERSION}


def _first(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if value is None:
        return {}
    if isinstance(value, list):
        return value[0] if value else {}
    return value


def _all(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key, {})
    if isinstance(value, dict):
        return [value]
    return list(value or [])


def _flatten(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def parse_song(payload: dict[str, Any]) -> dict[str, Any]:
    """Нормализация Subsonic song/entry в словарь полей доменной модели Track."""
    return {
        "id": str(payload.get("id", "")),
        "title": payload.get("title", ""),
        "artist": payload.get("artist", ""),
        "album": payload.get("album", ""),
        "album_id": str(payload.get("albumId", "")),
        "artist_id": str(payload.get("artistId", "")),
        "genre": payload.get("genre", ""),
        "duration": float(payload.get("duration", 0) or 0),
        "bpm": payload.get("bpm"),
        "year": payload.get("year"),
        "date_added": 0.0,
        "tags": [str(tag) for tag in (payload.get("genres") or []) if tag],
        "loved": bool(payload.get("starred", False)),
        "rating": int(payload.get("userRating", 0) or 0),
        "play_count": int(payload.get("playCount", 0) or 0),
        "last_played": None,
    }