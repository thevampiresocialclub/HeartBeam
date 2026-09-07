"""OS-backed locks are released on process exit, including crashes."""
from pathlib import Path
import os

from .project import ProjectError


class WriterLease:
    def __init__(self, root: Path, name=".editor.lock"):
        self.file = None
        root.mkdir(parents=True, exist_ok=True)
        handle = open(root / name, "a+b")
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.file = handle
        except OSError as exc:
            handle.close()
            raise ProjectError("This project is open in another editor. Close it there or open a copy.") from exc

    def close(self):
        if self.file:
            self.file.close()
            self.file = None

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
