from __future__ import annotations

import time
from typing import Any

from .contexts import Context

WEATHER_RU = {
    "clear": "Ясно",
    "cloudy": "Облачно",
    "rain": "Дождь",
    "storm": "Гроза",
    "snow": "Снег",
    "fog": "Туман",
    "wind": "Ветер",
    "extreme_heat": "Жара",
    "extreme_cold": "Мороз",
    "unknown": "Любая погода",
}

TIME_SLOT_RU = {
    "morning": "утро",
    "day": "день",
    "evening": "вечер",
    "night": "ночь",
}


def render(template: str, context: Context, extra: dict[str, Any] | None = None) -> str:
    values: dict[str, Any] = {
        "name": template,
        "time_slot": context.time_slot,
        "time_slot_ru": TIME_SLOT_RU.get(context.time_slot, context.time_slot),
        "weather": context.weather,
        "weather_ru": WEATHER_RU.get(context.weather, context.weather),
        "date": time.strftime("%Y-%m-%d", time.localtime()),
        "week": time.strftime("%G-W%V", time.localtime()),
        "user": context.user_id,
    }
    values.update(extra or {})
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def describe(tracks: list[Any], context: Context, spec_name: str) -> str:
    if not tracks:
        return f"{spec_name}: нет подходящих треков"
    genres = _top(tracks, lambda t: (t.genre or "").lower())
    bpms = sorted(t.bpm for t in tracks if t.bpm)
    parts = [f"{len(tracks)} треков"]
    if genres:
        parts.append("жанры: " + ", ".join(genres[:3]))
    if bpms:
        parts.append(f"BPM: {bpms[0]:.0f}–{bpms[-1]:.0f}")
    parts.append(f"контекст: {TIME_SLOT_RU.get(context.time_slot, context.time_slot)}/{WEATHER_RU.get(context.weather, context.weather)}")
    return f"{spec_name} · " + " · ".join(parts)


def _top(tracks: list[Any], key: Any, limit: int = 3) -> list[str]:
    counts: dict[str, int] = {}
    for track in tracks:
        value = key(track)
        if value:
            counts[value] = counts.get(value, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [name for name, count in ordered[:limit]]