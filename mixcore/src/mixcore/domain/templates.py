from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contexts import Context


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    code: str
    name_ru: str
    name_en: str
    goal: str
    length: int
    context_types: tuple[str, ...]
    filters: dict[str, Any] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    title_template: str = "{name}"
    period: str = "weekly"
    requires_ai: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name_ru": self.name_ru,
            "name_en": self.name_en,
            "goal": self.goal,
            "length": self.length,
            "context_types": list(self.context_types),
            "filters": self.filters,
            "weights": self.weights,
            "title_template": self.title_template,
            "period": self.period,
            "requires_ai": self.requires_ai,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TemplateSpec:
        return cls(
            code=str(payload["code"]),
            name_ru=str(payload.get("name_ru", payload["code"])),
            name_en=str(payload.get("name_en", payload["code"])),
            goal=str(payload.get("goal", "")),
            length=int(payload.get("length", 30)),
            context_types=tuple(payload.get("context_types", ())),
            filters=dict(payload.get("filters", {})),
            weights={str(k): float(v) for k, v in dict(payload.get("weights", {})).items()},
            title_template=str(payload.get("title_template", "{name}")),
            period=str(payload.get("period", "weekly")),
            requires_ai=bool(payload.get("requires_ai", False)),
        )


CATALOG: tuple[TemplateSpec, ...] = (
    TemplateSpec(
        code="discover_weekly",
        name_ru="Открытия недели",
        name_en="Discover Weekly",
        goal="Новое и малоизвестное, похожее на любимое",
        length=40,
        context_types=("none",),
        filters={"max_plays_all": 8, "exclude_recent": True, "novelty_floor": 0.55},
        weights={"novelty": 0.30, "cooccurrence": 0.28, "affinity": 0.16, "genre_match": 0.18, "cohort_match": 0.04, "recency_boost": 0.04},
        title_template="Открытия недели · {date}",
        period="weekly",
    ),
    TemplateSpec(
        code="daily_mix",
        name_ru="Микс дня",
        name_en="Daily Mix",
        goal="Подборка под текущее время суток",
        length=30,
        context_types=("time_slot",),
        filters={"exclude_recent": True},
        weights={"cohort_match": 0.24, "affinity": 0.26, "cooccurrence": 0.22, "genre_match": 0.20, "novelty": 0.05, "recency_boost": 0.03},
        title_template="Микс дня · {time_slot_ru}",
        period="daily",
    ),
    TemplateSpec(
        code="weather_mix",
        name_ru="Погодный синтез",
        name_en="Weather Mix",
        goal="Подборка под погоду",
        length=30,
        context_types=("weather", "time_slot"),
        filters={"exclude_recent": True},
        weights={"cohort_match": 0.28, "genre_match": 0.26, "affinity": 0.20, "cooccurrence": 0.18, "novelty": 0.05, "recency_boost": 0.03},
        title_template="{weather_ru} · {time_slot_ru}",
        period="scheduled",
    ),
    TemplateSpec(
        code="energy",
        name_ru="Энергия",
        name_en="Energy",
        goal="Тренировка и дорога",
        length=35,
        context_types=("none",),
        filters={"bpm_min": 120, "max_duration": 300},
        weights={"affinity": 0.28, "genre_match": 0.24, "cooccurrence": 0.20, "cohort_match": 0.08, "novelty": 0.14, "recency_boost": 0.06},
        title_template="Энергия · {bpm_range}",
    ),
    TemplateSpec(
        code="calm_morning",
        name_ru="Спокойное утро",
        name_en="Calm Morning",
        goal="Медленный старт дня",
        length=30,
        context_types=("time_slot",),
        filters={"bpm_max": 100, "min_duration": 150},
        weights={"cohort_match": 0.22, "genre_match": 0.26, "affinity": 0.24, "cooccurrence": 0.18, "novelty": 0.06, "recency_boost": 0.04},
        title_template="Спокойное утро · {time_slot_ru}",
    ),
    TemplateSpec(
        code="night_drive",
        name_ru="Ночной драйв",
        name_en="Night Drive",
        goal="Позднее время суток",
        length=35,
        context_types=("time_slot",),
        filters={"bpm_min": 105, "exclude_recent": True},
        weights={"cohort_match": 0.26, "affinity": 0.24, "cooccurrence": 0.20, "genre_match": 0.20, "novelty": 0.07, "recency_boost": 0.03},
        title_template="Ночной драйв · {time_slot_ru}",
    ),
    TemplateSpec(
        code="retro_cohort",
        name_ru="Ретро-кохорта",
        name_en="Retro",
        goal="Подборка по десятилетию",
        length=30,
        context_types=("none",),
        filters={"decade": 1980},
        weights={"genre_match": 0.30, "affinity": 0.26, "cooccurrence": 0.22, "cohort_match": 0.10, "novelty": 0.08, "recency_boost": 0.04},
        title_template="Ретро · {decade}s",
    ),
    TemplateSpec(
        code="release_radar",
        name_ru="Релис-радар",
        name_en="Release Radar",
        goal="Новинки библиотеки",
        length=30,
        context_types=("none",),
        filters={"days_added": 30, "exclude_recent": True},
        weights={"recency_boost": 0.28, "genre_match": 0.26, "affinity": 0.22, "cooccurrence": 0.16, "novelty": 0.06, "cohort_match": 0.02},
        title_template="Релис-радар · {date}",
    ),
    TemplateSpec(
        code="forgotten_favorites",
        name_ru="Забытое любимое",
        name_en="Forgotten Favorites",
        goal="Давно не слушали, но любили",
        length=25,
        context_types=("none",),
        filters={"loved_only": True, "min_days_since_play": 30, "exclude_recent": True},
        weights={"affinity": 0.40, "genre_match": 0.22, "cooccurrence": 0.16, "cohort_match": 0.08, "novelty": 0.08, "recency_boost": 0.06},
        title_template="Забытое любимое",
    ),
    TemplateSpec(
        code="loved_only",
        name_ru="Только любимое",
        name_en="Loved Only",
        goal="Осознанное повторение",
        length=30,
        context_types=("none",),
        filters={"loved_only": True, "exclude_recent": True},
        weights={"affinity": 0.42, "genre_match": 0.24, "cooccurrence": 0.18, "cohort_match": 0.08, "novelty": 0.02, "recency_boost": 0.06},
        title_template="Только любимое",
    ),
    TemplateSpec(
        code="weekly_digest",
        name_ru="Обзор недели",
        name_en="Weekly Digest",
        goal="Статистика прослушиваний",
        length=20,
        context_types=("none",),
        filters={"plays_7d_min": 1},
        weights={"affinity": 0.34, "genre_match": 0.24, "cooccurrence": 0.20, "cohort_match": 0.12, "novelty": 0.04, "recency_boost": 0.06},
        title_template="Обзор недели · {date}",
        period="weekly",
    ),
)

BY_CODE: dict[str, TemplateSpec] = {spec.code: spec for spec in CATALOG}


def get(code: str) -> TemplateSpec | None:
    return BY_CODE.get(code)


get_template = get


def all_specs() -> tuple[TemplateSpec, ...]:
    return CATALOG


def render_title(spec: TemplateSpec, context: Context, *, extra: dict[str, Any] | None = None) -> str:
    from .naming import render

    return render(spec.title_template, context, extra or {})