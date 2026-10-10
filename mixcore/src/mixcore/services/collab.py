from __future__ import annotations

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

from ..domain.models import (
    ROLE_EDITOR,
    ROLE_OWNER,
    ROLE_VIEWER,
    CollabMember,
    CollabOp,
    CollabPlaylist,
)
from ..navidrome.subsonic import SubsonicClient
from ..storage.layout import Layout

LOGGER = logging.getLogger("mixcore.collab")

OP_ADD = "track.added"
OP_REMOVE = "track.removed"
OP_MOVE = "track.moved"
OP_RENAME = "playlist.renamed"
OP_REPLACE = "playlist.replaced"


class PermissionDenied(PermissionError):
    pass


class NotFound(LookupError):
    pass


@dataclass(slots=True)
class OperationOutcome:
    op: CollabOp
    duplicate: bool
    applied: bool


class CollabService:
    """Реестр совместных плейлистов, права и append-only журнал операций (FR-4, 7.4)."""

    def __init__(self, layout: Layout, client: SubsonicClient, *, sync_enabled: bool = True) -> None:
        self._layout = layout
        self._client = client
        self._sync = sync_enabled

    def _playlists(self) -> dict[str, CollabPlaylist]:
        raw = self._layout.collab_playlists.load() or {}
        return {pid: CollabPlaylist.from_dict(item) for pid, item in raw.items()}

    def _save_playlists(self, playlists: dict[str, CollabPlaylist]) -> None:
        self._layout.collab_playlists.save({pid: item.to_dict() for pid, item in playlists.items()})

    def _members(self) -> dict[str, list[CollabMember]]:
        raw = self._layout.collab_members.load() or {}
        return {pid: [CollabMember.from_dict(item) for item in items] for pid, items in raw.items()}

    def _save_members(self, members: dict[str, list[CollabMember]]) -> None:
        self._layout.collab_members.save(
            {pid: [item.to_dict() for item in items] for pid, items in members.items()}
        )

    def list(self, user_id: str) -> list[dict[str, Any]]:
        playlists = self._playlists()
        members = self._members()
        result = []
        for pid, playlist in sorted(playlists.items(), key=lambda item: item[0]):
            roster = members.get(pid, [])
            if not any(m.user_id in (user_id, "") for m in roster) and playlist.owner_id != user_id:
                continue
            result.append(
                {
                    **playlist.to_dict(),
                    "role": self.role_of(playlist, roster, user_id),
                    "members": [m.to_dict() for m in roster],
                }
            )
        return result

    def get(self, playlist_id: str, user_id: str) -> dict[str, Any]:
        playlists = self._playlists()
        playlist = playlists.get(playlist_id)
        if playlist is None:
            raise NotFound(f"Плейлист {playlist_id} не найден")
        roster = self._members().get(playlist_id, [])
        role = self.role_of(playlist, roster, user_id)
        if role is None:
            raise PermissionDenied("Нет доступа к плейлисту")
        return {**playlist.to_dict(), "role": role, "members": [m.to_dict() for m in roster]}

    def role_of(self, playlist: CollabPlaylist, roster: list[CollabMember], user_id: str) -> str | None:
        for member in roster:
            if member.user_id == user_id:
                return member.role
        if playlist.owner_id == user_id:
            return ROLE_OWNER
        return None

    async def create(
        self,
        *,
        owner_id: str,
        name: str,
        description: str = "",
        track_ids: list[str] | None = None,
        members: list[tuple[str, str]] | None = None,
    ) -> CollabPlaylist:
        navidrome_id = await self._client.create_playlist(name=name, track_ids=track_ids or [], public=True)
        if description:
            await self._client.update_playlist(navidrome_id, comment=description)
        playlist_id = _new_id()
        playlist = CollabPlaylist(
            playlist_id=playlist_id,
            navidrome_playlist_id=navidrome_id,
            name=name,
            description=description,
            owner_id=owner_id,
            created_seq=0,
            next_seq=1,
        )
        playlists = self._playlists()
        playlists[playlist_id] = playlist
        self._save_playlists(playlists)
        roster_map = self._members()
        roster_map[playlist_id] = [
            CollabMember(playlist_id=playlist_id, user_id=owner_id, role=ROLE_OWNER),
            *[
                CollabMember(playlist_id=playlist_id, user_id=uid, role=role)
                for uid, role in (members or [])
                if uid != owner_id
            ],
        ]
        self._save_members(roster_map)
        if track_ids:
            await self._apply(
                playlist_id,
                actor_id=owner_id,
                op=OP_REPLACE,
                payload={"track_ids": list(track_ids)},
                role=ROLE_OWNER,
            )
        return playlist

    def set_members(self, playlist_id: str, actor_id: str, members: list[tuple[str, str]]) -> list[dict[str, Any]]:
        playlist = self._require(playlist_id)
        self._assert_role(playlist, playlist_id, actor_id, ROLE_OWNER)
        roster_map = self._members()
        preserved = [m for m in roster_map.get(playlist_id, []) if m.role == ROLE_OWNER]
        roster_map[playlist_id] = preserved + [
            CollabMember(playlist_id=playlist_id, user_id=uid, role=role) for uid, role in members
        ]
        self._save_members(roster_map)
        return [m.to_dict() for m in roster_map[playlist_id]]

    async def apply_operation(
        self,
        playlist_id: str,
        *,
        actor_id: str,
        op: str,
        payload: dict[str, Any],
        op_id: str | None = None,
    ) -> OperationOutcome:
        playlist = self._require(playlist_id)
        required = ROLE_OWNER if op in (OP_RENAME, OP_REPLACE) else ROLE_EDITOR
        role = self._assert_role(playlist, playlist_id, actor_id, required)
        operation_id = op_id or _new_op_id()
        if self._has_op(playlist_id, operation_id):
            existing = self._find_op(playlist_id, operation_id)
            return OperationOutcome(op=existing, duplicate=True, applied=False)
        record = CollabOp(
            playlist_id=playlist_id,
            seq=playlist.next_seq,
            op=op,
            actor_id=actor_id,
            op_id=operation_id,
            ts=time.time(),
            payload=dict(payload),
        )
        self._layout.collab_ops(playlist_id).append(record.to_dict())
        playlists = self._playlists()
        current = playlists[playlist_id]
        playlists[playlist_id] = CollabPlaylist(
            playlist_id=current.playlist_id,
            navidrome_playlist_id=current.navidrome_playlist_id,
            name=current.name,
            description=current.description,
            owner_id=current.owner_id,
            created_seq=current.created_seq,
            next_seq=record.seq + 1,
        )
        if op == OP_RENAME and payload.get("name"):
            updated = playlists[playlist_id]
            playlists[playlist_id] = CollabPlaylist(
                playlist_id=updated.playlist_id,
                navidrome_playlist_id=updated.navidrome_playlist_id,
                name=str(payload["name"]),
                description=updated.description,
                owner_id=updated.owner_id,
                created_seq=updated.created_seq,
                next_seq=updated.next_seq,
            )
        self._save_playlists(playlists)
        applied = await self._push_to_navidrome(playlists[playlist_id], record)
        del role
        return OperationOutcome(op=record, duplicate=False, applied=applied)

    def ops_since(self, playlist_id: str, since_seq: int) -> list[dict[str, Any]]:
        return [dict(op) for op in self._layout.collab_ops(playlist_id).read_all() if int(op.get("seq", 0)) > since_seq]

    def tracks(self, playlist_id: str) -> list[str]:
        result: list[str] = []
        for payload in self._layout.collab_ops(playlist_id).read_all():
            result = apply_op(result, CollabOp.from_dict(payload))
        return result

    def _require(self, playlist_id: str) -> CollabPlaylist:
        playlist = self._playlists().get(playlist_id)
        if playlist is None:
            raise NotFound(f"Плейлист {playlist_id} не найден")
        return playlist

    def _assert_role(self, playlist: CollabPlaylist, playlist_id: str, user_id: str, required: str) -> str:
        role = self.role_of(playlist, self._members().get(playlist_id, []), user_id)
        if role is None:
            raise PermissionDenied("Нет доступа к плейлисту")
        if _rank(role) < _rank(required):
            raise PermissionDenied(f"Требуется роль {required}, у пользователя {role}")
        return role

    def _has_op(self, playlist_id: str, op_id: str) -> bool:
        return any(op["op_id"] == op_id for op in self._layout.collab_ops(playlist_id).read_all())

    def _find_op(self, playlist_id: str, op_id: str) -> CollabOp:
        for payload in self._layout.collab_ops(playlist_id).read_all():
            if payload.get("op_id") == op_id:
                return CollabOp.from_dict(payload)
        raise NotFound("Операция не найдена")

    async def _push_to_navidrome(self, playlist: CollabPlaylist, record: CollabOp) -> bool:
        if not self._sync or not playlist.navidrome_playlist_id:
            return False
        track_ids = self.tracks(playlist.playlist_id)
        try:
            await self._client.replace_playlist_tracks(playlist.navidrome_playlist_id, track_ids)
            return True
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Не удалось синхронизировать плейлист с Navidrome: %s", exc)
            return False

    async def _apply(
        self,
        playlist_id: str,
        *,
        actor_id: str,
        op: str,
        payload: dict[str, Any],
        role: str,
    ) -> OperationOutcome:
        del role
        return await self.apply_operation(playlist_id, actor_id=actor_id, op=op, payload=payload)


def apply_op(track_ids: list[str], op: CollabOp) -> list[str]:
    result = list(track_ids)
    if op.op == OP_ADD:
        for track_id in op.payload.get("track_ids", []):
            position = int(op.payload.get("position", len(result)))
            position = max(0, min(position, len(result)))
            result.insert(position, str(track_id))
    elif op.op == OP_REMOVE:
        targets = {str(item) for item in op.payload.get("track_ids", [])}
        indexes = {int(i) for i in op.payload.get("indexes", [])}
        result = [tid for index, tid in enumerate(result) if index not in indexes and tid not in targets]
    elif op.op == OP_MOVE:
        index = int(op.payload.get("from", -1))
        to = int(op.payload.get("to", -1))
        if 0 <= index < len(result) and 0 <= to < len(result):
            value = result.pop(index)
            result.insert(to, value)
    elif op.op in (OP_REPLACE, OP_RENAME):
        if op.op == OP_REPLACE:
            result = [str(item) for item in op.payload.get("track_ids", [])]
    return result


def _rank(role: str) -> int:
    return {ROLE_VIEWER: 1, ROLE_EDITOR: 2, ROLE_OWNER: 3}.get(role, 0)


def _new_id() -> str:
    return "pl_" + secrets.token_hex(8)


def _new_op_id() -> str:
    return secrets.token_hex(8)


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]