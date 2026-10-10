from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

LOGGER = logging.getLogger("mixcore.ai")


@dataclass(frozen=True, slots=True)
class AIStatus:
    name: str
    available: bool
    reason: str = ""


@dataclass(slots=True)
class AIResult:
    available: bool
    name: str
    track_order: list[str] = field(default_factory=list)
    title: str = ""
    description: str = ""
    reason: str = ""


class AIPort(Protocol):
    name: str

    async def health(self) -> AIStatus: ...

    async def enrich(self, *, context: str, tracks: list[dict[str, object]], max_influence: float) -> AIResult: ...


class NullAI:
    """Контур ИИ выключен: состав и названия формируются алгоритмами (FR-3A.7)."""

    name = "none"

    async def health(self) -> AIStatus:
        return AIStatus(name=self.name, available=False, reason="disabled")

    async def enrich(self, *, context: str, tracks: list[dict[str, object]], max_influence: float) -> AIResult:
        del context, tracks, max_influence
        return AIResult(available=False, name=self.name, reason="disabled")


class OllamaAI:
    name = "ollama"

    def __init__(self, base_url: str, model: str, *, timeout_ms: int = 10_000, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_ms / 1000.0
        self._client = client or httpx.AsyncClient(timeout=self._timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> AIStatus:
        try:
            response = await self._client.get(f"{self._base_url}/api/tags", timeout=self._timeout)
            response.raise_for_status()
            models = {item.get("name", "") for item in response.json().get("models", [])}
        except (httpx.HTTPError, OSError) as exc:
            return AIStatus(name=self.name, available=False, reason=f"unreachable: {exc.__class__.__name__}")
        if self._model and not any(name.startswith(self._model.split(":")[0]) for name in models):
            return AIStatus(name=self.name, available=False, reason="model_not_pulled")
        return AIStatus(name=self.name, available=True)

    async def enrich(self, *, context: str, tracks: list[dict[str, object]], max_influence: float) -> AIResult:
        if max_influence <= 0:
            return AIResult(available=False, name=self.name, reason="influence_disabled")
        prompt = _build_prompt(context, tracks)
        try:
            response = await self._client.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.2, "num_predict": 400},
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json().get("response", "{}")
        except (httpx.HTTPError, OSError) as exc:
            LOGGER.warning("ИИ-модуль недоступен: %s", exc)
            return AIResult(available=False, name=self.name, reason="timeout_or_error")
        import json

        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return AIResult(available=False, name=self.name, reason="bad_json")
        order = [str(item) for item in parsed.get("order", []) if str(item) in {str(t["id"]) for t in tracks}]
        return AIResult(
            available=True,
            name=self.name,
            track_order=order,
            title=str(parsed.get("title", ""))[:120],
            description=str(parsed.get("description", ""))[:600],
        )


def _build_prompt(context: str, tracks: list[dict[str, object]]) -> str:
    compact = [
        {"id": t.get("id"), "title": t.get("title"), "artist": t.get("artist"), "tags": t.get("tags")}
        for t in tracks[:60]
    ]
    return (
        "Ты помощник подбора музыки. Верни ТОЛЬКО JSON: "
        '{"title": "...", "description": "...", "order": ["id трека", ...]}. '
        "order — до 60 id треков из списка, лучший порядок для этого контекста. "
        f"Контекст: {context}. Треки: {compact}"
    )


class AIEnsemble:
    def __init__(self, modules: list[AIPort], *, max_influence: float) -> None:
        self._modules = modules
        self._max_influence = max_influence

    @property
    def names(self) -> list[str]:
        return [module.name for module in self._modules]

    async def status(self) -> list[AIStatus]:
        return [await module.health() for module in self._modules]

    async def enrich(self, *, context: str, tracks: list[dict[str, object]]) -> AIResult:
        merged = AIResult(available=False, name="none", reason="all_modules_unavailable")
        for module in self._modules:
            status = await module.health()
            if not status.available:
                continue
            result = await module.enrich(
                context=context,
                tracks=tracks,
                max_influence=self._max_influence,
            )
            if result.available:
                return result
            merged = result
        return merged