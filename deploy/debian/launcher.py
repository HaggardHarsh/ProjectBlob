"""Per-user entry points for the prebuilt Ubuntu package (never run as root)."""

import argparse
import getpass
import os
from pathlib import Path
import subprocess
import sys

PREFIX = Path("/opt/projectblob")
PYTHON = PREFIX / "venv/bin/python"
SERVICES = ("blob-backend.service", "blob-overlay.service")
AUTOSTART = """[Desktop Entry]
Type=Application
Name=Project Blob
Exec=/usr/bin/blob-start
TryExec=/usr/bin/blob-start
Icon=projectblob
Terminal=false
X-GNOME-Autostart-enabled=true
X-ProjectBlob-Package=true
"""


def config_home():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def check_source_install():
    # A user unit takes precedence over the packaged system-wide user unit.
    # Refuse before changing credentials or startup files.
    conflicts = [config_home() / "systemd/user" / name for name in SERVICES]
    conflicts += [Path.home() / ".local/share/systemd/user" / name for name in SERVICES]
    conflicts = [str(path) for path in conflicts if os.path.lexists(path)]
    startup = config_home() / "autostart/blob.desktop"
    if startup.exists() and "X-ProjectBlob-Package=true" not in startup.read_text():
        conflicts.append(str(startup))
    if conflicts:
        raise RuntimeError("An existing source installation owns Blob startup files. "
                           "Uninstall its desktop integration first (keep your data); see "
                           "/usr/share/doc/projectblob/README.md. Conflicts: " + ", ".join(conflicts))


def environment():
    if os.geteuid() == 0:
        raise RuntimeError("Run Blob as your desktop user, without sudo.")
    os.umask(0o077)
    state = Path.home() / ".blob"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    from dotenv import load_dotenv
    load_dotenv(state / ".env", override=False)
    os.chdir(state)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PREFIX / "browsers")
    os.environ["BLOB_CHAT_PYTHON"] = "/usr/lib/projectblob/python"
    os.environ["PATH"] = str(PREFIX / "bin") + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin")
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    os.environ.pop("PYTHONPATH", None)
    os.environ.pop("PYTHONHOME", None)
    # Chroma's default embedding function uses this fixed cache location.
    # A read-only packaged model avoids a surprise first-chat download.
    model = Path.home() / ".cache/chroma/onnx_models/all-MiniLM-L6-v2"
    if not os.path.lexists(model):
        model.parent.mkdir(parents=True, exist_ok=True)
        try:
            model.symlink_to(PREFIX / "models/all-MiniLM-L6-v2", target_is_directory=True)
        except FileExistsError:
            pass  # The backend and overlay may start concurrently.
    return state


def systemctl(*args):
    subprocess.run(["systemctl", "--user", *args], check=True)


def start():
    check_source_install()
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise RuntimeError("Run this command in a terminal in your desktop session.")
    systemctl("daemon-reload")
    variables = [key for key in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
                 "DBUS_SESSION_BUS_ADDRESS", "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE")
                 if key in os.environ]
    systemctl("import-environment", *variables)
    # Do not import the API key into the user manager. Each process reads ~/.blob/.env.
    systemctl("start", *SERVICES)


def setup(state, argv):
    parser = argparse.ArgumentParser(description="Configure Blob for your desktop account.")
    parser.add_argument("--no-key", action="store_true", help="Keep credentials unchanged")
    parser.add_argument("--no-start", action="store_true", help="Configure without starting desktop services")
    args = parser.parse_args(argv)
    check_source_install()
    if not args.no_key:
        key = getpass.getpass("Nebius API key (Enter to keep existing settings / use local commands): ").strip()
        if key:
            if any(char in key for char in "\r\n\0"):
                raise RuntimeError("The key must be a single line.")
            from dotenv import set_key
            secret = state / ".env"
            if secret.is_symlink():
                raise RuntimeError("Refusing to replace a symlink at ~/.blob/.env.")
            secret.touch(mode=0o600, exist_ok=True)
            secret.chmod(0o600)
            set_key(secret, "NEBIUS_API_KEY", key)
            print("Key saved privately in ~/.blob/.env.")
    startup = config_home() / "autostart/blob.desktop"
    startup.parent.mkdir(parents=True, exist_ok=True)
    startup.write_text(AUTOSTART)
    print("Blob will start when you log in. Fresh profiles keep cloud assistance off.\n"
          "In Blob Chat, read /privacy explain, then use /privacy cloud on if desired.")
    if not args.no_start:
        # A newly entered key needs a fresh backend process, including on reruns.
        systemctl("stop", *SERVICES)
        start()
        print("Blob is running. Double-click the companion, or run blob-chat.")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        raise RuntimeError("Missing launcher mode.")
    mode, *args = argv
    state = environment()
    if mode == "setup":
        setup(state, args)
    elif mode == "start":
        start()
    elif mode == "chat":
        start()
        os.execv(str(PYTHON), [str(PYTHON), "-I", "-m", "blob.client", *args])
    elif mode == "backend":
        os.execv(str(PYTHON), [str(PYTHON), "-I", "-m", "blob.main", "--daemon", *args])
    elif mode == "overlay":
        from blob.config import BlobConfig
        config = BlobConfig.load()
        os.environ["BLOB_IPC_ADDRESS"] = config.ipc_address
        os.environ["BLOB_IPC_TOKEN_PATH"] = config.ipc_token_path
        os.execv(str(PREFIX / "blob_overlay"), [str(PREFIX / "blob_overlay"), *args])
    elif mode == "python":
        os.execv(str(PYTHON), [str(PYTHON), "-I", *args])
    else:
        raise RuntimeError("Unknown launcher mode: " + mode)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print("Blob: " + str(exc), file=sys.stderr)
        sys.exit(1)
