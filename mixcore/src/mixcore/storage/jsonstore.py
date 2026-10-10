from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from .atomic import StorageError, atomic_write_json, atomic_write_json_gz, read_json

T = TypeVar("T")

SCHEMA_VERSION = 1
SCHEMA_VERSION_FILE = ".schema_version"


class SchemaMismatch(StorageError):
    pass


class JsonStore:
    """JSON-документ в состоянии MixCore: атомарная запись, версия схемы, read-modify-write."""

    def __init__(self, path: Path, *, schema_version: int = SCHEMA_VERSION) -> None:
        self._path = path
        self._schema_version = schema_version

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def load(self, default: Any = None) -> Any:
        return read_json(self._path, default)

    def save(self, payload: Any) -> None:
        if self._path.suffix == ".gz":
            atomic_write_json_gz(self._path, payload)
        else:
            atomic_write_json(self._path, payload)

    def update(self, mutator: Callable[[Any], T], default: Any = None) -> T:
        current = self.load(default if default is not None else {})
        result = mutator(current)
        self.save(current)
        return result

    def ensure(self, payload: Any) -> None:
        if not self._path.exists():
            atomic_write_json(self._path, payload)


class SchemaVersion:
    def __init__(self, root: Path, *, current: int = SCHEMA_VERSION) -> None:
        self._root = root
        self._current = current
        self._path = root / SCHEMA_VERSION_FILE

    def read(self) -> int | None:
        if not self._path.exists():
            return None
        raw = self._path.read_text(encoding="utf-8").strip()
        try:
            return int(raw)
        except ValueError:
            return None

    def write(self, version: int) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(str(version), encoding="utf-8")
        tmp.replace(self._path)

    def check(self) -> int | None:
        stored = self.read()
        if stored is None:
            self.write(self._current)
            return None
        if stored > self._current:
            raise SchemaMismatch(
                f"Каталог {self._root} подготовлен более новой версией MixCore (схема {stored} > {self._current}). "
                f"Обновите образ MixCore или восстановите состояние из бэкапа."
            )
        return stored

    @property
    def current(self) -> int:
        return self._current

    def migrations_available(self) -> list[int]:
        stored = self.read()
        if stored is None:
            return []
        return list(range(stored + 1, self._current + 1))

    def dump(self) -> str:
        return json.dumps({"schema_version": self.read() or self._current, "supported": self._current})