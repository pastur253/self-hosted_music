from __future__ import annotations

import gzip
import json
import os
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from .atomic import append_jsonl, ensure_dir, read_jsonl

COMPACT_SUFFIX = ".gz"


class JsonlJournal:
    """Append-only журнал: порядок значим, записи только добавляются (7.4)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: Mapping[str, Any]) -> None:
        append_jsonl(self._path, record)

    def extend(self, records: list[Mapping[str, Any]]) -> None:
        for record in records:
            self.append(record)

    def read_all(self) -> list[dict[str, Any]]:
        return [dict(item) for item in read_jsonl(self._path)]

    def iter(self) -> Iterator[dict[str, Any]]:
        if not self._path.exists():
            return iter(())
        opener = gzip.open if self._path.suffix == COMPACT_SUFFIX else open
        with opener(self._path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)

    def tail(self, limit: int) -> list[dict[str, Any]]:
        return self.read_all()[-limit:] if limit > 0 else []

    def compact(self, *, keep_last: int = 0) -> Path:
        ensure_dir(self._path.parent)
        target = self._path.with_suffix(self._path.suffix + COMPACT_SUFFIX)
        records = self.read_all()
        if keep_last > 0:
            head, tail = records[:-keep_last], records[-keep_last:]
        else:
            head, tail = records, []
        raw = "\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in head)
        tmp = target.with_suffix(target.suffix + ".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as handle:
            handle.write(raw + ("\n" if head else ""))
        os.replace(tmp, target)
        os.unlink(self._path)
        if tail:
            with open(self._path, "a", encoding="utf-8") as handle:
                for record in tail:
                    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return target


class RotatingJsonlJournal:
    """Журнал с ротацией по периодам: logs/play_events/YYYY-MM.jsonl (7.4)."""

    def __init__(self, directory: Path, *, prefix: str = "event") -> None:
        self._dir = ensure_dir(directory)
        self._prefix = prefix

    def _path_for(self, timestamp: float) -> Path:
        period = time.strftime("%Y-%m", time.gmtime(timestamp))
        return self._dir / f"{period}.jsonl"

    def append(self, record: Mapping[str, Any], *, timestamp: float | None = None) -> Path:
        path = self._path_for(timestamp if timestamp is not None else time.time())
        append_jsonl(path, record)
        return path

    def iter_range(self, since: float | None = None) -> Iterator[dict[str, Any]]:
        for path in sorted(self._dir.glob("*.jsonl*")):
            for record in self._iter_file(path):
                if since is None or float(record.get("ts", 0)) >= since:
                    yield record

    def count(self) -> int:
        return sum(1 for _ in self.iter_range())

    def compact_all(self) -> list[Path]:
        result: list[Path] = []
        for path in sorted(self._dir.glob("*.jsonl")):
            if path.stat().st_size < 1_048_576:
                continue
            target = path.with_suffix(".jsonl" + COMPACT_SUFFIX)
            raw = path.read_text(encoding="utf-8")
            with gzip.open(target, "wt", encoding="utf-8") as handle:
                handle.write(raw)
            os.replace(target, path)
            result.append(path)
        return result

    @staticmethod
    def _iter_file(path: Path) -> Iterator[dict[str, Any]]:
        opener = gzip.open if path.suffix == COMPACT_SUFFIX else open
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)