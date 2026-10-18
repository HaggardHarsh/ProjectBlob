"""Validate the prepared candidate inside the disposable Ubuntu validation image."""

import json
import argparse
import os
import platform
from pathlib import Path
import subprocess
import tempfile
from xml.etree import ElementTree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true", help="Reuse an existing passing JUnit result while retrying desktop checks")
    parser.add_argument("--candidate", type=Path, help="Select a prepared candidate after an update")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    candidates = list((project / ".runtime/desktop/releases").glob("*/installation.json"))
    if args.candidate:
        candidate = args.candidate.resolve(strict=True)
        if candidate.parent != project / ".runtime/desktop/releases" or not (candidate / "installation.json").is_file():
            raise RuntimeError("Select a candidate from this checkout's release directory")
    elif len(candidates) != 1:
        raise RuntimeError("Expected exactly one freshly prepared validation candidate")
    else:
        candidate = candidates[0].parent
    python = candidate / "venv/bin/python"
    if not args.resume:
        subprocess.run([str(python), "-m", "pip", "install", "pytest", "pytest-asyncio", "build"], check=True)
        subprocess.run([str(python), "-m", "pytest", str(project / "backend_python/tests"), "-q",
                        "--junitxml=" + str(candidate / "backend-tests.xml")], check=True)
    suites = ElementTree.parse(candidate / "backend-tests.xml").getroot()
    assert all(int(suite.attrib.get("failures", 0)) == int(suite.attrib.get("errors", 0)) == 0
               for suite in suites.iter("testsuite")), "Cannot resume a failing regression run"
    subprocess.run([str(python), str(project / "tools/lock_dependencies.py"), "--output",
                    str(candidate / "linux-py312.lock")], check=True)
    subprocess.run(["xvfb-run", "-a", str(candidate / "frontend/blob_overlay"), "--demo", "--frames", "60",
                    "--snapshot", str(candidate / "x11-preview.bmp")], check=True)
    subprocess.run([str(python), "-c", "from PIL import Image; import sys; "
                    "image=Image.open(sys.argv[1]); assert image.getbbox(); image.save(sys.argv[2])",
                    str(candidate / "x11-preview.bmp"), str(candidate / "x11-preview.png")], check=True)
    subprocess.run([str(python), str(project / "tools/validate_proactive.py"),
                    "--binary", str(candidate / "frontend/blob_overlay"),
                    "--report", str(candidate / "proactive-overlay.json")], check=True)
    with tempfile.TemporaryDirectory(prefix="blob-systemd-verify-") as runtime:
        subprocess.run(["systemd-analyze", "--user", "verify",
                        str(candidate / "desktop-preview/systemd/user/blob-backend.service"),
                        str(candidate / "desktop-preview/systemd/user/blob-overlay.service")],
                       env={**os.environ, "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR") or runtime}, check=True)
    subprocess.run(["desktop-file-validate", str(candidate / "desktop-preview/applications/blob-chat.desktop"),
                    str(candidate / "desktop-preview/autostart/blob.desktop")], check=True)
    report = {"python": platform.python_version(), "ubuntu_candidate": str(candidate),
              "backend_tests": [{key: suite.attrib.get(key) for key in ("tests", "failures", "errors", "skipped")}
                                for suite in suites.iter("testsuite")],
              "x11_overlay": True, "proactive_overlay": True, "startup_syntax": True}
    (candidate / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
