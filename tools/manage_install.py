"""Manage tested desktop installations; backups retain data when uninstalling."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import uuid

from install_desktop import RUNTIME_PATH_VARIABLES, desktop_targets, wait_ready
from install_state import atomic_json, checked_path, restore, snapshot, verify


PROJECT = Path(__file__).resolve().parents[1]
UNITS = ("blob-backend.service", "blob-overlay.service")
DATA_FIELDS = set(RUNTIME_PATH_VARIABLES) - {"ipc_address", "ipc_token_path"}


class Installation:
    def __init__(self, project=PROJECT):
        self.project = Path(project).resolve()
        self.state = self.project / ".runtime/desktop"
        self.current = self.state / "current"
        self.marker = self.state / "maintenance"
        self.journal = self.state / "transaction.json"
        identifier = hashlib.sha256(str(self.project).encode()).hexdigest()[:12]
        self.backups = Path.home() / ".blob/install_backups" / identifier
        self.targets = desktop_targets()

    def run(self, args, *, check=True, env=None):
        return subprocess.run([str(arg) for arg in args], cwd=self.project, env=env,
                              capture_output=True, text=True, check=check, timeout=60)

    def systemctl(self, *args, check=True):
        return self.run(["systemctl", "--user", *args], check=check)

    @contextmanager
    def locked(self):
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.state / "maintenance.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(descriptor)

    def require_owned(self, *, managed=True):
        if os.path.lexists(self.current) and not self.current.is_symlink():
            raise ValueError("Unexpected non-symlink installation pointer")
        if managed and not self.current.is_symlink():
            raise ValueError("Updates require a managed installation. This editable/manual installation is unchanged; use --prepare-only to verify a candidate. Code rollback needs an immutable previous runtime.")
        if self.current.is_symlink():
            candidate = self.current.resolve(strict=True)
            if candidate.parent != self.state / "releases" or not (candidate / "installation.json").is_file():
                raise ValueError("Invalid managed installation pointer")
        for unit in UNITS:
            target = self.targets["systemd/user/" + unit]
            if target.is_symlink() or not target.is_file():
                raise ValueError("Expected regular Blob user service files")
            content = target.read_text()
            if ("Description=Project Blob" not in content or
                    "WorkingDirectory=" + str(self.project).replace("%", "%%") + "\n" not in content):
                raise ValueError("A Blob service belongs to another installation; refusing to replace it")
            dropins = self.systemctl("show", unit, "--property=DropInPaths", "--value").stdout.strip()
            if dropins:
                raise ValueError("Custom systemd drop-ins need manual review before managed updates")
            fragment = self.systemctl("show", unit, "--property=FragmentPath", "--value").stdout.strip()
            if Path(fragment) != target:
                raise ValueError("The loaded service differs from the expected user service file")
        for name, target in self.targets.items():
            if name.startswith(("autostart/", "applications/")) and target.exists():
                expected = "Path=" + str(self.project).replace("\\", "\\\\") + "\n"
                if target.is_symlink() or expected not in target.read_text():
                    raise ValueError("A desktop launcher belongs to another installation")

    def interpreter(self):
        root = self.current.resolve() if self.current.is_symlink() else self.project
        python = root / "venv/bin/python"
        if not python.is_file():
            raise ValueError("Cannot locate the existing Blob interpreter")
        return python

    def runtime_paths(self):
        output = self.systemctl("show", UNITS[0], "--property=Environment", "--value").stdout
        env = os.environ.copy()
        for item in shlex.split(output):
            key, separator, value = item.partition("=")
            if separator and key in RUNTIME_PATH_VARIABLES.values():
                env[key] = value
        # Capture only paths/endpoints, never provider credentials or conversation data.
        script = ("import json; from blob.config import BlobConfig; c=BlobConfig.load(); "
                  "print(json.dumps({k:str(getattr(c,k)) for k in " + repr(sorted(RUNTIME_PATH_VARIABLES)) + "}))")
        data = json.loads(self.run([self.interpreter(), "-c", script], env=env).stdout)
        for key in DATA_FIELDS | {"ipc_token_path"}:
            data[key] = str(Path(data[key]).expanduser().resolve())
        return data

    def activity(self):
        return {"active": {unit: self.systemctl("is-active", "--quiet", unit, check=False).returncode == 0 for unit in UNITS},
                "enabled": {unit: self.systemctl("is-enabled", "--quiet", unit, check=False).returncode == 0 for unit in UNITS}}

    def resume_activity(self, state):
        for unit in UNITS:
            self.systemctl("enable" if state["enabled"][unit] else "disable", unit)
        active = [unit for unit in UNITS if state["active"][unit]]
        inactive = [unit for unit in UNITS if not state["active"][unit]]
        if inactive:
            self.systemctl("stop", *inactive)
        if active:
            self.systemctl("start", *active)

    def quiesce(self, paths, activity):
        atomic_json(self.marker, {"operation": "maintenance", "activity": activity})
        self.systemctl("stop", *reversed(UNITS))
        env = {**os.environ, **{RUNTIME_PATH_VARIABLES[key]: value for key, value in paths.items()}}
        response = self.run([self.interpreter(), "-m", "blob.client", "--status"], check=False, env=env)
        if response.returncode == 0:
            raise ValueError("A separate Blob backend is still running. Stop that manual process before maintenance.")

    def make_backup(self, paths, activity):
        self.backups.mkdir(parents=True, exist_ok=True, mode=0o700)
        root = self.backups / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
        entries = {key: value for key, value in paths.items() if key in DATA_FIELDS}
        entries.update({"startup:" + name: str(target) for name, target in self.targets.items()})
        entries.update({"configuration:.env": str(self.project / ".env"),
                        "configuration:config.yaml": str(self.project / "config.yaml"),
                        "configuration:runtime_paths": str(self.state / "runtime-paths.json")})
        metadata = {"paths": paths, "activity": activity,
                    "runtime": str(self.current.resolve()) if self.current.is_symlink() else None,
                    "created_at": datetime.now(timezone.utc).isoformat()}
        snapshot(root, self.project, entries, metadata)
        return root

    def set_current(self, candidate):
        candidate = Path(candidate).resolve(strict=True)
        if candidate.parent != self.state / "releases":
            raise ValueError("Runtime must belong to this installation's release directory")
        temporary = self.state / (".current-" + uuid.uuid4().hex)
        temporary.symlink_to(candidate, target_is_directory=True)
        os.replace(temporary, self.current)

    def backup(self):
        with self.locked():
            self.require_owned(managed=False)
            if self.journal.exists() or self.marker.exists():
                raise ValueError("An interrupted transaction needs recover first")
            paths, activity = self.runtime_paths(), self.activity()
            try:
                self.quiesce(paths, activity)
                root = self.make_backup(paths, activity)
            finally:
                self.marker.unlink(missing_ok=True)
                self.resume_activity(activity)
            return root

    def _recover(self, root):
        manifest = verify(root, self.project)
        self.systemctl("stop", *reversed(UNITS))
        restore(root, self.project)
        previous = manifest["metadata"]["runtime"]
        if previous:
            self.set_current(previous)
        self.systemctl("daemon-reload")
        self.resume_activity(manifest["metadata"]["activity"])
        self.marker.unlink(missing_ok=True)
        self.journal.unlink(missing_ok=True)

    def recover(self):
        with self.locked():
            if not self.journal.exists():
                self.require_owned(managed=False)
                if not self.marker.exists():
                    raise ValueError("No interrupted maintenance operation to recover")
                interrupted = json.loads(self.marker.read_text())
                self.resume_activity(interrupted["activity"])
                self.marker.unlink()
                return
            transaction = json.loads(self.journal.read_text())
            if transaction.get("phase") == "committed":
                raise ValueError("The update committed. Use explicit rollback --restore-data for a point-in-time restore.")
            self._recover(Path(transaction["backup"]))

    def upgrade(self, candidate):
        candidate = Path(candidate).resolve(strict=True)
        if candidate.parent != self.state / "releases":
            raise ValueError("Choose a verified candidate from this project's release directory")
        metadata = json.loads((candidate / "installation.json").read_text())
        if (metadata.get("verified") is not True or metadata.get("maintenance_supported") is not True or
                metadata.get("project") != str(self.project)):
            raise ValueError("Candidate must pass the current setup checks and support maintenance admission control")
        with self.locked():
            self.require_owned()
            if self.journal.exists() or self.marker.exists():
                raise ValueError("Recover or inspect the previous transaction before another update")
            paths, activity = self.runtime_paths(), self.activity()
            root = None
            committed = False
            try:
                self.quiesce(paths, activity)
                root = self.make_backup(paths, activity)
                atomic_json(self.journal, {"phase": "switching", "backup": str(root)})
                # Preserve effective resources in a stable private location,
                # including custom defaults from legacy package layouts.
                resources = self.state / "resources"
                resources.mkdir(mode=0o700, exist_ok=True)
                for key in ("blacklist_path", "personality_path"):
                    target = resources / (key + ".yaml")
                    source = checked_path(paths[key])
                    if source != target:
                        shutil.copy2(source, target)
                    paths[key] = str(target)
                overrides = candidate / "runtime-paths.json"
                atomic_json(overrides, paths)
                staged = candidate / "update-preview"
                self.run([candidate / "venv/bin/python", self.project / "tools/install_desktop.py",
                          "--overlay", candidate / "frontend/blob_overlay", "--runtime-paths", overrides,
                          "--stage-dir", staged])
                for name, target in self.targets.items():
                    # Keep the user's decision to remove or disable login startup.
                    if name.startswith(("autostart/", "applications/")) and not target.exists():
                        continue
                    content = (staged / name).read_text()
                    if name.startswith(("autostart/", "applications/")):
                        replacements = {line.split("=", 1)[0]: line for line in content.splitlines()
                                        if line.startswith(("Exec=", "Path="))}
                        content = "\n".join(replacements.get(line.split("=", 1)[0], line)
                                            for line in target.read_text().splitlines()) + "\n"
                    descriptor, temporary = tempfile.mkstemp(prefix=".blob-unit-", dir=target.parent)
                    try:
                        with os.fdopen(descriptor, "w") as output:
                            output.write(content)
                            output.flush()
                            os.fsync(output.fileno())
                        os.replace(temporary, target)
                    finally:
                        if os.path.exists(temporary):
                            os.unlink(temporary)
                self.systemctl("daemon-reload")
                self.run([candidate / "venv/bin/python", "-m", "blob.desktop", "--startup"])
                probe_env = {**os.environ, **{RUNTIME_PATH_VARIABLES[key]: value for key, value in paths.items()}}
                wait_ready(self.project, candidate / "venv/bin/python", probe_env)
                self.set_current(candidate)
                atomic_json(self.state / "runtime-paths.json", paths)
                # After this durable commit, normal requests may be admitted.
                # A process crash before marker removal is safe to finish via
                # resume-commit; it must not silently reset new user data.
                atomic_json(self.journal, {"phase": "committed", "backup": str(root)})
                committed = True
                self.marker.unlink(missing_ok=True)
                self.resume_activity(activity)
                self.journal.unlink(missing_ok=True)
                return root
            except BaseException:
                if root is not None and (root / "manifest.json").exists() and not committed:
                    self._recover(root)
                elif not committed:
                    self.marker.unlink(missing_ok=True)
                    self.resume_activity(activity)
                raise

    def rollback(self, root, *, restore_data=False):
        manifest = verify(root, self.project)
        if not restore_data:
            raise ValueError("Rollback restores the backup's data as well as code. Review its timestamp and pass --restore-data; a new safety backup is made first.")
        if not manifest["metadata"].get("runtime"):
            raise ValueError("This legacy/editable backup has no immutable code version for rollback")
        with self.locked():
            self.require_owned()
            if self.journal.exists() or self.marker.exists():
                raise ValueError("Recover or inspect the previous transaction before rollback")
            paths, activity = self.runtime_paths(), self.activity()
            self.quiesce(paths, activity)
            try:
                safety = self.make_backup(paths, activity)
                atomic_json(self.journal, {"phase": "restoring", "backup": str(root), "safety_backup": str(safety)})
                self._recover(root)
                return safety
            except BaseException:
                # Keep admission blocked until an interrupted restore is recovered.
                if not self.journal.exists():
                    self.marker.unlink(missing_ok=True)
                    self.resume_activity(activity)
                raise

    def uninstall(self):
        with self.locked():
            self.require_owned(managed=False)
            if self.journal.exists() or self.marker.exists():
                raise ValueError("Recover the interrupted transaction before uninstalling")
            self.systemctl("stop", *reversed(UNITS))
            self.systemctl("disable", *UNITS)
            for target in self.targets.values():
                if target.is_symlink():
                    raise ValueError("Unexpected symlink in a desktop startup file")
                target.unlink(missing_ok=True)
            self.systemctl("daemon-reload")
            self.current.unlink(missing_ok=True)
            self.marker.unlink(missing_ok=True)
            # Runtime files, credentials, personal data and backups are retained.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "backup", "update", "rollback", "recover", "resume-commit", "uninstall"))
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--restore-data", action="store_true")
    args = parser.parse_args()
    installation = Installation()
    try:
        if args.action == "status":
            print(json.dumps({"runtime": str(installation.current.resolve()) if installation.current.is_symlink() else "manual/editable",
                              "backups": str(installation.backups), "maintenance": installation.marker.exists(),
                              "transaction": (json.loads(installation.journal.read_text())
                                              if installation.journal.exists() else None)}, indent=2))
        elif args.action == "backup":
            print("Backup: " + str(installation.backup()))
        elif args.action in {"update", "rollback"}:
            if args.path is None:
                parser.error("Provide the candidate directory or backup directory")
            root = installation.upgrade(args.path) if args.action == "update" else installation.rollback(args.path, restore_data=args.restore_data)
            print("Recovery backup: " + str(root))
        elif args.action == "recover":
            installation.recover()
            print("Previous installation and data restored.")
        elif args.action == "resume-commit":
            with installation.locked():
                transaction = json.loads(installation.journal.read_text())
                if transaction.get("phase") != "committed":
                    raise ValueError("The interrupted transaction did not commit; use recover")
                verify(transaction["backup"], installation.project)
                installation.marker.unlink(missing_ok=True)
                installation.resume_activity(verify(transaction["backup"], installation.project)["metadata"]["activity"])
                installation.journal.unlink()
                print("Committed installation resumed.")
        else:
            installation.uninstall()
            print("Blob startup removed. Personal data, credentials, runtime files and backups were retained.")
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print("Maintenance stopped: " + str(exc))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
