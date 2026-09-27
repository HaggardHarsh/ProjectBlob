from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.privacy.shield import PrivacyShield


def test_capture_check_rechecks_current_window():
    shield = PrivacyShield.__new__(PrivacyShield)
    shield.is_active = False
    shield.monitor = SimpleNamespace(get_active_window=lambda: SimpleNamespace(title="bank", process_name="browser"))
    shield.blacklist = SimpleNamespace(is_blacklisted=lambda window: window.title == "bank")
    assert shield.is_capture_blocked()


def test_active_shield_blocks_even_if_window_monitor_is_unavailable():
    shield = PrivacyShield.__new__(PrivacyShield)
    shield.is_active = True
    shield.monitor = SimpleNamespace(get_active_window=lambda: None)
    assert shield.is_capture_blocked()


@pytest.mark.asyncio
async def test_shield_state_is_broadcast_to_frontend():
    shield = PrivacyShield.__new__(PrivacyShield)
    shield.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    await shield._broadcast_state(True, "Sensitive window active")
    event = shield.event_dispatcher.broadcast.call_args.args[0]
    assert event.privacy.activated is True
