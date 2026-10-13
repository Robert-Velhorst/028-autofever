"""Same-host process lock shared by dispatch and operator reconciliation.

The sidecar's existence is not a lock. Never remove/replace it while processes
are running. All processes must use this implementation and one canonical DB.
"""
import errno
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path


class DeliveryBusy(Exception):
    pass


@contextmanager
def delivery_lock(database, *, timeout=0):
    database = Path(database)
    if database.is_symlink() or database.stat().st_nlink != 1:
        raise ValueError('Use one dedicated database path without links')
    path = database.resolve().with_name(database.name + '.dispatch.lock')
    if path.is_symlink():
        raise ValueError('Symlink delivery lock refused')
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
            raise ValueError('Use a dedicated regular delivery lock')
        if os.name == 'nt':
            import msvcrt
            def acquire():
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            def release():
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        elif os.name == 'posix':
            import fcntl
            def acquire():
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(fd, fcntl.LOCK_UN)
        else:
            raise ValueError('Unsupported delivery lock platform')
        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                locked = True
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise DeliveryBusy('Delivery is active; retry after the worker stops') from None
                time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        yield
    finally:
        try:
            if locked:
                release()
        finally:
            os.close(fd)
