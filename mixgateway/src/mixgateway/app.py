from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .proxy import SubsonicProxy, is_audit_method

LOGGER = logging.getLogger("mixgateway")

SUBSONIC_PREFIX = "/rest"


def _read_token() -> str:
    path = os.getenv("MIX_GATEWAY_TOKEN_FILE", "")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    return os.getenv("MIX_GATEWAY_TOKEN", "")


def create_app() -> FastAPI:
    logging.basicConfig(level=os.getenv("MIX_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)-7s %(name)s %(message)s")
    upstream = os.getenv("MIX_UPSTREAM", "http://navidrome:4533")
    core_url = os.getenv("MIX_CORE_URL", "http://mixcore:8080")
    token = _read_token()
    proxy = SubsonicProxy(upstream, core_url=core_url, token=token)

    app = FastAPI(title="MixGateway", version="0.1.0", description="Subsonic BFF перед Navidrome для Feishin")
    app.state.proxy = proxy

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await proxy.aclose()

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        status = await proxy.health()
        return {
            **status,
            "core_url": core_url,
            "native_api_proxy": os.getenv("MIX_PROXY_NATIVE_API", "false") == "true",
        }

    @app.api_route("/rest/{method}", methods=["GET", "POST"])
    async def subsonic(method: str, request: Request) -> Response:
        query: dict[str, str] = {}
        for key, value in request.query_params.multi_items():
            query[key] = value
        if request.method == "POST":
            form = await request.form()
            query.update({k: str(v) for k, v in form.multi_items()})
        if not query.get("f"):
            query["f"] = "json"
        response = await proxy.forward(method, query)
        if is_audit_method(method):
            LOGGER.info("subsonic %s u=%s", method, query.get("u", "?"))
        return response

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def native_api(path: str, request: Request) -> Response:
        if os.getenv("MIX_PROXY_NATIVE_API", "false") != "true":
            return JSONResponse({"error": "native_api_proxy_disabled", "hint": "SERVER_TYPE=subsonic"}, status_code=404)
        return await _forward_native(proxy, path, request)

    return app


async def _forward_native(proxy: SubsonicProxy, path: str, request: Request) -> Response:
    query = {k: v for k, v in request.query_params.items()}
    headers = {k: v for k, v in request.headers.items() if k.lower() in ("authorization", "content-type", "accept")}
    url = f"{proxy.base_url().rsplit('/rest', 1)[0]}/api/{path}"
    try:
        response = await proxy._client.request(  # noqa: SLF001
            request.method,
            url,
            params=query or None,
            headers=headers or None,
            content=await request.body() or None,
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": "upstream_unavailable", "detail": str(exc)}, status_code=502)
    return Response(content=response.content, status_code=response.status_code, headers={"Content-Type": response.headers.get("content-type", "application/json")})


app = create_app()