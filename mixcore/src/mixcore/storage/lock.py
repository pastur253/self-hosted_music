from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType

_HELD: dict[str, int] = {}


class LockError(RuntimeError):
    pass


class WriterLock:
    """Advisory-блокировка каталога состояния: единственный активный писатель (NFR-S04)."""

    def __init__(self, path: Path, *, blocking: bool = False) -> None:
        self._path = path
        self._blocking = blocking
        self._fd: int | None = None

    @property
    def key(self) -> str:
        return str(self._path.resolve()) if self._path.exists() else str(self._path.absolute())

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        key = self.key
        if key in _HELD:
            raise LockError(
                f"Каталог состояния {self._path.parent} уже заблокирован в этом процессе (NFR-S04, AC-N13)."
            )
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _lock(fd, blocking=self._blocking)
        except OSError as exc:
            os.close(fd)
            raise LockError(
                f"Каталог состояния {self._path.parent} уже занят другим процессом MixCore "
                f"({self._holder()}). Второй активный инстанс недопустим (NFR-S04, AC-N13)."
            ) from exc
        os.ftruncate(fd, 0)
        os.write(fd, f"pid={os.getpid()}\n".encode())
        self._fd = fd
        _HELD[key] = os.getpid()

    def release(self) -> None:
        if self._fd is None:
            return
        _HELD.pop(self.key, None)
        try:
            _unlock(self._fd)
        finally:
            os.close(self._fd)
            self._fd = None

    def _holder(self) -> str:
        try:
            return self._path.read_text(encoding="utf-8").replace("\n", " ").strip() or "неизвестно"
        except OSError:
            return "неизвестно"

    def __enter__(self) -> WriterLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


def _lock(fd: int, *, blocking: bool) -> None:
    try:
        import fcntl
    except ModuleNotFoundError:
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
        return
    flags = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
    fcntl.flock(fd, flags)


def _unlock(fd: int) -> None:
    try:
        import fcntl
    except ModuleNotFoundError:
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    fcntl.flock(fd, fcntl.LOCK_UN)