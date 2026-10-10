from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .atomic import ensure_dir
from .jsonstore import JsonStore, SchemaVersion
from .journal import JsonlJournal, RotatingJsonlJournal


@dataclass(frozen=True, slots=True)
class Layout:
    root: Path

    @classmethod
    def create(cls, root: Path) -> Layout:
        ensure_dir(root)
        ensure_dir(root / "state")
        ensure_dir(root / "state" / "profiles")
        ensure_dir(root / "state" / "mixes")
        ensure_dir(root / "state" / "synth_instances")
        ensure_dir(root / "state" / "collab")
        ensure_dir(root / "logs")
        ensure_dir(root / "logs" / "play_events")
        ensure_dir(root / "logs" / "collab_ops")
        ensure_dir(root / "logs" / "outbox")
        ensure_dir(root / "logs" / "mix_runs")
        ensure_dir(root / "cache")
        ensure_dir(root / "vectors")
        return cls(root)

    @property
    def lock_path(self) -> Path:
        return self.root / "lock"

    @property
    def schema(self) -> SchemaVersion:
        return SchemaVersion(self.root)

    @property
    def users(self) -> JsonStore:
        return JsonStore(self.root / "state" / "users.json")

    @property
    def synth_templates(self) -> JsonStore:
        return JsonStore(self.root / "state" / "synth_templates.json")

    @property
    def feature_weights(self) -> JsonStore:
        return JsonStore(self.root / "state" / "feature_weights.json")

    @property
    def model_versions(self) -> JsonStore:
        return JsonStore(self.root / "state" / "model_versions.json")

    @property
    def api_keys(self) -> JsonStore:
        return JsonStore(self.root / "state" / "api_keys.json")

    @property
    def collab_playlists(self) -> JsonStore:
        return JsonStore(self.root / "state" / "collab" / "playlists.json")

    @property
    def collab_members(self) -> JsonStore:
        return JsonStore(self.root / "state" / "collab" / "members.json")

    @property
    def track_meta(self) -> JsonStore:
        return JsonStore(self.root / "cache" / "track_meta.json.gz")

    @property
    def weather(self) -> JsonStore:
        return JsonStore(self.root / "cache" / "weather.json.gz")

    @property
    def library_index(self) -> Path:
        return self.root / "cache" / "library.index"

    @property
    def vectors(self) -> Path:
        return self.root / "vectors"

    def profile(self, user_id: str) -> JsonStore:
        return JsonStore(self.root / "state" / "profiles" / f"{_safe(user_id)}.json")

    def mix(self, mix_id: str) -> JsonStore:
        return JsonStore(self.root / "state" / "mixes" / f"{_safe(mix_id)}.json")

    def synth_instances(self, user_id: str) -> JsonStore:
        return JsonStore(self.root / "state" / "synth_instances" / f"{_safe(user_id)}.json")

    def play_events(self) -> RotatingJsonlJournal:
        return RotatingJsonlJournal(self.root / "logs" / "play_events", prefix="event")

    def mix_runs(self) -> RotatingJsonlJournal:
        return RotatingJsonlJournal(self.root / "logs" / "mix_runs", prefix="run")

    def collab_ops(self, playlist_id: str) -> JsonlJournal:
        return JsonlJournal(self.root / "logs" / "collab_ops" / f"{_safe(playlist_id)}.jsonl")

    def outbox(self) -> JsonlJournal:
        return JsonlJournal(self.root / "logs" / "outbox" / "pending.jsonl")

    @property
    def audit_log(self) -> Path:
        return self.root / "logs" / "audit.log"

    def mix_ids(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "state" / "mixes").glob("*.json"))

    def user_ids(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "state" / "profiles").glob("*.json"))

    def cache_dir(self) -> Path:
        return self.root / "cache"

    def vectors_dir(self) -> Path:
        return self.root / "vectors"


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value) or "unnamed"