"""Install per-user desktop startup. --stage-dir renders files for review/testing."""

import argparse
import os
from pathlib import Path
import subprocess
import sys


def unit_quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def desktop_quote(value):
    return '"' + str(value).replace("\\", "\\\\\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%") + '"'


def render(project, interpreter):
    project, interpreter = Path(project).resolve(), Path(interpreter).absolute()
    if any(char in str(project) + str(interpreter) for char in "\n\r"):
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
ExecStart={unit_quote(project / 'frontend_cpp/build/blob_overlay').replace('$', '$$')}
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


def install(project, interpreter, *, stage_dir=None):
    files = render(project, interpreter)
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    data_root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    for relative, content in files.items():
        if stage_dir:
            target = Path(stage_dir) / relative
        elif relative.startswith("applications/"):
            target = data_root / relative
        else:
            target = config_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        target.chmod(0o600)
        print(target)
    if not stage_dir:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        # XDG autostart handles environments whose desktop doesn't activate graphical-session.target.
        subprocess.run(["systemctl", "--user", "enable", "blob-backend.service", "blob-overlay.service"], check=True)
        from blob.desktop import start_session
        start_session()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-dir", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    if not (project / "frontend_cpp/build/blob_overlay").is_file():
        parser.error("Build the frontend with make frontend first.")
    install(project, sys.executable, stage_dir=args.stage_dir)


if __name__ == "__main__":
    main()
