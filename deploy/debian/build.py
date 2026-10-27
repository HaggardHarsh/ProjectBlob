"""Container-only builder; tools/build_deb.py supplies a clean source snapshot."""

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

SOURCE = Path("/src")
PREFIX = Path("/opt/projectblob")
STAGE = Path("/build/package")
PYTHON = PREFIX / "venv/bin/python"
RUNTIME = [
    "python3.12", "ca-certificates", "systemd", "dbus-user-session", "apparmor", "xterm", "xfonts-base", "git",
    "libsdl2-2.0-0", "libgrpc++1.51t64", "libprotobuf32t64", "libgl1", "libcap2",
    "libasound2t64", "libatk-bridge2.0-0t64", "libatk1.0-0t64", "libatspi2.0-0t64",
    "libcairo2", "libcups2t64", "libdbus-1-3", "libdrm2", "libgbm1", "libglib2.0-0t64",
    "libnspr4", "libnss3", "libpango-1.0-0", "libx11-6", "libxcb1", "libxcomposite1",
    "libxdamage1", "libxext6", "libxfixes3", "libxkbcommon0", "libxrandr2",
    "fonts-liberation", "fonts-noto-color-emoji",
]


def run(*args, **kwargs):
    print("+", *map(str, args), flush=True)
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def write(relative, content, mode=0o644):
    path = STAGE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(mode)


def main():
    version = sys.argv[1]
    run("dpkg", "--validate-version", version)
    assert platform.freedesktop_os_release().get("VERSION_ID") == "24.04"
    assert platform.machine() == "x86_64"
    run("apt-get", "install", "-y", "--no-install-recommends", *RUNTIME,
        "python3-venv", "build-essential", "cmake", "pkg-config", "libsdl2-dev", "libgrpc++-dev",
        "protobuf-compiler", "protobuf-compiler-grpc", "libprotobuf-dev", "libx11-dev",
        "bubblewrap", "xvfb", "xauth", "desktop-file-utils")
    PREFIX.mkdir(parents=True)
    run("python3", "-m", "venv", PREFIX / "venv")
    os.environ.update(PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    cached_pip = Path("/home/blobtest/.cache/pip")
    if cached_pip.exists() and cached_pip.stat().st_uid == os.geteuid():
        os.environ["PIP_CACHE_DIR"] = str(cached_pip)
    lock = SOURCE / "requirements/linux-py312.lock"
    run(PYTHON, "-m", "pip", "install", "-r", lock)
    # pip builds local source in place; keep the read-only input mount untouched.
    shutil.copytree(SOURCE / "backend_python", "/build/backend_python")
    run(PYTHON, "-m", "pip", "install", "--no-build-isolation", "-c", lock,
        "/build/backend_python[web,vision]")
    run(PYTHON, "-m", "pip", "check")
    run(PYTHON, SOURCE / "deploy/debian/test_launcher.py")
    inventory = subprocess.check_output([str(PYTHON), "-m", "pip", "freeze"], text=True)
    # Avoid a meaningless container source URL in the distributed inventory.
    inventory = "\n".join("blob-backend==0.1.0" if line.startswith("blob-backend @") else line
                          for line in inventory.splitlines()) + "\n"
    (Path("/out") / "python-dependencies.txt").write_text(inventory)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PREFIX / "browsers")
    cache = Path("/home/blobtest/.cache/ms-playwright")
    if cache.exists():
        for path in cache.iterdir():
            if path.name.startswith(("chromium_headless_shell-", "ffmpeg-")):
                shutil.copytree(path, PREFIX / "browsers" / path.name)
    run(PYTHON, "-m", "playwright", "install", "--only-shell", "chromium")
    run(PYTHON, "-c", "from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2 as M\n"
        "from pathlib import Path\n"
        "M.DOWNLOAD_PATH = Path('/opt/projectblob/models/all-MiniLM-L6-v2')\n"
        "vectors = M()(['Blob installation check'])\nassert len(vectors[0]) == 384\n")
    for archive in (PREFIX / "models").rglob("*.tar.gz"):
        archive.unlink()  # Extracted model is enough; do not ship both copies.
    run("cmake", "-S", SOURCE / "frontend_cpp", "-B", "/build/frontend", "-DCMAKE_BUILD_TYPE=Release")
    run("cmake", "--build", "/build/frontend", "--parallel", "2")
    run("ctest", "--test-dir", "/build/frontend", "--output-on-failure")
    shutil.copy2("/build/frontend/blob_overlay", PREFIX / "blob_overlay")
    run("strip", PREFIX / "blob_overlay")
    (PREFIX / "bin").mkdir()
    # An application-private binary permits a narrowly scoped AppArmor rule,
    # without replacing a distro's existing /usr/bin/bwrap profile.
    shutil.copy2("/usr/bin/bwrap", PREFIX / "bin/bwrap")
    shutil.copy2(SOURCE / "deploy/debian/launcher.py", PREFIX / "launcher.py")
    for pycache in (PREFIX / "venv").rglob("__pycache__"):
        shutil.rmtree(pycache)
    STAGE.mkdir(parents=True)
    (STAGE / "opt").mkdir()
    # Same filesystem: move the complete fixed-prefix runtime, without another GB copy.
    shutil.move(str(PREFIX), STAGE / "opt/projectblob")
    for name, mode in (("blob-setup", "setup"), ("blob-start", "start"), ("blob-chat", "chat"),
                       ("blob-backend", "backend"), ("blob-overlay", "overlay")):
        write("usr/bin/" + name, "#!/bin/sh\nexec /opt/projectblob/venv/bin/python -I "
              f'/opt/projectblob/launcher.py {mode} "$@"\n', 0o755)
    write("usr/lib/projectblob/python", "#!/bin/sh\nexec /opt/projectblob/venv/bin/python -I "
          '/opt/projectblob/launcher.py python "$@"\n', 0o755)
    for name, command in (("backend", "blob-backend"), ("overlay", "blob-overlay")):
        dependency = "After=blob-backend.service\nWants=blob-backend.service\n" if name == "overlay" else ""
        write(f"usr/lib/systemd/user/blob-{name}.service", f"""[Unit]
Description=Project Blob {name}
PartOf=graphical-session.target
After=graphical-session-pre.target
{dependency}
[Service]
Type=simple
ExecStart=/usr/bin/{command}
Restart=on-failure
RestartSec=3
TimeoutStopSec=15
UMask=0077
NoNewPrivileges=yes
StandardInput=null
StandardOutput=null
StandardError=journal
""")
    for name, command, terminal in (("Project Blob", "blob-start", "false"),
            ("Blob Chat", "blob-chat", "true"), ("Blob Setup", "blob-setup", "true")):
        entry = f"usr/share/applications/{command}.desktop"
        write(entry, f"""[Desktop Entry]
Type=Application
Name={name}
Comment=Project Blob desktop companion
Exec=/usr/bin/{command}
Icon=projectblob
Terminal={terminal}
Categories=Utility;
""")
        run("desktop-file-validate", STAGE / entry)
    icon = STAGE / "usr/share/icons/hicolor/256x256/apps/projectblob.png"
    icon.parent.mkdir(parents=True)
    shutil.copy2(SOURCE / "frontend_cpp/preview/neutral_transparent.png", icon)
    write("etc/apparmor.d/projectblob", """# Application-private executables only. Chromium's sandbox stays enabled.
abi <abi/4.0>,
include <tunables/global>
profile projectblob-chromium /opt/projectblob/browsers/**/{chrome,chrome-headless-shell} flags=(unconfined) {
  userns,
}
profile projectblob-bwrap /opt/projectblob/bin/bwrap flags=(unconfined) {
  userns,
}
""")
    run("apparmor_parser", "--skip-kernel-load", "--skip-read-cache", STAGE / "etc/apparmor.d/projectblob")
    write("usr/share/doc/projectblob/README.md", (SOURCE / "deploy/debian/README.md").read_text())
    write("usr/share/doc/projectblob/copyright", (SOURCE / "LICENSE").read_text() +
          "\nBundled Bubblewrap copyright and license:\n" + Path("/usr/share/doc/bubblewrap/copyright").read_text() +
          "\nPython dependency licenses are retained in /opt/projectblob/venv/lib/python3.12/site-packages.\n"
          "Chromium notices are bundled alongside its executable.\n"
          "all-MiniLM-L6-v2 model: sentence-transformers/all-MiniLM-L6-v2, Apache-2.0.\n"
          "Full model license: /usr/share/doc/projectblob/model-license\n")
    write("usr/share/doc/projectblob/python-dependencies.txt", inventory)
    write("usr/share/doc/projectblob/model-license", Path("/usr/share/common-licenses/Apache-2.0").read_text())
    provenance = {"version": version, "source_revision": (SOURCE / "SOURCE_REVISION").read_text().strip(),
                  "target": "Ubuntu 24.04 amd64", "python": platform.python_version(),
                  "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest()}
    provenance_text = json.dumps(provenance, indent=2) + "\n"
    write("usr/share/doc/projectblob/build-info.json", provenance_text)
    Path("/out/build-info.json").write_text(provenance_text)
    size = sum(path.stat().st_size for path in STAGE.rglob("*") if path.is_file()) // 1024
    write("DEBIAN/control", f"""Package: projectblob
Version: {version}
Section: utils
Priority: optional
Architecture: amd64
Maintainer: Project Blob <harshit989111@gmail.com>
Installed-Size: {size}
Depends: {', '.join(RUNTIME)}, python3.12 (<< 3.13)
Homepage: https://github.com/HaggardHarsh/ProjectBlob
Description: Project Blob desktop AI companion (Ubuntu 24.04 test build)
 Includes the compiled overlay, Python dependencies, headless browser and
 local embedding model. Run blob-setup as your desktop user after installation.
 Cloud assistance requires your own API key and explicit opt-in.
""")
    write("DEBIAN/conffiles", "/etc/apparmor.d/projectblob\n")
    write("DEBIAN/preinst", """#!/bin/sh
set -e
if [ "$1" = install ] || [ "$1" = upgrade ]; then
    . /etc/os-release
    if [ "$ID" != ubuntu ] || [ "$VERSION_ID" != 24.04 ]; then
        echo 'This test build requires Ubuntu 24.04 amd64.' >&2
        exit 1
    fi
fi
""", 0o755)
    write("DEBIAN/postinst", """#!/bin/sh
set -e
if [ "$1" = configure ]; then
    if [ -d /sys/kernel/security/apparmor ]; then
        apparmor_parser -r /etc/apparmor.d/projectblob
    fi
    echo 'Project Blob installed. Run blob-setup as your desktop user (without sudo).'
    echo 'After an upgrade, restart Blob services or log out and back in.'
fi
""", 0o755)
    write("DEBIAN/postrm", """#!/bin/sh
set -e
if [ "$1" = remove ] && [ -d /sys/kernel/security/apparmor ] && command -v apparmor_parser >/dev/null; then
    apparmor_parser -R /etc/apparmor.d/projectblob || true
fi
""", 0o755)
    # Normalize package ownership/modes, including files copied from cached images.
    for path in STAGE.rglob("*"):
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
    package = Path("/out") / f"projectblob_{version}_amd64.deb"
    run("dpkg-deb", "--root-owner-group", "-Zxz", "-z6", "--threads-max=2", "--build", STAGE, package)
    digest = hashlib.file_digest(package.open("rb"), "sha256").hexdigest()
    package.with_suffix(".deb.sha256").write_text(digest + "  " + package.name + "\n")
    shutil.copy2(SOURCE / "deploy/debian/README.md", "/out/INSTALL.md")
    print(f"Built {package} ({package.stat().st_size // (1024 * 1024)} MiB)", flush=True)


if __name__ == "__main__":
    main()
