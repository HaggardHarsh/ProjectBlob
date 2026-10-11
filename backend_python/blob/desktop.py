"""Desktop session startup and a terminal launcher for reconnectable chat."""

import argparse
import os
import shutil
import subprocess
import sys


def open_chat():
    chat = [sys.executable, "-m", "blob.client"]
    for terminal, flags in (("xdg-terminal-exec", []), ("ptyxis", ["--"]), ("kgx", ["--"]), ("gnome-terminal", ["--"]),
                            ("konsole", ["-e"]), ("xfce4-terminal", ["-x"]), ("xterm", ["-e"])):
        executable = shutil.which(terminal)
        if executable:
            subprocess.Popen([executable, *flags, *chat], start_new_session=True)
            return
    raise RuntimeError("No terminal launcher found. Open a terminal and run blob-chat (or python -m blob.client).")


def start_session():
    variables = [key for key in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
                                "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE") if key in os.environ]
    if variables:
        subprocess.run(["systemctl", "--user", "import-environment", *variables], check=True)
    subprocess.run(["systemctl", "--user", "restart", "blob-backend.service", "blob-overlay.service"], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--startup", action="store_true")
    args = parser.parse_args()
    try:
        start_session() if args.startup else open_chat()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
