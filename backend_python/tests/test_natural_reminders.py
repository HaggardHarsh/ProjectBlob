"""Natural timer requests must schedule exactly the current user's duration."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.ai.llm_engine import NebiusEngine
from blob.evals.private_workflow import Events, make_assistant, close_assistant
from blob.ipc import blob_service_pb2 as pb
from blob.privacy.controls import PrivacyControls
from blob.skills.builtin.reminder import ReminderSkill
from blob.skills.registry import SkillRegistry
from blob.skills.reminder_requests import relative_reminder_request
from test_model_continuity import assistant


@pytest.mark.parametrize("text,seconds,topic", [
    ("remind me after 1 min", 60, None),
    ("remind me in 10 seconds", 10, None),
    ("Remind me in 3min", 180, None),
    ("remind me in one minute", 60, None),
    ("remind me after a minute", 60, None),
    ("remind me in an hour", 3600, None),
    ("remind me after half an hour", 1800, None),
    ("Please remind me in 1.5 hours to take a break.", 5400, "take a break"),
    ("Could you please remind me to drink water in ten seconds?", 10, "drink water"),
    ("Hey Blob, remind me about my tea after 2 mins, please!", 120, "my tea"),
    ("set a timer for 30 seconds", 30, None),
    ("start a timer for 2h", 7200, None),
    ("set me a reminder in 2 days to check the garden", 172800, "check the garden"),
    ("Remind me to stretch and drink water in five minutes", 300, "stretch and drink water"),
])
def test_current_request_supplies_exact_relative_time(text, seconds, topic):
    args = relative_reminder_request(text)
    assert args["minutes"] * 60 == pytest.approx(seconds)
    assert args["message"] == (topic or text)
    assert args["action"] == "set"


@pytest.mark.parametrize("text", [
    "Don't remind me in 10 seconds",
    "Explain how to say remind me after 1 min",
    'Translate "remind me in 10 seconds" into French',
    '"remind me in 10 seconds"',
    "I said remind me in 10 seconds earlier",
    "Remind me tomorrow at 9",
    "Remind me in 1 hour and 30 minutes",
    "Remind me in 1 or 2 minutes",
    "Remind me in 5 minutes, then list reminders",
    "Remind me to stretch in 5 minutes and drink water in 10 minutes",
    "Remind me every 5 minutes",
    "Remind me in 10 minutes if I haven't finished",
    "Remind me in 10 minutes, actually don't",
    "Cancel my reminder in 10 minutes",
])
def test_ambiguous_or_non_action_text_is_not_a_direct_timer(text):
    assert relative_reminder_request(text) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["classic", "hermes"])
@pytest.mark.parametrize("privacy", ["cloud_on", "cloud_off", "paused"])
async def test_old_history_cannot_change_timer_or_create_duplicates(tmp_path, runtime, privacy):
    blob = assistant(tmp_path)
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    controls.update(cloud_enabled=privacy == "cloud_on", paused=privacy == "paused")
    blob.controls = controls
    blob.llm = NebiusEngine("", "https://synthetic.invalid", "synthetic", controls=controls)
    blob.llm._create = AsyncMock(side_effect=AssertionError("Simple timers must not call the model"))
    if runtime == "hermes":
        blob.agent_runtime = SimpleNamespace(run=AsyncMock(side_effect=AssertionError("No model needed")))
    blob.skill_registry = SkillRegistry(tmp_path / "skills", controls=controls)
    clock = [1000.0]
    reminder = ReminderSkill(tmp_path / "reminders.sqlite3", now=lambda: clock[0])
    blob.skill_registry.register(reminder)
    blob._recent_turns.extend([
        {"role": "user", "content": "remind me in 3min"},
        {"role": "assistant", "content": "Reminder set for 3 minutes."},
    ])
    try:
        for text, seconds in [("remind me in 10 seconds", 10), ("remind me after 1 min", 60)]:
            reply = await blob.handle_user_message(pb.UserMessage(text=text))
            records = [r for r in reminder.reminders if r["message"] == text]
            assert len(records) == 1
            assert records[0]["due_at"] == pytest.approx(clock[0] + seconds)
            assert records[0]["id"] in reply
            assert ReminderSkill._date(clock[0] + seconds) in reply
            assert "3 minutes" not in reply and "one reminder per turn" not in reply
        assert len(reminder.reminders) == 2
        blob.llm._create.assert_not_awaited()
        if runtime == "hermes":
            blob.agent_runtime.run.assert_not_awaited()
        assert [r["success"] for r in blob.skill_registry.history] == [True, True]
    finally:
        await reminder.close()


@pytest.mark.asyncio
async def test_active_document_and_cancel_word_do_not_change_timer_action(tmp_path):
    blob = assistant(tmp_path)
    blob._active_attachments = ["/some/lesson.pdf"]
    blob._handle_attachment_message = AsyncMock()
    blob.skill_registry = SkillRegistry(tmp_path / "skills")
    reminder = ReminderSkill(tmp_path / "reminders.sqlite3", now=lambda: 1000)
    blob.skill_registry.register(reminder)
    try:
        await blob.handle_user_message(pb.UserMessage(text="Remind me to read this PDF in 10 minutes"))
        await blob.handle_user_message(pb.UserMessage(text="Remind me to cancel a subscription in 20 minutes"))
        assert [(r["message"], r["due_at"]) for r in reminder.reminders] == [
            ("read this PDF", 1600), ("cancel a subscription", 2200),
        ]
        blob._handle_attachment_message.assert_not_awaited()
        blob.llm.generate_from_messages.assert_not_awaited()
    finally:
        await reminder.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["disabled", "storage", "zero", "negative"])
async def test_natural_reminder_failure_never_claims_scheduling(tmp_path, failure):
    blob = assistant(tmp_path)
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    blob.controls = controls
    blob.skill_registry = SkillRegistry(tmp_path / "skills", controls=controls)
    reminder = ReminderSkill(tmp_path / "reminders.sqlite3")
    blob.skill_registry.register(reminder)
    if failure == "disabled":
        controls.update(disabled_skills=["reminder"])
    elif failure == "storage":
        reminder.store.add = lambda *args: (_ for _ in ()).throw(OSError("Disk full"))
    amount = "0" if failure == "zero" else "-1" if failure == "negative" else "1"
    try:
        reply = await blob.handle_user_message(pb.UserMessage(text=f"Remind me after {amount} min"))
        assert "Reminder set" not in reply
        assert not reminder.reminders
        assert not blob.skill_registry.history[-1]["success"]
        blob.llm.generate_from_messages.assert_not_awaited()
    finally:
        await reminder.close()


@pytest.mark.asyncio
async def test_natural_reminder_archives_receipt_and_delivers_animation_identifier(tmp_path):
    events = Events()
    blob = make_assistant(tmp_path, events, [], live=False)
    reminder = blob.skill_registry.get_skill("reminder")
    clock = [1000.0]
    reminder._now = lambda: clock[0]
    blob.event_dispatcher.broadcast = AsyncMock()
    blob.llm.generate_from_messages = AsyncMock(side_effect=AssertionError("No model needed"))
    try:
        text = "Remind me in 10 seconds to stretch"
        reply = await blob.handle_user_message(pb.UserMessage(text=text))
        identifier = reminder.reminders[0]["id"]
        assert identifier in reply
        assert blob.vector_store.episodic.get(include=["documents"])["documents"] == [f"User: {text}\nBlob: {reply}"]
        clock[0] += 10
        reminder._wake.set()
        for _ in range(100):
            notices = [call.args[0].notification for call in events.broadcast.await_args_list
                       if call.args[0].HasField("notification") and call.args[0].notification.delivery_id]
            if notices:
                break
            await asyncio.sleep(0.01)
        assert len(notices) == 1
        assert identifier in notices[0].text and "stretch" in notices[0].text
        assert notices[0].delivery_id and not notices[0].proactive
        blob.llm.generate_from_messages.assert_not_awaited()
    finally:
        await close_assistant(blob)
