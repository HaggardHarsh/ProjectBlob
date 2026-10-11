"""Validate the GNOME bridge/OCR in an isolated headless desktop with synthetic windows.

Run: dbus-run-session -- venv/bin/python tools/validate_awareness_desktop.py
Requires GNOME Shell 45+, system GTK4 bindings, the installed Blob extension,
and a local OCR backend. No cloud calls or real desktop captures are made.
"""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from blob.config import BlobConfig
from blob.privacy.controls import PrivacyControls
from blob.privacy.shield import PrivacyShield
from blob.screen.awareness import ScreenAwareness
from blob.screen.ocr import OCRProcessor
from blob.screen.sampler import ScreenSampler
from blob.screen.gnome_bridge import bridge_token, capture_window

FIXTURE = """
import gi, sys
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk
app = Gtk.Application(application_id='org.projectblob.AwarenessFixture')
def activate(app):
    provider = Gtk.CssProvider()
    provider.load_from_data(b'label { font-size: 30px; padding: 24px; }')
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, 600)
    window = Gtk.ApplicationWindow(application=app, title=sys.argv[1])
    window.set_default_size(1000, 550)
    window.set_child(Gtk.Label(label=sys.argv[2], wrap=True))
    window.present()
app.connect('activate', activate)
app.run([])
"""


async def wait_window(shield, title, process):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Synthetic window process exited")
        window = await asyncio.to_thread(shield.monitor.get_active_window)
        if window and window.title == title:
            return window
        await asyncio.sleep(0.25)
    raise RuntimeError("Timed out waiting for the synthetic window/installed GNOME bridge")


async def wait_bridge(shell):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if shell.poll() is not None:
            raise RuntimeError("Isolated GNOME desktop exited")
        result = await asyncio.to_thread(subprocess.run, ["gdbus", "call", "--session",
            "--dest", "org.gnome.Shell", "--object-path", "/org/projectblob/Awareness",
            "--method", "org.projectblob.Awareness.GetWindow"],
            capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            # A headless Shell starts in its overview; leave it through the
            # public property before presenting the synthetic application.
            await asyncio.to_thread(subprocess.run, ["gdbus", "call", "--session",
                "--dest", "org.gnome.Shell", "--object-path", "/org/gnome/Shell",
                "--method", "org.freedesktop.DBus.Properties.Set", "org.gnome.Shell",
                "OverviewActive", "<false>"], capture_output=True, text=True, timeout=2)
            return
        await asyncio.sleep(0.5)
    raise RuntimeError("Installed GNOME bridge did not load in the isolated desktop")


async def validate(root):
    bridge_token(create=True)
    config = BlobConfig(blacklist_path=str(root / "none"))
    controls = PrivacyControls(root / "private/privacy.json")
    controls.update(awareness_enabled=True, cloud_enabled=False)
    shield = PrivacyShield(config, controls=controls)
    sampler = ScreenSampler(config, shield)
    awareness = ScreenAwareness(config, sampler, OCRProcessor(), controls)
    checks = []
    def check(name, passed):
        checks.append({"case": name, "passed": bool(passed)})
        print(name + ": " + ("PASS" if passed else "FAIL"), flush=True)
    fixture = None
    def show(title, text):
        nonlocal fixture
        if fixture:
            fixture.terminate()
            fixture.wait(timeout=5)
        fixture = subprocess.Popen(["/usr/bin/python3", "-c", FIXTURE, title, text],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return fixture
    try:
        window = await wait_window(shield, "Physics lesson", show("Physics lesson",
            "Voltage divider\nResistance and Ohm's law\nAlice Smith\nalice@example.com\n12 V, 2 kohm"))
        check("native_wayland_window_detected", window.backend == "gnome")
        check("unauthorized_capture_rejected", await capture_window(window.identity, token="invalid") is None)
        image = await sampler.capture_active_window(window)
        check("active_window_capture_in_memory", image is not None)
        if image:
            image.close()
        await awareness.sample_once(window)
        brief = awareness.context()
        check("real_local_ocr_detects_voltage_divider", "voltage divider" in brief)
        check("summary_excludes_personal_and_exact_screen_text", bool(brief) and all(
            value not in brief for value in ("Alice", "alice@example", "12 V", "Physics lesson")))
        await wait_window(shield, "Blob Chat", show("Blob Chat", "Blob> Help me with this"))
        check("switch_to_blob_retains_recent_activity", "voltage divider" in awareness.context())
        window = await wait_window(shield, "Private test", show("Private test", "Python\nPassword: synthetic-secret"))
        await awareness.sample_once(window)
        check("credential_screen_excluded_locally", awareness.activity is None)
        await wait_window(shield, "Inbox", show("Inbox", "Private synthetic correspondence"))
        check("private_window_blocks_capture", shield.is_capture_blocked())
        window = await wait_window(shield, "Physics lesson", show("Physics lesson", "Voltage divider\nResistance"))
        await awareness.sample_once(window)
        controls.update(paused=True)
        check("manual_pause_clears_context", not awareness.context() and awareness.activity is None)
        check("no_screenshot_files_saved", not list(root.rglob("*.png")))
        return {"mode": "isolated-gnome-desktop", "cloud_calls": 0,
                "inputs": "Synthetic GTK windows only; separate session bus and virtual monitor.", "results": checks}
    finally:
        if fixture:
            fixture.terminate()
            fixture.wait(timeout=5)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    os.environ["XDG_SESSION_TYPE"] = "wayland"
    os.environ["WAYLAND_DISPLAY"] = "blob-awareness-test"
    with tempfile.TemporaryDirectory(prefix="blob-awareness-desktop-") as directory:
        root = Path(directory)
        with (root / "shell.log").open("w") as log:
            shell = subprocess.Popen(["gnome-shell", "--headless", "--wayland", "--no-x11",
                "--virtual-monitor", "1280x800", "--wayland-display", "blob-awareness-test"], stdout=log, stderr=log)
            try:
                async def run():
                    await wait_bridge(shell)
                    return await validate(root)
                report = asyncio.run(run())
                if args.report:
                    args.report.parent.mkdir(parents=True, exist_ok=True)
                    args.report.write_text(json.dumps(report, indent=2) + "\n")
                raise SystemExit(0 if all(check["passed"] for check in report["results"]) else 1)
            except RuntimeError:
                print((root / "shell.log").read_text()[-12000:])
                raise
            finally:
                shell.terminate()
                try:
                    shell.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    shell.kill()
                    shell.wait()


if __name__ == "__main__":
    main()
