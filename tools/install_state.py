"""Private, checked snapshots for stopped Blob installations."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".blob-state-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(data, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def checked_path(path, *, directory=False):
    path = Path(path).expanduser().absolute()
    if path.is_symlink() or path.resolve() != path:
        raise ValueError(f"Snapshot paths cannot contain symlinks: {path}")
    if path.exists() and path.stat().st_uid != os.getuid():
        raise ValueError("Installation data must be owned by the current user")
    forbidden = {Path("/"), Path.home(), Path.home() / ".config", Path.home() / ".local",
                 Path.home() / ".local/share", Path.home() / ".cache"}
    forbidden.update(Path.home() / name for name in ("Documents", "Downloads", "Pictures", "Desktop", "Videos", "Music"))
    if directory and path in forbidden:
        raise ValueError(f"Choose a dedicated Blob data directory: {path}")
    if any(part in {".ssh", ".aws", ".gnupg", ".git", ".codex"} for part in path.parts):
        raise ValueError("Credential and repository metadata cannot be installation data")
    if any(path == root or path.is_relative_to(root) for root in map(Path, ("/proc", "/sys", "/dev", "/etc", "/usr", "/run"))):
        raise ValueError("System directories cannot be restored as Blob data")
    return path


def safe_copy(source, target):
    if source.is_symlink():
        raise ValueError(f"Snapshot contains a symlink: {source}")
    if source.is_dir():
        target.mkdir(mode=0o700)
        for item in source.iterdir():
            safe_copy(item, target / item.name)
    elif source.is_file():
        shutil.copy2(source, target)
    else:
        raise ValueError(f"Snapshot requires regular files and directories: {source}")


def hashes(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Backup contains a symlink")
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            result[str(path.relative_to(root))] = digest.hexdigest()
        elif not path.is_dir():
            raise ValueError("Backup contains a non-regular file")
    return result


def check_sqlite(root):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        with path.open("rb") as source:
            sqlite = source.read(16) == b"SQLite format 3\0"
        if sqlite:
            with sqlite3.connect(str(path)) as db:
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError(f"Backup SQLite integrity check failed: {path.name}")


def snapshot(root, project, paths, metadata):
    """Caller must stop all writers before copying SQLite and vector indexes."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    payload = root / "payload"
    payload.mkdir(mode=0o700)
    entries = {}
    for index, (name, raw) in enumerate(paths.items()):
        source = checked_path(raw, directory=Path(raw).is_dir())
        if root.is_relative_to(source):
            raise ValueError("A backup cannot be stored inside its source data")
        folder = payload / str(index)
        folder.mkdir(mode=0o700)
        present = source.exists()
        directory = source.is_dir()
        entries[name] = {"path": str(source), "present": present, "directory": directory, "folder": str(index)}
        if present:
            safe_copy(source, folder / "value")
            if not directory:
                for suffix in ("-wal", "-shm", "-journal"):
                    sidecar = Path(str(source) + suffix)
                    if sidecar.exists():
                        safe_copy(sidecar, folder / ("value" + suffix))
    check_sqlite(payload)
    manifest = {"format": 1, "project": str(Path(project).resolve()), "entries": entries,
                "hashes": hashes(payload), "metadata": metadata}
    atomic_json(root / "manifest.json", manifest)
    return manifest


def verify(root, project):
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("format") != 1 or manifest.get("project") != str(Path(project).resolve()):
        raise ValueError("This backup belongs to a different project or format")
    if hashes(root / "payload") != manifest["hashes"]:
        raise ValueError("Backup is incomplete or modified; refusing to restore")
    for entry in manifest["entries"].values():
        checked_path(entry["path"], directory=entry["directory"])
        if not entry["folder"].isdigit():
            raise ValueError("Invalid backup payload path")
    return manifest


def _replace(source, target):
    """Stage on the destination filesystem; retain the original on copy failure."""
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".blob-restore-", dir=target.parent) as temporary:
        staging = Path(temporary)
        safe_copy(source, staging / "new")
        moved = False
        try:
            if target.exists():
                os.replace(target, staging / "old")
                moved = True
            os.replace(staging / "new", target)
        except BaseException:
            if moved:
                os.replace(staging / "old", target)
            raise


def restore(root, project, *, names=None):
    manifest = verify(root, project)
    for name, entry in manifest["entries"].items():
        if names is not None and name not in names:
            continue
        target = checked_path(entry["path"], directory=entry["directory"])
        folder = Path(root) / "payload" / entry["folder"]
        if entry["present"]:
            _replace(folder / "value", target)
        elif target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if not entry["directory"]:
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = Path(str(target) + suffix)
                saved = folder / ("value" + suffix)
                if saved.exists():
                    _replace(saved, sidecar)
                elif sidecar.exists():
                    sidecar.unlink()
