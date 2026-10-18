"""Installation snapshots and switch failure paths use only disposable files/services."""

import importlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest


@pytest.fixture
def modules(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return importlib.import_module("install_state"), importlib.import_module("manage_install")


def test_sqlite_and_source_snapshot_restore_exactly_and_reject_tampering(modules, tmp_path):
    state, _ = modules
    project = tmp_path / "project"
    project.mkdir()
    database = project / "reminders.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE facts (text TEXT)")
        db.execute("INSERT INTO facts VALUES ('before update')")
    snapshot = tmp_path / "private-backup"
    state.snapshot(snapshot, project, {"reminders": str(database)}, {"runtime": "synthetic"})
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM facts")
    state.restore(snapshot, project)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT text FROM facts").fetchone()[0] == "before update"
    (snapshot / "payload/0/value").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="modified"):
        state.restore(snapshot, project)
    assert snapshot.stat().st_mode & 0o777 == 0o700


def test_symlinks_and_broad_directories_are_rejected(modules, tmp_path):
    state, _ = modules
    root = tmp_path / "store"
    root.mkdir()
    secret = tmp_path / "outside-secret"
    secret.write_text("must not be copied")
    (root / "escape").symlink_to(secret)
    with pytest.raises(ValueError, match="symlink"):
        state.snapshot(tmp_path / "backup", tmp_path, {"store": str(root)}, {})
    assert not (tmp_path / "backup/manifest.json").exists()
    with pytest.raises(ValueError, match="dedicated"):
        state.checked_path(Path.home(), directory=True)


def test_restore_copy_failure_preserves_original(modules, monkeypatch, tmp_path):
    state, _ = modules
    original, saved = tmp_path / "original", tmp_path / "saved"
    original.write_text("current data")
    saved.write_text("backup data")
    def disk_full(*args):
        raise OSError("No space left on device")
    monkeypatch.setattr(state, "safe_copy", disk_full)
    with pytest.raises(OSError, match="space"):
        state._replace(saved, original)
    assert original.read_text() == "current data"


@pytest.fixture
def installation(modules, monkeypatch, tmp_path):
    state, manager = modules
    project = tmp_path / "Project with % space"
    project.mkdir()
    previous = project / ".runtime/desktop/releases/previous"
    candidate = previous.parent / "candidate"
    for root in (previous, candidate):
        (root / "venv/bin").mkdir(parents=True)
        (root / "venv/bin/python").write_text("test interpreter placeholder")
        (root / "installation.json").write_text(json.dumps({"project": str(project), "verified": True, "maintenance_supported": True}))
    current = project / ".runtime/desktop/current"
    current.symlink_to(previous)
    data = tmp_path / "app-state"
    data.mkdir()
    memory = data / "memory"
    memory.mkdir()
    (memory / "user-fact").write_text("original user fact")
    paths = {"memory_db_path": str(memory), "privacy_settings_path": str(data / "privacy.json"),
        "reminders_db_path": str(data / "reminders.sqlite3"), "documents_dir_path": str(data / "documents"),
        "face_db_path": str(data / "faces"), "skills_dir_path": str(data / "skills"),
        "blacklist_path": str(data / "blacklist.yaml"), "personality_path": str(data / "personality.yaml"),
        "ipc_address": "unix:" + str(data / "ipc.sock"), "ipc_token_path": str(data / "token")}
    for key in ("blacklist_path", "personality_path"):
        Path(paths[key]).write_text("synthetic configuration")
    (project / ".env").write_text("synthetic provider credential")
    class FakeInstallation(manager.Installation):
        def __init__(self):
            super().__init__(project)
            self.backups = tmp_path / "private-backups"
            self.events = []
            self.state_values = {"active": {unit: True for unit in manager.UNITS},
                                 "enabled": {unit: False for unit in manager.UNITS}}
            self.state_values["enabled"][manager.UNITS[0]] = True
        def require_owned(self, *, managed=True):
            assert self.current.is_symlink()
        def runtime_paths(self):
            return paths.copy()
        def systemctl(self, *args, check=True):
            self.events.append(args)
            for unit in args[1:]:
                if unit in manager.UNITS:
                    if args[0] in {"start", "stop"}:
                        self.state_values["active"][unit] = args[0] == "start"
                    if args[0] in {"enable", "disable"}:
                        self.state_values["enabled"][unit] = args[0] == "enable"
            if args[0] in {"is-active", "is-enabled"}:
                field = "active" if args[0] == "is-active" else "enabled"
                return SimpleNamespace(returncode=0 if self.state_values[field][args[-1]] else 1, stdout="")
            return SimpleNamespace(returncode=0, stdout="")
        def run(self, args, **kwargs):
            if "--stage-dir" in args:
                from install_desktop import render
                staged = Path(args[args.index("--stage-dir") + 1])
                overrides = json.loads(Path(args[args.index("--runtime-paths") + 1]).read_text())
                for name, content in render(project, args[0], overlay=candidate / "frontend/blob_overlay", runtime_paths=overrides).items():
                    target = staged / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content)
            return SimpleNamespace(returncode=1 if "--status" in args else 0, stdout="")
    instance = FakeInstallation()
    for name, target in instance.targets.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("previous startup file\nHidden=true\nX-GNOME-Autostart-enabled=false\n")
    monkeypatch.setattr(manager, "wait_ready", lambda *args: None)
    return instance, candidate, previous, memory


def test_successful_update_preserves_data_startup_choices_and_retains_checked_backup(installation, modules):
    state, _ = modules
    instance, candidate, _, memory = installation
    original_state = json.loads(json.dumps(instance.state_values))
    backup = instance.upgrade(candidate)
    assert instance.current.resolve() == candidate
    assert (memory / "user-fact").read_text() == "original user fact"
    assert not instance.marker.exists() and not instance.journal.exists()
    assert instance.state_values == original_state
    assert "Hidden=true" in instance.targets["autostart/blob.desktop"].read_text()
    assert "X-GNOME-Autostart-enabled=false" in instance.targets["autostart/blob.desktop"].read_text()
    assert state.verify(backup, instance.project)["metadata"]["runtime"].endswith("previous")
    assert (instance.project / ".env").read_text() == "synthetic provider credential"


def test_orphan_maintenance_marker_requires_recovery_without_losing_activity(installation, modules):
    state, _ = modules
    instance, candidate, _, _ = installation
    activity = instance.activity()
    instance.quiesce(instance.runtime_paths(), activity)
    for action in (instance.backup, lambda: instance.upgrade(candidate), instance.uninstall):
        with pytest.raises(ValueError, match="[Rr]ecover"):
            action()
    instance.recover()
    assert instance.activity() == activity and not instance.marker.exists()


def test_failed_candidate_probe_restores_runtime_data_and_units(installation, modules, monkeypatch):
    _, manager = modules
    instance, candidate, previous, memory = installation
    old_units = {name: path.read_bytes() for name, path in instance.targets.items()}
    def fail_probe(*args):
        assert instance.marker.exists()
        (memory / "user-fact").write_text("simulated candidate migration")
        raise RuntimeError("candidate failed")
    monkeypatch.setattr(manager, "wait_ready", fail_probe)
    with pytest.raises(RuntimeError, match="candidate failed"):
        instance.upgrade(candidate)
    assert instance.current.resolve() == previous
    assert (memory / "user-fact").read_text() == "original user fact"
    assert all(path.read_bytes() == old_units[name] for name, path in instance.targets.items())
    assert not instance.marker.exists() and not instance.journal.exists()


def test_backup_disk_full_never_switches_runtime(installation, modules, monkeypatch):
    state, _ = modules
    instance, candidate, previous, memory = installation
    monkeypatch.setattr(state, "safe_copy", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        instance.upgrade(candidate)
    assert instance.current.resolve() == previous
    assert (memory / "user-fact").read_text() == "original user fact"
    assert not instance.marker.exists() and not instance.journal.exists()


def test_explicit_rollback_keeps_newer_data_in_a_safety_backup(installation, modules):
    state, _ = modules
    instance, candidate, previous, memory = installation
    backup = instance.upgrade(candidate)
    (memory / "user-fact").write_text("newer user fact")
    with pytest.raises(ValueError, match="--restore-data"):
        instance.rollback(backup)
    safety = instance.rollback(backup, restore_data=True)
    assert instance.current.resolve() == previous
    assert (memory / "user-fact").read_text() == "original user fact"
    manifest = state.verify(safety, instance.project)
    folder = manifest["entries"]["memory_db_path"]["folder"]
    assert (safety / "payload" / folder / "value/user-fact").read_text() == "newer user fact"


def test_interrupted_switch_recovery_restores_the_recorded_snapshot(installation, modules):
    state, _ = modules
    instance, candidate, previous, memory = installation
    activity = instance.activity()
    instance.quiesce(instance.runtime_paths(), activity)
    backup = instance.make_backup(instance.runtime_paths(), activity)
    state.atomic_json(instance.journal, {"phase": "switching", "backup": str(backup)})
    instance.set_current(candidate)
    (memory / "user-fact").write_text("interrupted migration")
    instance.recover()
    assert instance.current.resolve() == previous
    assert (memory / "user-fact").read_text() == "original user fact"
    assert not instance.marker.exists()


def test_uninstall_removes_startup_and_keeps_personal_data_and_credentials(installation):
    instance, _, _, memory = installation
    instance.uninstall()
    assert not instance.current.exists()
    assert all(not target.exists() for target in instance.targets.values())
    assert (memory / "user-fact").read_text() == "original user fact"
    assert (instance.project / ".env").exists()


def test_managed_path_pins_respect_explicit_configuration_and_reject_secrets(modules, tmp_path, monkeypatch):
    from blob.config import BlobConfig
    state, _ = modules
    project = tmp_path / "pins-project"
    project.mkdir()
    pin = project / ".runtime/desktop/runtime-paths.json"
    state.atomic_json(pin, {"memory_db_path": str(project / "pinned-memory")})
    monkeypatch.delenv("BLOB_MEMORY_DB_PATH", raising=False)
    config = project / "config.yaml"
    assert BlobConfig.load(str(config)).memory_db_path == str(project / "pinned-memory")
    config.write_text("memory_db_path: " + str(project / "explicit-memory"))
    assert BlobConfig.load(str(config)).memory_db_path == str(project / "explicit-memory")
    state.atomic_json(pin, {"nebius_api_key": "not-a-path"})
    with pytest.raises(ValueError, match="runtime path"):
        BlobConfig.load(str(config))
