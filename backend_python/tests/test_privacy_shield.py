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


def test_unknown_window_reason_explains_desktop_bridge_without_exposing_metadata():
    shield = PrivacyShield.__new__(PrivacyShield)
    shield.monitor = SimpleNamespace(get_active_window=lambda: None)
    reason = shield.capture_block_reason()
    assert "active window" in reason and "bridge" in reason and "logout/login" in reason


def test_capture_rechecks_safe_window_after_cached_sensitive_state():
    shield = PrivacyShield.__new__(PrivacyShield)
    shield.is_active = True
    shield.monitor = SimpleNamespace(get_active_window=lambda: SimpleNamespace(title="Lecture notes", process_name="firefox"))
    shield.blacklist = SimpleNamespace(is_blacklisted=lambda window: False)
    assert not shield.is_capture_blocked()


def test_manual_pause_and_sensitive_window_have_distinct_reasons():
    shield = PrivacyShield.__new__(PrivacyShield)
    shield.controls = SimpleNamespace(paused=True)
    shield.monitor = SimpleNamespace(get_active_window=lambda: SimpleNamespace(title="Private browsing", process_name="firefox"))
    shield.blacklist = SimpleNamespace(is_blacklisted=lambda window: False)
    assert "/privacy resume" in shield.capture_block_reason()
    shield.controls.paused = False
    reason = shield.capture_block_reason()
    assert "marked sensitive" in reason and "Private browsing" not in reason


@pytest.mark.asyncio
async def test_shield_state_is_broadcast_to_frontend():
    shield = PrivacyShield.__new__(PrivacyShield)
    shield.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    await shield._broadcast_state(True, "Sensitive window active")
    event = shield.event_dispatcher.broadcast.call_args.args[0]
    assert event.privacy.activated is True
