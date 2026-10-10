from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from ..domain.models import MixDefinition, PlayEvent, UserSettings
from ..domain.templates import all_specs, get_template
from ..runtime import Runtime, check_health, run_selftest
from ..services.collab import NotFound, PermissionDenied
from .ws import EventHub, drain, keepalive

LOGGER = logging.getLogger("mixcore.routes")

router = APIRouter()
hub = EventHub()


def runtime_of(request: Request) -> Runtime:
    return request.app.state.runtime


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, Any]:
    return await check_health(runtime_of(request))


@router.get("/metrics")
async def metrics() -> Response:
    from prometheus_client import generate_latest

    return Response(content=generate_latest(), media_type="text/plain; version=0.0.4; charset=utf-8")


@router.get("/api/v1/context")
async def context(user: str = Query(...), request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    runtime = runtime_of(request)
    ctx = await runtime.mixes.context_for(user)
    return ctx.to_dict()


@router.get("/api/v1/synths")
async def list_synths(request: Request) -> dict[str, Any]:
    runtime = runtime_of(request)
    mode, modules, degraded = await runtime.mixes.mode()
    return {
        "mode": mode,
        "enabled_modules": modules,
        "degraded_reason": degraded,
        "items": [spec.to_dict() for spec in all_specs()],
    }


@router.get("/api/v1/synths/{code}/preview")
async def preview_synth(code: str, user: str = Query(...), request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    runtime = runtime_of(request)
    spec = get_template(code)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Неизвестный синтез {code}")
    mix = MixDefinition(
        mix_id=f"{user}:{code}",
        name=spec.name_ru,
        owner_id=user,
        template_code=code,
        length=spec.length,
    )
    outcome = await runtime.mixes.generate(mix, dry_run=True)
    return {
        "code": code,
        "title": outcome.title,
        "description": outcome.description,
        "mode": outcome.mode,
        "degraded_reason": outcome.degraded_reason,
        "metrics": outcome.metrics,
        "quality_problems": outcome.quality_problems,
        "stage_counts": outcome.stage_counts,
        "tracks": [{"id": tid, "reasons": runtime.mixes and []} for tid in outcome.track_ids],
    }


@router.get("/api/v1/mixes")
async def list_mixes(request: Request) -> dict[str, Any]:
    runtime = runtime_of(request)
    items = []
    for mix_id in runtime.layout.mix_ids():
        raw = runtime.layout.mix(mix_id).load()
        if raw:
            items.append(MixDefinition.from_dict(raw).to_dict())
    return {"items": items}


@router.post("/api/v1/mixes", status_code=201)
async def create_mix(payload: dict[str, Any] = Body(...), request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    runtime = runtime_of(request)
    owner = str(payload.get("owner_id", ""))
    if not owner:
        raise HTTPException(status_code=400, detail="owner_id обязателен")
    spec = get_template(str(payload.get("template_code", "")))
    mix = MixDefinition(
        mix_id=str(payload.get("mix_id") or f"{owner}:{payload.get('template_code', 'custom')}"),
        name=str(payload.get("name") or (spec.name_ru if spec else "Микс")),
        owner_id=owner,
        template_code=str(payload.get("template_code", "")),
        length=int(payload.get("length", 0)) or (spec.length if spec else 30),
        schedule=str(payload.get("schedule", "")),
        rules=dict(payload.get("rules", {})),
    )
    runtime.layout.mix(mix.mix_id).save(mix.to_dict())
    return mix.to_dict()


@router.post("/api/v1/mixes/{mix_id}/generate")
async def generate_mix(mix_id: str, request: Request = None, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:  # type: ignore[assignment]
    runtime = runtime_of(request)
    raw = runtime.layout.mix(mix_id).load()
    if raw is None:
        raise HTTPException(status_code=404, detail=f"Микс {mix_id} не найден")
    mix = MixDefinition.from_dict(raw)
    body = payload or {}
    outcome = await runtime.mixes.generate(
        mix,
        dry_run=bool(body.get("dry_run", False)),
        seed=body.get("seed"),
    )
    hub.publish_user(mix.owner_id, {"type": "mix.generated", "mix_id": outcome.mix_id, "title": outcome.title})
    return {
        "mix_id": outcome.mix_id,
        "title": outcome.title,
        "description": outcome.description,
        "mode": outcome.mode,
        "enabled_modules": outcome.enabled_modules,
        "degraded_reason": outcome.degraded_reason,
        "track_ids": outcome.track_ids,
        "metrics": outcome.metrics,
        "quality_problems": outcome.quality_problems,
        "stage_counts": outcome.stage_counts,
        "context": outcome.context,
        "playlist_id": outcome.playlist_id,
        "written": outcome.written,
    }


@router.get("/api/v1/mixes/{mix_id}/runs")
async def mix_runs(mix_id: str, request: Request) -> dict[str, Any]:
    runtime = runtime_of(request)
    records = [r for r in runtime.layout.mix_runs().iter_range() if r.get("mix_id") == mix_id]
    records.sort(key=lambda item: item.get("ts", 0), reverse=True)
    return {"items": records[:50]}


@router.get("/api/v1/users")
async def list_users(request: Request) -> dict[str, Any]:
    runtime = runtime_of(request)
    return {"items": (runtime.layout.users.load() or {})}


@router.put("/api/v1/users/{user_id}")
async def update_user(user_id: str, payload: dict[str, Any] = Body(...), request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    runtime = runtime_of(request)
    current = runtime.mixes.user(user_id).to_dict()
    merged = {**current, **payload, "user_id": user_id}
    saved = runtime.mixes.save_user(UserSettings.from_dict(merged))
    return saved.to_dict()


@router.post("/api/v1/users/{user_id}/profile/rebuild")
async def rebuild_profile(user_id: str, request: Request) -> dict[str, Any]:
    runtime = runtime_of(request)
    profile = runtime.mixes.rebuild_profile(user_id)
    return {"user_id": user_id, "plays": profile.total_plays, "tracks": len(profile.stats)}


@router.get("/api/v1/library/sync", status_code=202)
async def sync_library(request: Request) -> dict[str, Any]:
    runtime = runtime_of(request)
    stats = await runtime.library.sync()
    return {"total": stats.total, "duration_hours": stats.duration_hours}


@router.get("/api/v1/playlists")
async def list_playlists(request: Request, user: str = Query(...)) -> dict[str, Any]:
    runtime = runtime_of(request)
    return {"items": runtime.collab.list(user)}


@router.post("/api/v1/playlists", status_code=201)
async def create_playlist(payload: dict[str, Any] = Body(...), request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    runtime = runtime_of(request)
    try:
        playlist = await runtime.collab.create(
            owner_id=str(payload["owner_id"]),
            name=str(payload["name"]),
            description=str(payload.get("description", "")),
            track_ids=list(payload.get("track_ids", [])),
            members=[(str(m["user_id"]), str(m["role"])) for m in payload.get("members", [])],
        )
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return playlist.to_dict()


@router.get("/api/v1/playlists/{playlist_id}")
async def get_playlist(playlist_id: str, request: Request, user: str = Query(...)) -> dict[str, Any]:
    runtime = runtime_of(request)
    try:
        data = runtime.collab.get(playlist_id, user)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    data["track_ids"] = runtime.collab.tracks(playlist_id)
    return data


@router.post("/api/v1/playlists/{playlist_id}/tracks", status_code=201)
async def add_tracks(playlist_id: str, payload: dict[str, Any] = Body(...), request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    runtime = runtime_of(request)
    try:
        outcome = await runtime.collab.apply_operation(
            playlist_id,
            actor_id=str(payload["actor_id"]),
            op="track.added",
            payload={"track_ids": list(payload["track_ids"]), "position": int(payload.get("position", 0))},
            op_id=payload.get("op_id"),
        )
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    event = {"type": "playlist.track.added", **outcome.op.to_dict()}
    hub.publish_playlist(playlist_id, event)
    return {"op": outcome.op.to_dict(), "duplicate": outcome.duplicate, "applied": outcome.applied}


@router.delete("/api/v1/playlists/{playlist_id}/tracks/{track_id}")
async def remove_track(playlist_id: str, track_id: str, request: Request, actor_id: str = Query(...)) -> dict[str, Any]:
    runtime = runtime_of(request)
    try:
        outcome = await runtime.collab.apply_operation(
            playlist_id,
            actor_id=actor_id,
            op="track.removed",
            payload={"track_ids": [track_id]},
        )
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    hub.publish_playlist(playlist_id, {"type": "playlist.track.removed", **outcome.op.to_dict()})
    return {"op": outcome.op.to_dict(), "applied": outcome.applied}


@router.get("/api/v1/playlists/{playlist_id}/ops")
async def ops_since(playlist_id: str, request: Request, since_seq: int = Query(0, ge=0)) -> dict[str, Any]:
    runtime = runtime_of(request)
    return {"items": runtime.collab.ops_since(playlist_id, since_seq)}


@router.post("/api/v1/events/observe")
async def observe_events(payload: dict[str, Any] = Body(...), request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    """Приём событий от MixGateway (зеркалирование scrobble/star/rating, S-3)."""
    runtime = runtime_of(request)
    expected = _gateway_token()
    if expected:
        provided = request.headers.get("authorization", "").removeprefix("Bearer ")
        if provided != expected:
            raise HTTPException(status_code=401, detail="invalid gateway token")
    accepted = 0
    for item in payload.get("events", []):
        kind = str(item.get("kind", ""))
        if not kind:
            continue
        runtime.events.record(
            PlayEvent(
                user_id=str(item.get("user_id", "")),
                track_id=str(item.get("track_id", "")),
                kind=kind,
                ts=float(item.get("ts", 0.0) or 0.0),
                position_ms=int(item.get("position_ms", 0) or 0),
                rating=int(item.get("rating", 0) or 0),
            )
        )
        accepted += 1
    return {"accepted": accepted}


def _gateway_token() -> str:
    import os
    from pathlib import Path

    path = os.getenv("MIX_GATEWAY_TOKEN_FILE", "")
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8").strip()
    return os.getenv("MIX_GATEWAY_TOKEN", "")


@router.post("/api/v1/diagnostics/selftest")
async def selftest(request: Request) -> JSONResponse:
    runtime = runtime_of(request)
    result = await run_selftest(runtime)
    return JSONResponse(result, status_code=200 if result["ok"] else 500)


@router.websocket("/ws/v1")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    user_id = websocket.query_params.get("user", "")
    sub = hub.register(websocket, user_id)
    playlist_ids = [p for p in websocket.query_params.get("playlists", "").split(",") if p]
    sub.playlists.update(playlist_ids)
    LOGGER.info("WS подключён: user=%s playlists=%d", user_id, len(sub.playlists))
    try:
        await websocket.send_json({"type": "hello", "user": user_id, "playlists": sorted(sub.playlists)})
        async with asyncio.TaskGroup() as group:
            group.create_task(drain(websocket, sub))
            group.create_task(keepalive(websocket, sub))
            group.create_task(_receive_loop(websocket, sub))
    except* (WebSocketDisconnect, asyncio.CancelledError):
        LOGGER.info("WS отключён: user=%s", user_id)
    finally:
        hub.unregister(websocket)


async def _receive_loop(websocket: WebSocket, sub: Any) -> None:
    while True:
        message = await websocket.receive_json()
        kind = message.get("type")
        if kind == "subscribe.playlist":
            sub.playlists.add(str(message.get("playlist_id", "")))
            await websocket.send_json({"type": "subscribed", "playlist_id": message.get("playlist_id")})
        elif kind == "subscribe.mix":
            sub.mixes.add(str(message.get("mix_id", "")))
            await websocket.send_json({"type": "subscribed", "mix_id": message.get("mix_id")})
        elif kind == "ping":
            await websocket.send_json({"type": "pong"})


def register_routes(app: Any) -> None:
    app.include_router(router)
    app.state.hub = hub