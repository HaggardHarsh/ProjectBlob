"""Install per-user desktop startup. --stage-dir renders files for review/testing."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time


def unit_quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def desktop_quote(value):
    return '"' + str(value).replace("\\", "\\\\\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%") + '"'


def render(project, interpreter, *, overlay=None):
    project, interpreter = Path(project).resolve(), Path(interpreter).absolute()
    overlay = Path(overlay).absolute() if overlay else project / "frontend_cpp/build/blob_overlay"
    if any(char in str(project) + str(interpreter) + str(overlay) for char in "\n\r"):
        raise ValueError("Installation paths cannot contain newlines.")
    desktop_path = str(project).replace("\\", "\\\\")
    from blob.config import BlobConfig
    config = BlobConfig.load(str(project / "config.yaml"))
    base = f"""[Unit]
Description=Project Blob backend
PartOf=graphical-session.target
After=graphical-session-pre.target
StartLimitIntervalSec=60
StartLimitBurst=10

[Service]
Type=simple
WorkingDirectory={str(project).replace('%', '%%')}
ExecStart={unit_quote(interpreter).replace('$', '$$')} -m blob.main --daemon
Restart=on-failure
RestartSec=3
TimeoutStopSec=15
UMask=0077
NoNewPrivileges=yes
StandardInput=null
# Replies are delivered through authenticated IPC; don't archive chat in the journal.
StandardOutput=null
StandardError=journal

[Install]
WantedBy=graphical-session.target
"""
    overlay = f"""[Unit]
Description=Project Blob desktop overlay
PartOf=graphical-session.target
After=graphical-session-pre.target blob-backend.service
Wants=blob-backend.service
StartLimitIntervalSec=60
StartLimitBurst=10

[Service]
Type=simple
WorkingDirectory={str(project).replace('%', '%%')}
ExecStart={unit_quote(overlay).replace('$', '$$')}
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=yes
Environment={unit_quote('BLOB_CHAT_PYTHON=' + str(interpreter))}
Environment={unit_quote('BLOB_IPC_ADDRESS=' + config.ipc_address)}
Environment={unit_quote('BLOB_IPC_TOKEN_PATH=' + config.ipc_token_path)}

[Install]
WantedBy=graphical-session.target
"""
    startup = f"""[Desktop Entry]
Type=Application
Name=Project Blob
Comment=Start your desktop companion and local backend
Exec={desktop_quote(interpreter)} -m blob.desktop --startup
Path={desktop_path}
Terminal=false
X-GNOME-Autostart-enabled=true
"""
    chat = f"""[Desktop Entry]
Type=Application
Name=Blob Chat
Comment=Reconnect to your running companion
Exec={desktop_quote(interpreter)} -m blob.client
Path={desktop_path}
Terminal=true
Categories=Utility;
"""
    return {"systemd/user/blob-backend.service": base, "systemd/user/blob-overlay.service": overlay,
            "autostart/blob.desktop": startup, "applications/blob-chat.desktop": chat}


def desktop_targets():
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    data_root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    names = ("systemd/user/blob-backend.service", "systemd/user/blob-overlay.service",
             "autostart/blob.desktop", "applications/blob-chat.desktop")
    return {name: (data_root if name.startswith("applications/") else config_root) / name for name in names}


def require_fresh_desktop(targets):
    for target in targets.values():
        if os.path.lexists(target):
            raise RuntimeError(f"Existing desktop installation left unchanged: {target}. Use --prepare-only to verify a separate build.")
    # Also detect units installed in other systemd search locations.
    for name in ("blob-backend.service", "blob-overlay.service"):
        result = subprocess.run(["systemctl", "--user", "show", name, "--property=LoadState", "--value"],
                                check=True, capture_output=True, text=True)
        if result.stdout.strip() != "not-found":
            raise RuntimeError(f"Existing service left unchanged: {name}. Use --prepare-only to verify a separate build.")


def wait_ready(project, interpreter):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        active = subprocess.run(["systemctl", "--user", "is-active",
                                 "blob-backend.service", "blob-overlay.service"],
                                check=False, capture_output=True, text=True)
        if active.returncode == 0 and active.stdout.split() == ["active", "active"]:
            try:
                ready = subprocess.run([str(interpreter), "-m", "blob.client", "--status"], cwd=project,
                                       capture_output=True, timeout=8, check=False)
                if ready.returncode == 0:
                    return
            except subprocess.TimeoutExpired:
                pass
        time.sleep(1)
    raise RuntimeError("Blob startup did not become ready. Check journalctl --user -u blob-backend -u blob-overlay. Fresh startup files will be removed.")


def install(project, interpreter, *, stage_dir=None, overlay=None, fresh=False):
    files = render(project, interpreter, overlay=overlay)
    targets = {name: Path(stage_dir) / name for name in files} if stage_dir else desktop_targets()
    if fresh and not stage_dir:
        require_fresh_desktop(targets)
    written = {}
    try:
        for relative, content in files.items():
            target = targets[relative]
            target.parent.mkdir(parents=True, exist_ok=True)
            if fresh:
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                written[target] = os.fstat(descriptor).st_ino
                with os.fdopen(descriptor, "w") as output:
                    output.write(content)
            else:
                target.write_text(content)
                target.chmod(0o600)
            print(target)
        if not stage_dir:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            # XDG autostart also covers desktops without graphical-session.target.
            subprocess.run(["systemctl", "--user", "enable", "blob-backend.service", "blob-overlay.service"], check=True)
            from blob.desktop import start_session
            start_session()
            if fresh:
                wait_ready(project, interpreter)
    except BaseException:
        if fresh:
            if not stage_dir and written:
                units = [target.name for target in written if target.suffix == ".service"]
                if units:
                    for action in ("stop", "disable"):
                        subprocess.run(["systemctl", "--user", action, *units], check=False)
            for target, inode in written.items():
                if target.exists() and target.lstat().st_ino == inode:
                    target.unlink()
            if not stage_dir and written:
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-dir", type=Path)
    parser.add_argument("--overlay", type=Path, help="Use an independently built overlay")
    parser.add_argument("--fresh", action="store_true", help="Refuse existing startup files; roll back fresh startup on failure")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    overlay = args.overlay or project / "frontend_cpp/build/blob_overlay"
    if not overlay.is_file():
        parser.error("Build the frontend with make frontend first.")
    install(project, sys.executable, stage_dir=args.stage_dir, overlay=overlay, fresh=args.fresh)


if __name__ == "__main__":
    main()
