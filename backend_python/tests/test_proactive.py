"""Simulate weeks, interruptions and privacy changes without waiting or real stores."""

import asyncio
from datetime import datetime
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from PIL import Image
import pytest

from blob.ipc import blob_service_pb2 as pb
from blob.ipc.event_dispatcher import EventDispatcher
from blob.privacy.controls import PrivacyControls
from blob.privacy.window_monitor import WindowInfo
from blob.proactive import DAY, ProactiveConversation, SessionProbe, bubble_art
from test_reply_presentation import normal_chat


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 19, 12).timestamp()
        self.mono = 10000
    def advance(self, seconds):
        self.now += seconds
        self.mono += seconds


def setup(tmp_path):
    blob = normal_chat()
    blob.config.memory_db_path = str(tmp_path / "memory")
    blob.config.model_name = "synthetic-model"
    blob.controls = PrivacyControls(tmp_path / "private/privacy.json")
    blob.controls.update(cloud_enabled=True, proactive_enabled=True)
    blob.event_dispatcher = EventDispatcher()
    queue = asyncio.Queue(maxsize=10)
    blob.event_dispatcher.register_client(1, queue)
    blob.semantic = SimpleNamespace(list_facts=MagicMock(return_value=[]), remember_explicit_statements=MagicMock())
    blob.llm._create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content="What's one small thing you enjoyed today?", tool_calls=None))]))
    blob.llm._chat_kwargs = lambda: {}
    window = WindowInfo("Untitled", "gedit", 42, (0, 0, 800, 600), "window-1", "gnome")
    shield = SimpleNamespace(is_active=False, blacklist=SimpleNamespace(is_blacklisted=lambda w: False))
    probe = SimpleNamespace(shield=shield, sample=MagicMock(return_value=(window, 30)))
    clock = Clock()
    rng = SimpleNamespace(choice=lambda rows: rows[-1], uniform=lambda a, b: 60)
    feature = ProactiveConversation(blob, clock=lambda: clock.now, monotonic=lambda: clock.mono, rng=rng, probe=probe)
    blob.proactive = feature
    clock.advance(3601)
    feature._focus, feature._focus_since = window.identity, clock.mono - 121
    refresh(feature)
    return feature, blob, clock, queue


def refresh(feature):
    feature.presence(1, pb.HeartbeatPing(client_kind=pb.HeartbeatPing.OVERLAY,
        proactive_bubbles=True, overlay_visible=True, desktop_width=1920, desktop_height=1080))


async def shown(feature):
    await feature.feedback(1, pb.ProactiveFeedback(approach_id=feature.pending["id"], action=pb.ProactiveFeedback.SHOWN))


@pytest.mark.asyncio
async def test_invitation_is_ephemeral_tool_free_and_not_saved_as_user_memory(tmp_path):
    f, blob, clock, queue = setup(tmp_path)
    assert await f.tick()
    event = queue.get_nowait()
    assert event.notification.proactive and event.notification.approach_id
    assert event.notification.display_ms == 20000 and not event.notification.delivery_id
    assert blob.llm._create.await_count == 1
    request = blob.llm._create.call_args.kwargs
    assert "tools" not in request and request["max_tokens"] == 1024
    assert not blob._recent_turns
    blob.episodic.add_episode.assert_not_called()
    blob.semantic.remember_explicit_statements.assert_not_called()
    with Image.open(io.BytesIO(event.notification.image_bmp)) as image:
        assert image.width == 340 and 116 <= image.height <= 180
    assert f.path.stat().st_mode & 0o777 == 0o600
    assert event.notification.text not in f.path.read_text()
    assert not await f.tick()
    assert blob.llm._create.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("gate", ["off", "cloud", "pause", "startup", "recent_chat", "stale_overlay", "terminal_only",
    "hidden", "night", "typing", "away", "private", "call", "fullscreen", "unknown", "shield", "changing_focus"])
async def test_unsuitable_moments_make_zero_provider_calls(tmp_path, gate):
    f, blob, clock, queue = setup(tmp_path)
    window, idle = f.probe.sample.return_value
    if gate == "off": blob.controls.update(proactive_enabled=False)
    elif gate == "cloud": blob.controls.update(cloud_enabled=False)
    elif gate == "pause": blob.controls.update(paused=True)
    elif gate == "startup": f.started = clock.mono
    elif gate == "recent_chat": f.user_activity()
    elif gate == "stale_overlay": clock.advance(20)
    elif gate == "terminal_only":
        f.clients.clear(); f.presence(1, pb.HeartbeatPing(client_kind=pb.HeartbeatPing.CHAT))
    elif gate == "hidden": f.presence(1, pb.HeartbeatPing(client_kind=pb.HeartbeatPing.OVERLAY))
    elif gate == "night": clock.now = datetime(2026, 10, 20, 23).timestamp()
    elif gate == "typing": f.probe.sample.return_value = (window, 1)
    elif gate == "away": f.probe.sample.return_value = (window, 600)
    elif gate == "private": window.title = "Bank account"
    elif gate == "call": window.title = "Google Meet"
    elif gate == "fullscreen": window.bbox = (0, 0, 1920, 1080)
    elif gate == "unknown": f.probe.sample.return_value = None
    elif gate == "shield": f.probe.shield.is_active = True
    elif gate == "changing_focus": window.identity = "new-window"
    assert not await f.tick()
    blob.llm._create.assert_not_awaited()
    assert queue.empty()


def row(clock, days, topic="social:day", outcome="answered"):
    return {"id": str(days), "topic": topic, "at": clock.now - days * DAY, "outcome": outcome, "words": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [[0.9], [1.1, 3.3, 6.9]])
async def test_hard_daily_and_rolling_weekly_limits(tmp_path, days):
    f, blob, clock, _ = setup(tmp_path)
    f.state["history"] = [row(clock, d) for d in days]
    assert not await f.tick()
    blob.llm._create.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_and_toggling_never_reset_spacing_or_budget(tmp_path):
    f, blob, clock, _ = setup(tmp_path)
    assert await f.tick()
    original = f.state["next_at"]
    await f.command("/proactive off")
    await f.command("/proactive on")
    assert f.state["next_at"] == original
    clock.advance(3601)
    reopened = ProactiveConversation(blob, clock=lambda: clock.now, monotonic=lambda: clock.mono, probe=f.probe)
    assert reopened.state["next_at"] >= f.state["history"][0]["at"] + 3 * DAY
    assert reopened.state["history"][0]["outcome"] == "ignored"


@pytest.mark.asyncio
async def test_ignore_and_dismiss_never_create_followup_nudges(tmp_path):
    f, blob, clock, queue = setup(tmp_path)
    assert await f.tick()
    await shown(f)
    await f.feedback(1, pb.ProactiveFeedback(approach_id=f.pending["id"], action=pb.ProactiveFeedback.DISMISSED))
    assert f.pending is None
    assert f.state["next_at"] >= clock.now + 3 * DAY
    assert not await f.tick()
    assert blob.llm._create.await_count == 1


@pytest.mark.asyncio
async def test_quiet_today_and_mute_persist_and_work_while_paused(tmp_path):
    f, blob, clock, _ = setup(tmp_path)
    blob.controls.update(paused=True, cloud_enabled=False)
    assert "peace" in await f.command("/proactive quiet")
    assert f.state["quiet_until"] > clock.now
    assert "off" in await f.command("/proactive off")
    assert not PrivacyControls(blob.controls.path).state["proactive_enabled"]
    blob.llm._create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["user", "pause", "cloud", "focus", "disconnect", "quiet_hours"])
async def test_inflight_opening_discarded_after_changes(tmp_path, interruption):
    f, blob, clock, queue = setup(tmp_path)
    async def generate(**kwargs):
        if interruption == "user": f.user_activity()
        elif interruption == "pause": blob.controls.update(paused=True)
        elif interruption == "cloud": blob.controls.update(cloud_enabled=False)
        elif interruption == "focus": f.probe.sample.return_value[0].identity = "different"
        elif interruption == "disconnect": f.disconnect(1)
        elif interruption == "quiet_hours": clock.now = datetime(2026, 10, 19, 23).timestamp()
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="What's one good thing about today?", tool_calls=None))])
    blob.llm._create.side_effect = generate
    assert not await f.tick()
    assert queue.empty()
    assert f.state["next_at"] > clock.now + DAY


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["Why haven't you talked to me?", "You seem depressed, want to talk?",
    'Hey! {"tool":"reminder","args":{}}', "Day?<|reserved_token_123|>", "Hello!", "Hi? Hi?", "x" * 180 + "?",
    "Could you email alex@example.com?", "I missed you, how are you?", "How did your presentation go?", "Are you there?"])
async def test_bad_model_openings_are_silent_and_never_retried(tmp_path, content):
    f, blob, clock, queue = setup(tmp_path)
    blob.llm._create.return_value.choices[0].message.content = content
    assert not await f.tick()
    assert not await f.tick()
    assert queue.empty()
    assert blob.llm._create.await_count == 1


@pytest.mark.asyncio
async def test_repetition_rejected_even_with_a_new_topic(tmp_path):
    f, blob, clock, queue = setup(tmp_path)
    assert await f.tick()
    clock.advance(4 * DAY)
    refresh(f)
    assert not await f.tick()
    assert blob.llm._create.await_count == 2


@pytest.mark.asyncio
async def test_distinct_subjects_are_not_rejected_for_shared_conversational_words(tmp_path):
    f, blob, clock, queue = setup(tmp_path)
    blob.llm._create.return_value.choices[0].message.content = "What's one thing you enjoyed today?"
    assert await f.tick()
    clock.advance(4 * DAY)
    refresh(f)
    blob.llm._create.return_value.choices[0].message.content = "What's one thing you enjoyed photographing lately?"
    assert await f.tick()


def test_memory_topics_are_only_grounded_interest_labels(tmp_path):
    f, blob, _, _ = setup(tmp_path)
    blob.semantic.list_facts.return_value = [
        {"text": "I enjoy photography at SecretCompany", "metadata": {"grounded": True, "source_episode_id": "source1"}},
        {"text": "I enjoy gaming", "metadata": {"grounded": False}},
        {"text": "I don't like cooking", "metadata": {"grounded": True, "source_episode_id": "source2"}},
        {"text": "Draft an old email to someone", "metadata": {"grounded": True, "source_episode_id": "source3"}},
    ]
    topics = f._topics()
    assert "SecretCompany" not in str(topics) and "old email" not in str(topics)
    assert any(key == "interest:photography" for key, _ in topics)
    assert not any(key in {"interest:gaming", "interest:cooking"} for key, _ in topics)


def test_screen_topics_use_only_current_opted_in_brief(tmp_path):
    f, blob, _, _ = setup(tmp_path)
    blob.awareness = SimpleNamespace(context=lambda: "Working with code. Detected topics: Python.")
    assert any(key == "screen:Python" for key, _ in f._topics())
    blob.awareness.context = lambda: ""
    assert not any(key.startswith("screen:") for key, _ in f._topics())


@pytest.mark.asyncio
async def test_reply_uses_real_assistant_role_and_never_invents_a_user_turn(tmp_path):
    f, blob, clock, queue = setup(tmp_path)
    assert await f.tick()
    await shown(f)
    opener = f.pending["text"]
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content="That sounds lovely.")
    await blob.handle_user_message(pb.UserMessage(text="I baked something nice"))
    messages = blob.llm.generate_from_messages.call_args.args[0]
    assert {"role": "assistant", "content": opener} in messages
    assert not any(m["role"] == "user" and m["content"] == opener for m in messages)
    assert f.pending is None and f.state["history"][-1]["outcome"] == "answered"
    assert blob.episodic.add_episode.call_args.args[0] == "I baked something nice"


@pytest.mark.asyncio
async def test_invitation_history_write_failure_never_blocks_a_user_reply(tmp_path):
    f, blob, _, _ = setup(tmp_path)
    assert await f.tick()
    await shown(f)
    f._save = MagicMock(side_effect=OSError("synthetic disk full"))
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content="That sounds lovely.")
    assert await blob.handle_user_message(pb.UserMessage(text="I baked something nice")) == "That sounds lovely."
    assert f.storage_error and not await f.tick()


@pytest.mark.asyncio
async def test_duplicate_clients_and_full_queue_never_make_extra_bubbles(tmp_path):
    f, blob, clock, queue = setup(tmp_path)
    other = asyncio.Queue()
    blob.event_dispatcher.register_client(2, other)
    f.presence(2, pb.HeartbeatPing(client_kind=pb.HeartbeatPing.OVERLAY, proactive_bubbles=True,
        overlay_visible=True, desktop_width=1920, desktop_height=1080))
    assert await f.tick()
    assert queue.qsize() + other.qsize() == 1
    f2, blob2, _, queue2 = setup(tmp_path / "second")
    for _ in range(10): queue2.put_nowait(pb.BackendEvent())
    assert not await f2.tick()
    assert queue2.qsize() == 10 and f2.pending is None


@pytest.mark.asyncio
async def test_hide_never_sends_blank_notifications_to_old_chat_clients(tmp_path):
    f, blob, _, queue = setup(tmp_path)
    legacy_chat = asyncio.Queue()
    blob.event_dispatcher.register_client(2, legacy_chat)
    assert await f.tick()
    await f.hide()
    assert legacy_chat.empty() and queue.qsize() == 2
    await f.hide()
    assert legacy_chat.empty() and queue.qsize() == 2


def test_invalid_history_cannot_reset_rate_limits(tmp_path):
    f, blob, _, _ = setup(tmp_path)
    f.path.parent.mkdir(parents=True, exist_ok=True)
    f.path.write_text('{"version":1,"history":[]}')
    with pytest.raises(ValueError): ProactiveConversation(blob, probe=f.probe)


@pytest.mark.asyncio
async def test_fresh_short_acceptance_answers_the_invitation(tmp_path):
    f, blob, _, _ = setup(tmp_path)
    assert await f.tick()
    await shown(f)
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content="What was the nice part?")
    assert await blob.handle_user_message(pb.UserMessage(text="sure")) == "What was the nice part?"
    blob.llm.generate_from_messages.assert_awaited_once()


def test_deleting_document_context_keeps_an_independent_invitation(tmp_path):
    f, blob, _, _ = setup(tmp_path)
    blob._recent_turns.extend([{"role": "user", "content": "Explain [Attached: report.pdf]"},
        {"role": "assistant", "content": "A document answer."},
        {"role": "assistant", "content": "How has your day been?"},
        {"role": "user", "content": "Pretty good"}, {"role": "assistant", "content": "Nice."}])
    blob._prune_recent_context("[Attached:", ["report.pdf"])
    assert not any("document answer" in t["content"] for t in blob._recent_turns)
    assert any("How has your day" in t["content"] for t in blob._recent_turns)


@pytest.mark.asyncio
async def test_quiet_controls_are_authenticated_confirmed_and_local_when_cloud_off(tmp_path):
    import grpc
    from blob.ipc import blob_service_pb2_grpc as rpc
    from blob.ipc.auth import ipc_token
    from blob.ipc.server import start_grpc_server
    f, blob, _, _ = setup(tmp_path)
    blob.config.ipc_address = "unix:" + str(tmp_path / "controls.sock")
    blob.config.ipc_token_path = str(tmp_path / "private/token")
    blob.controls.update(paused=True, cloud_enabled=False)
    server, service = await start_grpc_server(blob.config, blob, blob.event_dispatcher)
    try:
        async with grpc.aio.insecure_channel(blob.config.ipc_address) as channel:
            stub = rpc.BlobServiceStub(channel)
            with pytest.raises(grpc.aio.AioRpcError):
                await stub.UpdateConfig(pb.ConfigUpdate(settings={"proactive_mode": "off"}))
            assert f.enabled
            metadata = (("x-blob-token", ipc_token(blob.config.ipc_token_path)),)
            response = await stub.UpdateConfig(pb.ConfigUpdate(settings={"proactive_mode": "quiet"}), metadata=metadata)
            assert response.success and f.state["quiet_until"] > f.clock()
            response = await stub.UpdateConfig(pb.ConfigUpdate(settings={"proactive_mode": "off"}), metadata=metadata)
            assert response.success and not f.enabled
            response = await stub.UpdateConfig(pb.ConfigUpdate(settings={"proactive_mode": "on"}), metadata=metadata)
            assert not response.success
            blob.llm._create.assert_not_awaited()
    finally:
        await service.close_streams()
        await server.stop(0)


def test_bubble_art_has_bounded_portable_bmp_layout():
    data = bubble_art("What's something small you're looking forward to?")
    with Image.open(io.BytesIO(data)) as image:
        assert len(data) == 54 + 340 * image.height * 3
        assert image.getpixel((0, 0)) == (255, 0, 255)


@pytest.mark.asyncio
async def test_repeated_ignored_approaches_back_off_for_a_week(tmp_path):
    f, blob, clock, queue = setup(tmp_path)
    f.state["history"] = [row(clock, 4, "social:day", "ignored")]
    assert await f.tick()
    await shown(f)
    await f.feedback(1, pb.ProactiveFeedback(approach_id=f.pending["id"], action=pb.ProactiveFeedback.DISMISSED))
    assert f.state["next_at"] >= clock.now + 7 * DAY


@pytest.mark.asyncio
async def test_a_discarded_generation_does_not_reset_ignored_approach_backoff(tmp_path):
    f, blob, clock, _ = setup(tmp_path)
    f.state["history"] = [row(clock, 5, "social:day", "ignored"), row(clock, 3, "social:small_win", "attempted")]
    assert await f.tick()
    await shown(f)
    await f.feedback(1, pb.ProactiveFeedback(approach_id=f.pending["id"], action=pb.ProactiveFeedback.DISMISSED))
    assert f.state["next_at"] >= clock.now + 7 * DAY
