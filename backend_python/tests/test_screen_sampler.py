from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.screen.sampler import ScreenSampler


@pytest.mark.asyncio
async def test_privacy_shield_blocks_screen_capture_before_backends():
    shield = SimpleNamespace(is_capture_blocked=lambda: True)
    sampler = ScreenSampler(SimpleNamespace(), shield)
    sampler._capture_gnome_screenshot = AsyncMock()

    assert await sampler.capture() is None
    sampler._capture_gnome_screenshot.assert_not_awaited()
