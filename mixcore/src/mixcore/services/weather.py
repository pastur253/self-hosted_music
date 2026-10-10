from __future__ import annotations

import logging
import time
from typing import Protocol

import httpx

from ..domain.contexts import classify_weather
from ..storage.layout import Layout

LOGGER = logging.getLogger("mixcore.weather")

TTL_SECONDS = 1800
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


class WeatherProvider(Protocol):
    name: str

    async def fetch(self, latitude: float, longitude: float) -> dict[str, object]: ...


class NullWeatherProvider:
    name = "none"

    async def fetch(self, latitude: float, longitude: float) -> dict[str, object]:
        return {"code": None, "temperature_c": None, "wind_kph": None, "stale": True, "provider": "none"}


class OpenMeteoProvider:
    name = "open-meteo"

    def __init__(self, client: httpx.AsyncClient | None = None, *, timeout: float = 8.0) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, latitude: float, longitude: float) -> dict[str, object]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code,wind_speed_10m,is_day",
            "timezone": "auto",
        }
        response = await self._client.get(OPEN_METEO, params=params)
        response.raise_for_status()
        current = response.json().get("current", {})
        code = current.get("weather_code")
        return {
            "code": code,
            "temperature_c": current.get("temperature_2m"),
            "wind_kph": current.get("wind_speed_10m"),
            "is_day": bool(current.get("is_day", 1)),
            "observed_at": time.time(),
            "provider": self.name,
            "stale": False,
        }


class WeatherService:
    def __init__(self, layout: Layout, provider: WeatherProvider | None = None) -> None:
        self._layout = layout
        self._provider = provider or NullWeatherProvider()

    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def current(self, latitude: float | None, longitude: float | None) -> dict[str, object]:
        if latitude is None or longitude is None:
            return {"code": None, "stale": True, "provider": "none", "reason": "no_coordinates"}
        cache = self._layout.weather.load() or {}
        key = f"{latitude:.2f},{longitude:.2f}"
        entry = cache.get(key)
        now = time.time()
        if entry and now - float(entry.get("observed_at", 0)) < TTL_SECONDS:
            return {**entry, "stale": False, "from_cache": True}
        try:
            fresh = await self._provider.fetch(latitude, longitude)
        except (httpx.HTTPError, OSError) as exc:
            LOGGER.warning("Погодный провайдер недоступен: %s", exc)
            if entry:
                return {**entry, "stale": True, "reason": "provider_unavailable"}
            return {"code": None, "stale": True, "provider": self._provider.name, "reason": "provider_unavailable"}
        cache[key] = fresh
        cache["_updated_at"] = now
        self._layout.weather.save({"points": cache})
        return fresh

    async def code_for(self, latitude: float | None, longitude: float | None) -> str:
        data = await self.current(latitude, longitude)
        if data.get("code") is None:
            return "unknown"
        return classify_weather(
            data.get("code"),
            temp_c=data.get("temperature_c"),
            wind_kph=data.get("wind_kph"),
        )


def build_provider(name: str, api_key: str = "") -> WeatherProvider:
    if name in ("", "none"):
        return NullWeatherProvider()
    if name in ("open-meteo", "openmeteo"):
        return OpenMeteoProvider()
    LOGGER.warning("Неизвестный погодный провайдер %r, используется none", name)
    return NullWeatherProvider()