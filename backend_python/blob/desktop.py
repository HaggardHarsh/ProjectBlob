"""Desktop session startup and a terminal launcher for reconnectable chat."""

import argparse
import os
import shutil
import subprocess
import sys


def open_chat(*, conversation=False):
    chat = [sys.executable, "-m", "blob.client"]
    if conversation:
        chat.append("--conversation")
    for terminal, flags in (("xdg-terminal-exec", []), ("ptyxis", ["--"]), ("kgx", ["--"]), ("gnome-terminal", ["--"]),
                            ("konsole", ["-e"]), ("xfce4-terminal", ["-x"]), ("xterm", ["-e"])):
        executable = shutil.which(terminal)
        if executable:
            # The overlay tracks this helper until terminal startup finishes.
            # Some terminals remain attached for the whole chat session.
            subprocess.run([executable, *flags, *chat], start_new_session=True, check=True)
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
    parser.add_argument("--conversation", action="store_true", help="Reply to Blob's current invitation")
    args = parser.parse_args()
    try:
        start_session() if args.startup else open_chat(conversation=args.conversation)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
