"""Persistent, user-controlled privacy settings. No model can change these."""

import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading


class PrivacyBlocked(RuntimeError):
    pass


class PrivacyControls:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.lock = threading.RLock()
        self.tasks = set()
        self.generation = 0
        maintenance = os.environ.get("BLOB_MAINTENANCE_PATH", "")
        self.maintenance_path = Path(maintenance) if maintenance else None
        self.state = {"paused": False, "cloud_enabled": False, "approved_folders": [], "disabled_skills": [],
                      "awareness_enabled": False, "proactive_enabled": False, "active_project": None}
        if self.path.exists():
            data = json.loads(self.path.read_text())
            if (not isinstance(data, dict) or type(data.get("paused")) is not bool or
                    type(data.get("cloud_enabled")) is not bool or
                    ("awareness_enabled" in data and type(data["awareness_enabled"]) is not bool) or
                    ("proactive_enabled" in data and type(data["proactive_enabled"]) is not bool) or
                    (data.get("active_project") is not None and not isinstance(data["active_project"], str)) or
                    any(not isinstance(data.get(key), list) or
                        any(not isinstance(item, str) for item in data[key])
                        for key in ("approved_folders", "disabled_skills"))):
                raise ValueError("Invalid privacy settings; refusing to start. Repair the privacy JSON file.")
            self.state.update({key: data[key] for key in self.state if key in data})

    @property
    def paused(self):
        return self.state["paused"]

    def maintaining(self):
        return bool(self.maintenance_path and self.maintenance_path.exists())

    @property
    def cloud_enabled(self):
        return self.state["cloud_enabled"]

    @property
    def folders(self):
        return tuple(Path(path) for path in self.state["approved_folders"])

    def update(self, **changes):
        with self.lock:
            state = {**self.state, **changes}
            if "approved_folders" in changes and state["active_project"] and not any(
                    Path(state["active_project"]).is_relative_to(root) for root in state["approved_folders"]):
                state["active_project"] = None
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.path.parent.stat().st_mode & 0o077:
                raise ValueError("Privacy settings must be stored in a private directory (0700).")
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as file:
                temporary = Path(file.name)
                json.dump(state, file, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            try:
                os.chmod(temporary, 0o600)
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
            self.state = state
            self.generation += 1

    def cancel_requests(self):
        current = asyncio.current_task()
        for task in tuple(self.tasks):
            if task is not current:
                task.cancel()

    @contextmanager
    def operation(self, *, cloud=False):
        self.check(cloud=cloud)
        task = asyncio.current_task()
        already_tracked = task in self.tasks
        if task:
            self.tasks.add(task)
        try:
            yield
        finally:
            if task and not already_tracked:
                self.tasks.discard(task)

    def check(self, *, cloud=False):
        if self.maintaining():
            raise PrivacyBlocked("Blob is updating. Please retry when maintenance finishes.")
        if self.paused:
            raise PrivacyBlocked("Privacy pause is active. Use /privacy resume to continue.")
        if cloud and not self.cloud_enabled:
            raise PrivacyBlocked("Cloud assistance is off. Local commands still work. /privacy explain describes data sharing; /privacy cloud on enables it.")

    @contextmanager
    def writing(self):
        with self.lock:
            self.check()
            yield

    def write(self, function, *args, **kwargs):
        with self.writing():
            return function(*args, **kwargs)

    def deferred_write(self, function):
        generation = self.generation
        def guarded(*args, **kwargs):
            with self.writing():
                if self.generation != generation:
                    raise PrivacyBlocked("Storage cancelled because privacy settings changed.")
                return function(*args, **kwargs)
        return guarded

    def approve(self, folder):
        path = Path(folder).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError("Choose an existing folder.")
        # Avoid accidentally approving all user data or system configuration.
        if path in {Path("/"), Path.home(), Path("/home"), Path("/tmp"), Path("/etc"), Path("/usr"), Path("/var"), Path("/proc"), Path("/dev"), Path("/run")}:
            raise ValueError("Choose a specific project or document folder, rather than a home or system root.")
        if any(part in {".ssh", ".aws", ".gnupg", ".blob", ".codex"} for part in path.parts):
            raise ValueError("Credential and Blob storage folders cannot be approved for tools.")
        self.update(approved_folders=sorted(set([*self.state["approved_folders"], str(path)])))
        return path

    def allows(self, path):
        resolved = Path(path).expanduser().resolve()
        return any(resolved.is_relative_to(root) for root in self.folders)

    def project_directory(self, requested=None):
        """Resolve an invocation's directory without silently choosing a project."""
        selected = requested or self.state["active_project"]
        if not selected:
            if len(self.folders) != 1:
                raise PrivacyBlocked("Select a project with /skills project /approved/path before running commands.")
            selected = self.folders[0]
        try:
            path = Path(selected).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PrivacyBlocked("The selected project is unavailable. Review /skills project.") from exc
        if not path.is_dir() or not self.allows(path):
            raise PrivacyBlocked("The project must be a directory inside an approved folder. Use /privacy folders.")
        if any(part in {".ssh", ".aws", ".gnupg", ".blob", ".codex"} for part in path.parts):
            raise PrivacyBlocked("Credential and Blob storage folders cannot be selected as projects.")
        return path

    def select_project(self, path=None):
        with self.lock:
            self.check()
            selected = str(self.project_directory(path)) if path is not None else None
            self.update(active_project=selected)
            return selected
