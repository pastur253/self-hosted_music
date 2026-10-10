from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger("mixcore.domain.contexts")

DAY_SECONDS = 86_400


class TimeSlot(StrEnum):
    MORNING = "morning"
    DAY = "day"
    EVENING = "evening"
    NIGHT = "night"


class WeatherCode(StrEnum):
    CLEAR = "clear"
    CLOUDY = "cloudy"
    RAIN = "rain"
    STORM = "storm"
    SNOW = "snow"
    FOG = "fog"
    WIND = "wind"
    EXTREME_HEAT = "extreme_heat"
    EXTREME_COLD = "extreme_cold"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Context:
    user_id: str
    local_time: str
    time_slot: str
    weather: str
    weather_detail: dict[str, object]
    weather_stale: bool
    mode: str

    def to_dict(self) -> dict[str, object]:
        return {
            "user": self.user_id,
            "local_time": self.local_time,
            "time_slot": self.time_slot,
            "weather": self.weather,
            "weather_detail": self.weather_detail,
            "weather_stale": self.weather_stale,
            "mode": self.mode,
        }


DEFAULT_SLOTS = ((6, 11), (11, 17), (17, 23), (23, 6))


def resolve_time_slot(moment: datetime, bounds: tuple[tuple[int, int], ...] = DEFAULT_SLOTS) -> str:
    hour = moment.hour
    for index, (start, end) in enumerate(bounds):
        if start <= end:
            inside = start <= hour < end
        else:
            inside = hour >= start or hour < end
        if inside:
            return _slot_name(index)
    return _slot_name(0)


def _slot_name(index: int) -> str:
    order = (TimeSlot.MORNING, TimeSlot.DAY, TimeSlot.EVENING, TimeSlot.NIGHT)
    return str(order[index % len(order)])


def _zone(name: str) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        LOGGER.warning("Часовой пояс %s недоступен, используется UTC", name)
        return timezone.utc


def build_context(
    user_id: str,
    timezone_name: str,
    *,
    weather: str | None = None,
    weather_detail: dict[str, object] | None = None,
    weather_stale: bool = False,
    mode: str = "algo",
    now: float | None = None,
) -> Context:
    moment = datetime.fromtimestamp(now if now is not None else time.time(), tz=_zone(timezone_name))
    return Context(
        user_id=user_id,
        local_time=moment.isoformat(),
        time_slot=resolve_time_slot(moment),
        weather=weather or str(WeatherCode.UNKNOWN),
        weather_detail=dict(weather_detail or {}),
        weather_stale=weather_stale,
        mode=mode,
    )


def classify_weather(code: int | str | None, *, temp_c: float | None = None, wind_kph: float | None = None) -> str:
    if temp_c is not None and temp_c >= 32:
        return str(WeatherCode.EXTREME_HEAT)
    if temp_c is not None and temp_c <= -15:
        return str(WeatherCode.EXTREME_COLD)
    if wind_kph is not None and wind_kph >= 45:
        return str(WeatherCode.WIND)
    numeric = _to_int(code)
    if numeric is None:
        return str(WeatherCode.UNKNOWN)
    if numeric in (0, 1):
        return str(WeatherCode.CLEAR)
    if numeric in (2, 3, 45, 48):
        return str(WeatherCode.FOG if numeric in (45, 48) else WeatherCode.CLOUDY)
    if numeric in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return str(WeatherCode.RAIN)
    if numeric in (95, 96, 99):
        return str(WeatherCode.STORM)
    if numeric in (71, 73, 75, 77, 85, 86):
        return str(WeatherCode.SNOW)
    return str(WeatherCode.UNKNOWN)


def cohort_key(context: Context) -> str:
    return f"{context.time_slot}:{context.weather}"


def _to_int(value: int | str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None