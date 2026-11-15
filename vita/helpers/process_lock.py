"""Operating-system file locks that are released when the owning process exits."""

import os
import time
from contextlib import contextmanager
from functools import partial


class LockBusy(OSError):
    """Another process owns the lock."""


@contextmanager
def exclusive(path, *, attempts=1, pause=time.sleep):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise OSError("Unsafe lock path")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            # Windows can lock beyond EOF. Writing a byte before acquiring
            # the lock could overwrite a region another process owns.
            acquire = partial(msvcrt.locking, fd, msvcrt.LK_NBLCK, 1)
            release = partial(msvcrt.locking, fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            acquire = partial(fcntl.flock, fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = partial(fcntl.flock, fd, fcntl.LOCK_UN)
        for attempt in range(attempts):
            try:
                acquire()
                break
            except (BlockingIOError, PermissionError) as exc:
                if attempt + 1 == attempts:
                    raise LockBusy("File lock is already held") from exc
                pause(0.01)
        try:
            yield
        finally:
            release()
    finally:
        os.close(fd)
