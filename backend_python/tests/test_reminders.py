import asyncio
from datetime import datetime, timezone
import os
from unittest.mock import AsyncMock

import pytest

from blob.skills.builtin.reminder import ReminderSkill
from blob.skills.reminder_store import ReminderStore


@pytest.mark.asyncio
async def test_pending_reminder_survives_shutdown_and_fires_once_on_restart(tmp_path, capsys):
    path = tmp_path / "private" / "reminders.sqlite3"
    now = [datetime(2026, 10, 2, 18, tzinfo=timezone.utc).timestamp()]
    original = ReminderSkill(path, now=lambda: now[0])
    result = await original.async_execute({"message": "Study HDL", "minutes": 25})
    assert result.success
    identifier = original.reminders[0]["id"]
    assert identifier in result.output
    await original.close()
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert os.stat(path.parent).st_mode & 0o777 == 0o700

    now[0] += 60 * 60
    resumed = ReminderSkill(path, now=lambda: now[0])
    resumed.set_dispatcher(AsyncMock())
    resumed.prompt_waiting = lambda: True
    delivered = asyncio.Event()
    resumed.dispatcher.broadcast.side_effect = lambda event: delivered.set()
    resumed.start()
    try:
        await asyncio.wait_for(delivered.wait(), 1)
        await asyncio.sleep(0)
        assert resumed.reminders == []
        notifications = [call.args[0] for call in resumed.dispatcher.broadcast.await_args_list
                         if call.args[0].HasField("notification")]
        assert len(notifications) == 1
        assert "Overdue reminder" in notifications[0].notification.text
        assert "Study HDL" in notifications[0].notification.text
        output = capsys.readouterr().out
        assert "Blob> " in output
        assert "was due" in output
    finally:
        await resumed.close()
    again = ReminderSkill(path, now=lambda: now[0])
    assert again.reminders == []
    await again.close()


@pytest.mark.asyncio
async def test_scheduled_offset_and_snooze_cancel_persist(tmp_path):
    path = tmp_path / "reminders.sqlite3"
    now = datetime(2026, 10, 2, tzinfo=timezone.utc).timestamp()
    skill = ReminderSkill(path, now=lambda: now)
    result = await skill.async_execute({"message": "Get ready for exam", "at": "2026-10-05T09:00:00+05:30"})
    assert result.success
    record = skill.reminders[0]
    assert record["due_at"] == datetime(2026, 10, 5, 3, 30, tzinfo=timezone.utc).timestamp()
    assert (await skill.async_execute({"action": "snooze", "id": record["id"], "minutes": 10})).success
    await skill.close()
    restarted = ReminderSkill(path, now=lambda: now)
    try:
        assert restarted.reminders[0]["due_at"] == now + 600
        listing = await restarted.async_execute({"action": "list"})
        assert record["id"] in listing.output and "Get ready for exam" in listing.output
        assert (await restarted.async_execute({"action": "cancel", "id": record["id"]})).success
        assert not (await restarted.async_execute({"action": "cancel", "id": record["id"]})).success
        assert restarted.reminders == []
    finally:
        await restarted.close()
    reopened = ReminderSkill(path)
    assert reopened.reminders == []
    await reopened.close()


def test_repeating_reminder_skips_missed_intervals_and_keeps_original_cadence(tmp_path):
    store = ReminderStore(tmp_path / "reminders.sqlite3")
    identifier = store.add("Stretch", 1000, 30, 900)
    store.close()
    resumed = ReminderStore(tmp_path / "reminders.sqlite3")
    try:
        due = resumed.take_due(1000 + 5 * 1800 + 200)
        assert [record["id"] for record in due] == [identifier]
        assert resumed.take_due(1000 + 5 * 1800 + 200) == []
        assert resumed.pending()[0]["due_at"] == 1000 + 6 * 1800
        assert len(resumed.pending()) == 1
    finally:
        resumed.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [
    {"message": "Study", "minutes": float("nan")},
    {"message": "Study", "minutes": float("inf")},
    {"message": "Study", "minutes": True},
    {"message": "Study", "minutes": -1},
    {"message": "Study", "minutes": "5"},
    {"message": "Study", "minutes": 1, "at": "2026-10-05T09:00:00+05:30"},
    {"message": "Study", "at": "not a date"},
    {"message": "Study", "at": "2020-01-01T09:00:00+05:30"},
    {"message": "Study", "minutes": 1, "repeat_minutes": 0.5},
    {"message": "  ", "minutes": 1},
    {"action": "snooze", "id": "missing"},
    {"action": "list", "minutes": 5},
    {"message": "Study", "minutes": 1, "unexpected": "value"},
    ["not", "an", "object"],
])
async def test_invalid_reminders_create_no_tasks_or_records(tmp_path, args):
    skill = ReminderSkill(tmp_path / "reminders.sqlite3")
    try:
        result = await skill.async_execute(args)
        assert not result.success
        assert skill.reminders == []
        assert skill._worker is None
    finally:
        await skill.close()


@pytest.mark.asyncio
async def test_worker_handles_delivery_failure_and_second_due_reminder(tmp_path, capsys):
    now = [1000.0]
    skill = ReminderSkill(tmp_path / "reminders.sqlite3", now=lambda: now[0])
    first = skill.store.add("First", 900, None, 800)
    second = skill.store.add("Second", 950, None, 800)
    skill.set_dispatcher(AsyncMock())
    done = asyncio.Event()

    async def broadcast(event):
        if event.HasField("notification") and first in event.notification.text:
            raise RuntimeError("Overlay disconnected")
        if event.HasField("notification") and second in event.notification.text:
            done.set()

    skill.dispatcher.broadcast.side_effect = broadcast
    skill.start()
    try:
        await asyncio.wait_for(done.wait(), 1)
        assert skill.reminders == []
        output = capsys.readouterr().out
        assert "First" in output and "Second" in output
    finally:
        await skill.close()


def test_reminder_store_does_not_change_existing_parent_permissions(tmp_path):
    os.chmod(tmp_path, 0o755)
    store = ReminderStore(tmp_path / "reminders.sqlite3")
    store.close()
    assert os.stat(tmp_path).st_mode & 0o777 == 0o755
