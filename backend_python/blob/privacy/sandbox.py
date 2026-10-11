"""Read-only command namespace: approved folders, no host network or credentials."""

import os
from pathlib import Path
import shutil
import time
from blob.privacy.controls import PrivacyBlocked


def sandbox_command(argv, controls):
    controls.check()
    generation = controls.generation
    deadline = time.monotonic() + 3
    executable = shutil.which("bwrap")
    if not executable:
        raise PrivacyBlocked("Command isolation is unavailable. Install Bubblewrap; command skills remain blocked.")
    if not controls.folders:
        raise PrivacyBlocked("No folders approved. Use /privacy allow /path/to/project before running command skills.")
    if argv[0] == "curl":
        raise PrivacyBlocked("Network commands are disabled in command skills. Use the built-in weather skill.")
    roots = [root for root in controls.folders if root.is_dir() and root.resolve() == root]
    if not roots:
        raise PrivacyBlocked("Approved folders are unavailable or changed. Review /privacy folders.")
    controls.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    empty = controls.path.parent / "sandbox-empty"
    fd = os.open(empty, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    os.close(fd)
    command = [executable, "--die-with-parent", "--new-session", "--unshare-all", "--clearenv",
               "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/nonexistent",
               "--setenv", "GIT_CONFIG_NOSYSTEM", "1", "--cap-drop", "ALL",
               "--ro-bind", "/usr", "/usr", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for name in ("bin", "sbin", "lib", "lib64"):
        path = Path("/") / name
        if path.is_symlink():
            command += ["--symlink", os.readlink(path), str(path)]
        elif path.exists():
            command += ["--ro-bind", str(path), str(path)]
    for root in roots:
        command += ["--ro-bind", str(root), str(root)]
    # Do not inherit Git credentials, repository helpers, or environment secrets.
    # Mask common credentials at every depth of approved roots (without following symlinks).
    for root in roots:
        for directory, dirs, files in os.walk(root, followlinks=False):
            controls.check()
            if controls.generation != generation:
                raise PrivacyBlocked("Privacy settings changed while preparing the command.")
            if time.monotonic() > deadline:
                raise PrivacyBlocked("This folder is too large to prepare safely. Approve a narrower folder.")
            for name in list(dirs):
                if name in {".ssh", ".aws", ".gnupg", ".blob", ".codex"}:
                    command += ["--tmpfs", str(Path(directory) / name)]
                    dirs.remove(name)
                elif name in {"node_modules", "venv", ".venv", "__pycache__"}:
                    dirs.remove(name)
            for name in files:
                if name == ".env" or name.startswith(".env.") or name in {".git-credentials", ".netrc"} or (name == "config" and Path(directory).name == ".git"):
                    target = Path(directory) / name
                    if not target.is_symlink():
                        command += ["--ro-bind", str(empty), str(target)]
    command += ["--chdir", str(roots[0]), "--", *argv]
    return command
