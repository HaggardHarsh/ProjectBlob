"""Run as a disposable normal user in an installed, network-disabled Ubuntu container."""

import json
import os
from pathlib import Path
import subprocess
import tempfile


def run(*args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, timeout=180, **kwargs)


def main():
    assert os.geteuid() != 0
    assert not Path("/usr/bin/cmake").exists(), "Test in a runtime-only image"
    home = Path.home()
    report = {"target": "Ubuntu 24.04 amd64", "external_network": False}
    run("blob-setup", "--no-key", "--no-start")
    run("blob-setup", "--no-key", "--no-start")
    assert (home / ".config/autostart/blob.desktop").is_file()
    assert not (home / ".blob/.env").exists()
    assert (home / ".cache/chroma/onnx_models/all-MiniLM-L6-v2").is_symlink()
    report["fresh_setup_and_repeat"] = True
    run("/opt/projectblob/venv/bin/python", "-m", "pip", "check")
    run("/usr/lib/projectblob/python", "/checks/test_launcher.py")
    run("/usr/lib/projectblob/python", "/src/tools/release_smoke.py", "--source-root", "/src")
    report["installed_daemon_local_commands_privacy_and_skills"] = True
    run("/usr/lib/projectblob/python", "-c",
        "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction\n"
        "assert len(DefaultEmbeddingFunction()(['Offline package test'])[0]) == 384\n"
        "print('Bundled embedding model works offline')")
    report["offline_embedding"] = True
    run("/usr/lib/projectblob/python", "-c",
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    browser = p.chromium.launch(headless=True, chromium_sandbox=True)\n"
        "    page = browser.new_page()\n"
        "    page.set_content('<title>Packaged Blob browser</title>')\n"
        "    assert page.title() == 'Packaged Blob browser'\n"
        "    browser.close()\n"
        "print('Bundled Chromium launched with sandbox enabled')")
    report["sandboxed_chromium"] = True
    run("/opt/projectblob/bin/bwrap", "--unshare-all", "--ro-bind", "/", "/", "--", "/usr/bin/true")
    report["private_bubblewrap"] = True
    run("xvfb-run", "-a", "blob-overlay", "--demo", "--frames", "60", "--snapshot", home / "overlay.bmp")
    run("/usr/lib/projectblob/python", "-c",
        "from PIL import Image\nfrom pathlib import Path\n"
        "im=Image.open(Path.home()/'overlay.bmp'); assert im.getbbox(); im.save(Path.home()/'overlay.png')")
    report["x11_overlay_render"] = True
    with tempfile.TemporaryDirectory() as runtime:
        run("systemd-analyze", "--user", "verify", "/usr/lib/systemd/user/blob-backend.service",
            "/usr/lib/systemd/user/blob-overlay.service", env={**os.environ, "XDG_RUNTIME_DIR": runtime})
    report["user_service_syntax"] = True
    # A harmless marker verifies package removal does not remove personal data.
    (home / ".blob/package-removal-probe").write_text("keep this personal file\n")
    (home / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
