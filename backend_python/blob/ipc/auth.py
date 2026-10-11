"""Per-user IPC credentials, kept outside model context and logs."""

import os
from pathlib import Path
import secrets
import stat


def ipc_token(path, *, create=False):
    path = Path(path).expanduser()
    if create:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.parent.stat().st_mode & 0o077:
            raise ValueError("IPC credentials must be stored in a private directory (0700).")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as file:
                file.write(secrets.token_hex(32) + "\n")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd) as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("IPC token must be a private, user-owned regular file (0600).")
        token = file.read(256).strip()
    if len(token) != 64 or any(char not in "0123456789abcdef" for char in token):
        raise ValueError("Invalid IPC token file.")
    return token
