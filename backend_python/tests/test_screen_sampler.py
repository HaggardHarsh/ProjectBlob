from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from blob.screen.sampler import ScreenSampler
from blob.screen.portal import PortalCaptureError


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
