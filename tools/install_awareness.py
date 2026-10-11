"""Install Blob's local GNOME active-window bridge without restarting the desktop."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

UUID = "blob-awareness@projectblob"


def install(*, stage_dir=None):
    source = Path(__file__).resolve().parents[1] / "desktop/gnome" / UUID
    root = Path(stage_dir) if stage_dir else Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    target = root / "gnome-shell/extensions" / UUID
    target.mkdir(parents=True, exist_ok=True)
    for name in ("metadata.json", "extension.js"):
        shutil.copyfile(source / name, target / name)
    if stage_dir:
        print(f"Staged local screen bridge: {target}")
        return
    # Preserve all other extension settings. Newly installed extensions may not
    # be known to the running Shell until the next desktop login.
    import ast
    result = subprocess.run(["gsettings", "get", "org.gnome.shell", "enabled-extensions"],
                            capture_output=True, text=True, check=True)
    value = result.stdout.strip().removeprefix("@as ")
    enabled = ast.literal_eval(value)
    if UUID not in enabled:
        subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions",
                        json.dumps([*enabled, UUID])], check=True)
    result = subprocess.run(["gnome-extensions", "enable", UUID], capture_output=True, text=True)
    print(f"Installed local screen bridge: {target}")
    if result.returncode:
        print("GNOME has not loaded the new extension yet. Log out and back in once; it is enabled for the next login.")
    else:
        print("Bridge enabled. Use /awareness on, then /awareness status in Blob Chat.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-dir", type=Path, help="Copy files for review without changing desktop settings")
    args = parser.parse_args()
    install(stage_dir=args.stage_dir)


if __name__ == "__main__":
    main()
