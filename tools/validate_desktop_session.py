"""Exercise startup/restart only inside the disposable Ubuntu validation image."""

import json
import argparse
import os
from pathlib import Path
import subprocess
import time


def command(*args, capture=False):
    return subprocess.run([str(arg) for arg in args], check=True, text=True,
                          capture_output=capture, timeout=60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--after-container-restart", action="store_true")
    args = parser.parse_args()
    if (os.environ.get("BLOB_DISPOSABLE_VALIDATION") != "1" or
            Path.home() != Path("/home/blobtest") or not Path("/run/systemd/container").is_file()):
        raise RuntimeError("Run only as blobtest in the disposable systemd validation container.")
    project = Path(__file__).resolve().parents[1]
    manifests = list((project / ".runtime/desktop/releases").glob("*/installation.json"))
    if len(manifests) != 1:
        raise RuntimeError("Expected one verified candidate")
    candidate = manifests[0].parent
    python = candidate / "venv/bin/python"
    from setup import activate
    from install_desktop import wait_ready
    def chat(text):
        return command(python, "-m", "blob.client", "--send", text, capture=True).stdout
    if args.after_container_restart:
        command(python, "-m", "blob.desktop", "--startup")
        wait_ready(project, python)
        state = json.loads(chat("/privacy status"))
        assert state["paused"] and not state["cloud_enabled"]
        assert "synthetic desktop restart" in chat("/reminders")
        report = json.loads((candidate / "desktop-session.json").read_text())
        assert report["fresh_activation"]
        report["container_restart_and_startup"] = True
        (candidate / "desktop-session.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
        return
    activate(candidate)
    state = json.loads(chat("/privacy status"))
    assert not state["cloud_enabled"] and not state["awareness_enabled"]
    assert "synthetic desktop restart" in chat("/reminders add 20 synthetic desktop restart")
    assert "paused" in chat("/privacy pause")
    before = command("systemctl", "--user", "show", "blob-backend.service", "-p", "MainPID", "--value", capture=True).stdout.strip()
    command("systemctl", "--user", "kill", "--signal=SIGKILL", "blob-backend.service")
    time.sleep(4)
    wait_ready(project, python)
    after = command("systemctl", "--user", "show", "blob-backend.service", "-p", "MainPID", "--value", capture=True).stdout.strip()
    assert before != after and after != "0"
    assert json.loads(chat("/privacy status"))["paused"]
    assert "synthetic desktop restart" in chat("/reminders")
    command("systemctl", "--user", "stop", "blob-overlay.service", "blob-backend.service")
    # Invoke the exact XDG-autostart entry point with the virtual desktop's environment.
    command(python, "-m", "blob.desktop", "--startup")
    wait_ready(project, python)
    assert "synthetic desktop restart" in chat("/reminders")
    report = {"fresh_activation": True, "authenticated_chat": True, "cloud_off": True,
              "crash_restart": True, "privacy_persisted": True, "reminder_persisted": True,
              "autostart_entry_point": True, "real_gnome_login": False, "native_wayland": False}
    (candidate / "desktop-session.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
