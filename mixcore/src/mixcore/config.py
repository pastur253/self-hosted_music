from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

VALID_SYNTH_MODES = ("algo", "hybrid", "ai")
VALID_MODES = ("offline_first", "online")

SECRET_ENV = "MIX_NAVIDROME_SECRET_FILE"


def _get(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name)
    return default if value is None or value == "" else value


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _number(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _integer(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _secret(env: Mapping[str, str], name: str) -> str:
    path = env.get(name)
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8").strip()


@dataclass(frozen=True, slots=True)
class Settings:
    state_dir: Path
    navidrome_url: str
    navidrome_user: str
    navidrome_password: str
    synth_mode: str
    mode: str
    llm_enabled: bool
    llm_url: str
    llm_model: str
    llm_max_influence: float
    ai_timeout_ms: int
    embeddings_enabled: bool
    mix_length: int
    no_repeat_days: int
    weather_provider: str
    weather_api_key: str
    weather_lat: float | None
    weather_lon: float | None
    event_retention_days: int
    log_level: str
    gateway_url: str
    version: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source: Mapping[str, str] = os.environ if env is None else env
        synth_mode = _get(source, "MIX_SYNTH_MODE", "algo").lower()
        mode = _get(source, "MIX_MODE", "offline_first").lower()
        if synth_mode not in VALID_SYNTH_MODES:
            raise ValueError(f"MIX_SYNTH_MODE должен быть одним из {VALID_SYNTH_MODES}, получено {synth_mode!r}")
        if mode not in VALID_MODES:
            raise ValueError(f"MIX_MODE должен быть одним из {VALID_MODES}, получено {mode!r}")
        return cls(
            state_dir=Path(_get(source, "MIX_STATE_DIR", "/var/lib/mixcore")),
            navidrome_url=_get(source, "MIX_NAVIDROME_URL", "http://navidrome:4533").rstrip("/"),
            navidrome_user=_get(source, "MIX_NAVIDROME_USER", "mix-admin"),
            navidrome_password=_secret(source, SECRET_ENV),
            synth_mode=synth_mode,
            mode=mode,
            llm_enabled=_flag(source, "MIX_LLM_ENABLED", False),
            llm_url=_get(source, "MIX_LLM_URL", "http://ollama:11434").rstrip("/"),
            llm_model=_get(source, "MIX_LLM_MODEL", "qwen2.5:7b-instruct"),
            llm_max_influence=max(0.0, min(1.0, _number(source, "MIX_LLM_MAX_INFLUENCE", 0.2))),
            ai_timeout_ms=_integer(source, "MIX_AI_TIMEOUT_MS", 10_000),
            embeddings_enabled=_flag(source, "MIX_EMBEDDINGS_ENABLED", False),
            mix_length=_integer(source, "MIX_MIX_LENGTH", 30),
            no_repeat_days=_integer(source, "MIX_NO_REPEAT_DAYS", 14),
            weather_provider=_get(source, "MIX_WEATHER_PROVIDER", "none").lower(),
            weather_api_key=_get(source, "MIX_WEATHER_API_KEY", ""),
            weather_lat=_number(source, "MIX_WEATHER_LAT", 0.0) or None,
            weather_lon=_number(source, "MIX_WEATHER_LON", 0.0) or None,
            event_retention_days=_integer(source, "MIX_EVENT_RETENTION_DAYS", 180),
            log_level=_get(source, "MIX_LOG_LEVEL", "INFO").upper(),
            gateway_url=_get(source, "MIX_GATEWAY_URL", "").rstrip("/"),
            version=_get(source, "MIX_VERSION", "0.1.0"),
        )

    @property
    def effective_synth_mode(self) -> str:
        if self.synth_mode != "ai":
            return self.synth_mode
        if self.llm_enabled:
            return "ai"
        return "hybrid" if self.embeddings_enabled else "algo"

    @property
    def offline(self) -> bool:
        return self.mode == "offline_first"