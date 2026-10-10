from __future__ import annotations

import json
from pathlib import Path

import pytest

from mixcore.storage.atomic import atomic_write_json, atomic_write_json_gz, read_json
from mixcore.storage.journal import JsonlJournal, RotatingJsonlJournal
from mixcore.storage.jsonstore import JsonStore, SchemaVersion
from mixcore.storage.layout import Layout
from mixcore.storage.lock import LockError, WriterLock


def test_layout_creates_expected_tree(tmp_path: Path) -> None:
    layout = Layout.create(tmp_path / "state")
    for relative in ("state/profiles", "state/mixes", "logs/play_events", "logs/collab_ops", "cache", "vectors"):
        assert (layout.root / relative).is_dir()


def test_atomic_write_leaves_no_partial_file(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "state.json"
    atomic_write_json(target, {"value": 1})
    assert read_json(target) == {"value": 1}
    assert not list(target.parent.glob(".*.tmp*"))


def test_gzip_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "cache.json.gz"
    atomic_write_json_gz(target, [{"id": "t-1"}, {"id": "t-2"}])
    assert read_json(target) == [{"id": "t-1"}, {"id": "t-2"}]


def test_writer_lock_rejects_second_instance(tmp_path: Path) -> None:
    lock_path = tmp_path / "lock"
    first = WriterLock(lock_path)
    first.acquire()
    try:
        with pytest.raises(LockError):
            WriterLock(lock_path).acquire()
    finally:
        first.release()
    second = WriterLock(lock_path)
    second.acquire()
    second.release()


def test_schema_version_refuses_newer_state(tmp_path: Path) -> None:
    schema = SchemaVersion(tmp_path, current=2)
    schema.write(3)
    with pytest.raises(Exception):
        schema.check()


def test_json_store_update_is_read_modify_write(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "state" / "users.json")

    def add(payload: dict) -> str:
        payload["count"] = payload.get("count", 0) + 1
        return str(payload["count"])

    assert store.update(add, default={}) == "1"
    assert store.update(add, default={}) == "2"
    assert json.loads((tmp_path / "state" / "users.json").read_text(encoding="utf-8"))["count"] == 2


def test_jsonl_journal_is_append_only_and_readable(tmp_path: Path) -> None:
    journal = JsonlJournal(tmp_path / "ops.jsonl")
    journal.append({"seq": 1, "op": "add"})
    journal.append({"seq": 2, "op": "remove"})
    records = journal.read_all()
    assert [r["seq"] for r in records] == [1, 2]
    journal.extend([{"seq": 3, "op": "move"}])
    assert len(journal.read_all()) == 3


def test_rotating_journal_filters_by_period(tmp_path: Path) -> None:
    journal = RotatingJsonlJournal(tmp_path)
    journal.append({"ts": 1_700_000_000, "kind": "play"}, timestamp=1_700_000_000)
    journal.append({"ts": 1_800_000_000, "kind": "play"}, timestamp=1_800_000_000)
    all_records = list(journal.iter_range())
    assert len(all_records) == 2
    filtered = list(journal.iter_range(since=1_750_000_000))
    assert len(filtered) == 1


def test_cache_directory_is_disposable(tmp_path: Path) -> None:
    layout = Layout.create(tmp_path)
    layout.track_meta.save({"tracks": [{"id": "t-1"}]})
    assert layout.track_meta.load()["tracks"][0]["id"] == "t-1"
    for path in layout.cache_dir().iterdir():
        path.unlink()
    assert layout.track_meta.load() is None