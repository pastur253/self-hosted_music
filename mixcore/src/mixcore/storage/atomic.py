from __future__ import annotations

import gzip
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class StorageError(RuntimeError):
    pass


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    ensure_dir(path.parent)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        fsync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def atomic_write_text(path: Path, payload: str) -> None:
    atomic_write_bytes(path, payload.encode("utf-8"))


def atomic_write_json(path: Path, payload: Any, *, indent: int = 2) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=True, default=_fallback)
    atomic_write_bytes(path, (text + "\n").encode("utf-8"))


def atomic_write_json_gz(path: Path, payload: Any) -> None:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_fallback)
    atomic_write_bytes(path, gzip.compress(raw.encode("utf-8"), compresslevel=6))


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        text = handle.read()
    if not text.strip():
        return default
    return json.loads(text)


def append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    ensure_dir(path.parent)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=_fallback)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def read_jsonl(path: Path) -> list[Any]:
    if not path.exists():
        return []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _fallback(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Невозможно сериализовать {type(value)!r}")