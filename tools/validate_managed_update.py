"""Destructive maintenance checks restricted to the disposable validation container."""

import argparse
import json
import os
from pathlib import Path

import manage_install as manager
from install_state import atomic_json, verify
from setup import activate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    if (os.environ.get("BLOB_DISPOSABLE_VALIDATION") != "1" or
            Path.home() != Path("/home/blobtest") or not Path("/run/systemd/container").is_file()):
        raise RuntimeError("Run only as blobtest in the disposable systemd validation container.")
    installation = manager.Installation()
    candidate = args.candidate.resolve(strict=True)
    previous = installation.current.resolve(strict=True)
    if candidate == previous:
        raise RuntimeError("Select a newly prepared candidate, not the running runtime")
    report = {}

    def chat(text):
        result = installation.run([installation.interpreter(), "-m", "blob.client", "--send", text])
        return result.stdout

    def ready():
        manager.wait_ready(installation.project, installation.interpreter())
        state = json.loads(chat("/privacy status"))
        assert state["paused"] and not state["cloud_enabled"]
        assert "synthetic managed update" in chat("/reminders")
        assert not installation.marker.exists() and not installation.journal.exists()

    assert "synthetic managed update" in chat("/reminders add 600 synthetic managed update")
    assert "paused" in chat("/privacy pause")
    activity = installation.activity()
    credentials = installation.project / ".env"
    original_credentials = credentials.read_bytes() if credentials.exists() else None
    backup = installation.upgrade(candidate)
    ready()
    assert installation.current.resolve() == candidate and installation.activity() == activity
    report["update_preserves_privacy_reminders_and_activity"] = True
    assert verify(backup, installation.project)["metadata"]["runtime"] == str(previous)

    assert "synthetic newer reminder" in chat("/reminders add 600 synthetic newer reminder")
    safety = installation.rollback(backup, restore_data=True)
    ready()
    assert installation.current.resolve() == previous
    assert "synthetic newer reminder" not in chat("/reminders")
    assert verify(safety, installation.project)["metadata"]["runtime"] == str(candidate)
    report["previous_runtime_rollback_and_newer_safety_backup"] = True
    installation.upgrade(candidate)
    ready()

    # Fail after real candidate startup while admission is still blocked.
    original_wait = manager.wait_ready
    paths = installation.runtime_paths()
    privacy = Path(paths["privacy_settings_path"])
    before = privacy.read_bytes()

    def fail_probe(*_):
        assert installation.marker.exists()
        privacy.write_text("simulated failed migration")
        raise RuntimeError("injected candidate probe failure")

    manager.wait_ready = fail_probe
    try:
        try:
            installation.upgrade(candidate)
        except RuntimeError as exc:
            assert str(exc) == "injected candidate probe failure"
        else:
            raise AssertionError("Expected failed probe")
    finally:
        manager.wait_ready = original_wait
    assert privacy.read_bytes() == before
    ready()
    report["failed_candidate_restores_checked_data_and_services"] = True

    # Leave the same durable state as a process interrupted after backup.
    with installation.locked():
        paths, activity = installation.runtime_paths(), installation.activity()
        installation.quiesce(paths, activity)
        interrupted = installation.make_backup(paths, activity)
        atomic_json(installation.journal, {"phase": "switching", "backup": str(interrupted)})
        privacy.write_text("simulated interrupted migration")
    installation.recover()
    assert privacy.read_bytes() == before
    ready()
    report["interrupted_transaction_recovery"] = True

    installation.uninstall()
    assert not installation.current.exists()
    assert all(not target.exists() for target in installation.targets.values())
    assert privacy.read_bytes() == before
    assert Path(paths["reminders_db_path"]).is_file()
    assert (credentials.read_bytes() if credentials.exists() else None) == original_credentials
    assert candidate.is_dir() and installation.backups.is_dir()
    activate(candidate)
    ready()
    report["uninstall_reinstall_retains_data_credentials_and_backups"] = True
    report["scope"] = "disposable Ubuntu systemd user session with Xvfb; synthetic stores only"
    (candidate / "managed-update-validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
