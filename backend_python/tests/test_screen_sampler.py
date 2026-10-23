import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from blob.screen.sampler import ScreenSampler
from blob.screen.portal import PortalCaptureError


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["_capture_gnome_screenshot", "_capture_grim"])
@pytest.mark.parametrize("stop", ["cancel", "timeout"])
async def test_cancelled_capture_reaps_helper_and_removes_partial_file(tmp_path, monkeypatch, backend, stop):
    sampler = ScreenSampler(SimpleNamespace(), SimpleNamespace(is_capture_blocked=lambda: False))
    path = tmp_path / "frame.png"
    monkeypatch.setattr(sampler, "_get_temp_path", lambda: str(path))
    monkeypatch.setattr("blob.screen.sampler.shutil.which", lambda name: name)
    spawn = asyncio.create_subprocess_exec
    processes = []
    ready = asyncio.Event()

    async def synthetic_capture(*args, **kwargs):
        process = await spawn(sys.executable, "-c",
            "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); "
            "p.write_bytes(b'partial'); print('ready',flush=True); "
            "time.sleep(60); p.write_bytes(b'late capture')", args[-1],
            stdout=asyncio.subprocess.PIPE)
        processes.append(process)
        await process.stdout.readline()
        ready.set()
        return process

    monkeypatch.setattr("blob.screen.sampler.asyncio.create_subprocess_exec", synthetic_capture)
    task = asyncio.create_task(getattr(sampler, backend)())
    try:
        await asyncio.wait_for(ready.wait(), 5)
        assert path.exists()
        if stop == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(task, 0.01)
        assert processes[0].returncode is not None
        assert not path.exists()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for process in processes:
            if process.returncode is None:
                process.kill()
                await process.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["_capture_gnome_screenshot", "_capture_grim"])
@pytest.mark.parametrize("outcome", ["success", "invalid_image", "nonzero"])
async def test_capture_cleans_files_and_returns_detached_image(tmp_path, monkeypatch, backend, outcome):
    sampler = ScreenSampler(SimpleNamespace(), SimpleNamespace(is_capture_blocked=lambda: False))
    path = tmp_path / "frame.png"
    monkeypatch.setattr(sampler, "_get_temp_path", lambda: str(path))
    monkeypatch.setattr("blob.screen.sampler.shutil.which", lambda name: name)

    async def capture(*args, **kwargs):
        if outcome == "invalid_image":
            path.write_bytes(b"not an image")
        else:
            Image.new("RGB", (4, 4), "red").save(path)
        return SimpleNamespace(wait=AsyncMock(), returncode=1 if outcome == "nonzero" else 0)

    monkeypatch.setattr("blob.screen.sampler.asyncio.create_subprocess_exec", capture)
    image = await getattr(sampler, backend)()
    assert not path.exists()
    if outcome == "success":
        with image:
            assert image.getpixel((0, 0)) == (255, 0, 0)
    else:
        assert image is None


@pytest.mark.asyncio
async def test_privacy_shield_blocks_screen_capture_before_backends():
    shield = SimpleNamespace(is_capture_blocked=lambda: True)
    sampler = ScreenSampler(SimpleNamespace(), shield)
    sampler._capture_gnome_screenshot = AsyncMock()

    assert await sampler.capture() is None
    sampler._capture_gnome_screenshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_wayland_uses_desktop_portal_first(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    shield = SimpleNamespace(is_capture_blocked=lambda: False)
    sampler = ScreenSampler(SimpleNamespace(), shield)
    expected = Image.new("RGB", (4, 4))
    portal = AsyncMock(return_value=expected)
    monkeypatch.setattr("blob.screen.sampler.screenshot", portal)
    sampler._capture_gnome_screenshot = AsyncMock()

    assert await sampler.capture() is expected
    portal.assert_awaited_once()
    sampler._capture_gnome_screenshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_portal_denial_is_reported_without_bypassing_it(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    shield = SimpleNamespace(is_capture_blocked=lambda: False)
    sampler = ScreenSampler(SimpleNamespace(), shield)
    monkeypatch.setattr("blob.screen.sampler.screenshot", AsyncMock(
        side_effect=PortalCaptureError("Screen sharing was cancelled in the desktop permission dialog.")))
    sampler._capture_gnome_screenshot = AsyncMock()

    assert await sampler.capture() is None
    assert "cancelled" in sampler.last_error
    sampler._capture_gnome_screenshot.assert_not_awaited()
