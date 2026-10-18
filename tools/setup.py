"""Prepare and verify Blob, then install desktop startup on a fresh Linux PC."""

import argparse
import getpass
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from install_desktop import desktop_targets, require_fresh_desktop


PROJECT = Path(__file__).resolve().parents[1]
APT_PACKAGES = ["build-essential", "cmake", "pkg-config", "libsdl2-dev", "libgrpc++-dev",
                "protobuf-compiler", "protobuf-compiler-grpc", "libprotobuf-dev", "libx11-dev",
                "python3-venv", "xterm", "git", "bubblewrap", "libgl1"]
TERMINALS = ("xdg-terminal-exec", "ptyxis", "kgx", "gnome-terminal", "konsole", "xfce4-terminal", "xterm")


class SetupError(RuntimeError):
    pass


def run(command, *, cwd=PROJECT, env=None):
    command = [str(part) for part in command]
    print("+ " + shlex.join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def candidate_environment():
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PIP_TARGET", "PIP_PREFIX"):
        env.pop(key, None)
    env.update(PYTHONNOUSERSITE="1", PIP_USER="0", PIP_REQUIRE_VIRTUALENV="true",
               PIP_DISABLE_PIP_VERSION_CHECK="1")
    return env


def preflight(args):
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise SetupError("The first installer targets Linux x86-64. Other platforms still need manual setup.")
    if sys.version_info < (3, 11):
        raise SetupError("Use Python 3.11 or newer (for example python3.12 tools/setup.py).")
    if sys.implementation.name != "cpython":
        raise SetupError("Use CPython for this installer; other Python implementations have not been validated.")
    if os.geteuid() == 0:
        raise SetupError("Run setup as your desktop user, without sudo. Only OS packages need sudo.")
    if not args.prepare_only and not args.check:
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise SetupError("Run setup in your desktop session, or use --prepare-only.")
        # Check before apt, downloads or builds: never replace an existing installation.
        if os.path.lexists(PROJECT / "venv") or os.path.lexists(PROJECT / ".runtime/desktop/current"):
            raise SetupError("An installation already exists. It was left unchanged. Use --prepare-only to verify a separate build.")
        require_fresh_desktop(desktop_targets())
    if args.install_system_deps and not args.check:
        distro = platform.freedesktop_os_release()
        family = {distro.get("ID", ""), *distro.get("ID_LIKE", "").split()}
        if not family.intersection({"ubuntu", "debian"}):
            raise SetupError("Automatic OS packages support Ubuntu/Debian only. Install native dependencies manually, then rerun without --install-system-deps.")
        run(["sudo", "apt-get", "update"])
        run(["sudo", "apt-get", "install", "-y", *APT_PACKAGES])
    missing = [name for name in ("cmake", "c++", "protoc", "grpc_cpp_plugin") if not shutil.which(name)]
    if missing:
        raise SetupError("Missing native tools: " + ", ".join(missing) +
                         ". On Ubuntu/Debian, rerun with --install-system-deps.")
    run([sys.executable, "-c", "import venv, ensurepip"])
    if not args.prepare_only and not args.check:
        if not any(shutil.which(name) for name in TERMINALS):
            raise SetupError("Install a terminal (for example xterm), or rerun with --install-system-deps on Ubuntu/Debian.")
    # A temporary configure catches missing headers, libraries and incompatible SDL.
    with tempfile.TemporaryDirectory(prefix="blob-setup-check-") as directory:
        run(["cmake", "-S", PROJECT / "frontend_cpp", "-B", directory, "-DCMAKE_BUILD_TYPE=Release"])
    if sys.version_info[:2] != (3, 14):
        print("Python 3.14 has the pinned dependency baseline. This Python version will resolve dependencies and must pass the same local checks.", flush=True)


def prepare(args):
    releases = PROJECT / ".runtime/desktop/releases"
    releases.mkdir(parents=True, exist_ok=True)
    candidate = Path(tempfile.mkdtemp(prefix="install-", dir=releases))
    python = candidate / "venv/bin/python"
    build = candidate / "frontend"
    env = candidate_environment()
    # Leave failed candidates available for diagnosis; no active runtime is changed.
    print(f"Building separately in {candidate}", flush=True)
    run([sys.executable, "-m", "venv", candidate / "venv"], env=env)
    pip = [python, "-m", "pip"]
    locked = sys.version_info[:2] == (3, 14)
    if locked:
        run([*pip, "install", "-r", PROJECT / "requirements/linux-py314.lock"], env=env)
    else:
        run([*pip, "install", "--upgrade", "pip", "setuptools>=77.0.3"], env=env)
    extras = "web,vision,ocr" if args.ocr else "web,vision"
    install = [*pip, "install", "--no-build-isolation"]
    if locked:
        install.extend(["-c", PROJECT / "requirements/linux-py314.lock"])
    run([*install, f"{PROJECT / 'backend_python'}[{extras}]"], env=env)
    run([*pip, "check"], env=env)
    if locked:
        run([python, PROJECT / "tools/lock_dependencies.py", "--check"], env=env)
    run([python, PROJECT / "tools/release_smoke.py", "--source-root", PROJECT], cwd=candidate, env=env)
    browser = [python, "-m", "playwright", "install"]
    if args.install_system_deps:
        browser.append("--with-deps")
    run([*browser, "chromium"], cwd=candidate, env=env)
    # Launch Chromium with an in-memory document; no website or personal browser profile.
    run([python, "-c", "from playwright.sync_api import sync_playwright\n"
         "with sync_playwright() as p:\n"
         "    browser = p.chromium.launch()\n"
         "    page = browser.new_page()\n"
         "    page.set_content('<title>Blob setup check</title>')\n"
         "    assert page.title() == 'Blob setup check'\n"
         "    browser.close()"], cwd=candidate, env=env)
    run(["cmake", "-S", PROJECT / "frontend_cpp", "-B", build, "-DCMAKE_BUILD_TYPE=Release"], env=env)
    run(["cmake", "--build", build, "--parallel", args.jobs], env=env)
    run(["ctest", "--test-dir", build, "--output-on-failure"], env=env)
    # Render startup files without installing them as part of preparation.
    run([python, PROJECT / "tools/install_desktop.py", "--overlay", build / "blob_overlay",
         "--stage-dir", candidate / "desktop-preview"], env=env)
    (candidate / "installation.json").write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "extras": extras, "pinned_baseline": locked,
        "project": str(PROJECT), "verified": True,
    }, indent=2) + "\n")
    return candidate


def activate(candidate):
    current = PROJECT / ".runtime/desktop/current"
    # An exclusive symlink also prevents two setup runs from claiming the same install.
    current.symlink_to(candidate, target_is_directory=True)
    try:
        run([candidate / "venv/bin/python", PROJECT / "tools/install_desktop.py", "--fresh",
             "--overlay", candidate / "frontend/blob_overlay"], env=candidate_environment())
    except BaseException:
        current.unlink()
        raise


def configure_key():
    target = PROJECT / ".env"
    if os.path.lexists(target):
        return
    key = os.environ.get("NEBIUS_API_KEY", "").strip()
    if not key:
        if not sys.stdin.isatty():
            return
        key = getpass.getpass("Optional Nebius API key (Enter to skip; saved locally): ").strip()
    if not key:
        return
    if any(char in key for char in "\n\r\0"):
        raise SetupError("API keys must be a single line.")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write("NEBIUS_API_KEY=" + json.dumps(key) + "\n")
    print("API key saved privately in .env. Your privacy settings are unchanged.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check prerequisites without installing or downloading")
    parser.add_argument("--install-system-deps", action="store_true", help="Install Ubuntu/Debian OS and Chromium libraries using sudo")
    parser.add_argument("--prepare-only", action="store_true", help="Build and verify separately; leave running services and startup files unchanged")
    parser.add_argument("--ocr", action="store_true", help="Also install optional EasyOCR and its larger dependencies")
    parser.add_argument("--jobs", type=int, default=2, help="Parallel C++ build jobs (default: 2)")
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    try:
        preflight(args)
        if args.check:
            print("Native prerequisites passed. Setup will install Python packages and Chromium in the next step.")
            return 0
        candidate = prepare(args)
        if args.prepare_only:
            print(f"Verified build: {candidate}\nDesktop startup and the running Blob were left unchanged.")
        else:
            configure_key()
            activate(candidate)
            print("Blob is installed and running. Double-click the slime to chat.\n"
                  "Cloud assistance starts off on fresh profiles. Add NEBIUS_API_KEY to .env when ready,\n"
                  "then read /privacy explain and use /privacy cloud on in Blob Chat.")
        return 0
    except (SetupError, RuntimeError, OSError, subprocess.CalledProcessError, KeyboardInterrupt) as exc:
        print(f"Setup stopped: {exc}\nNo existing installation was replaced. Fix the reported issue and rerun setup.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
