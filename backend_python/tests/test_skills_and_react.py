import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from PIL import Image
from unittest.mock import AsyncMock, MagicMock
from blob.skills.base import SkillResult
from blob.skills.builtin.reminder import ReminderSkill
from blob.skills.builtin.weather import WeatherSkill
from blob.skills.builtin.screen_capture import ScreenCaptureSkill
from blob.skills.builtin.file_search import FileSearchSkill
from blob.skills.registry import SkillRegistry
from blob.ai.orchestrator import BlobOrchestrator, SCREEN_REQUEST, _requested_face, _wants_screen_capture
from blob.ai.guardrails import unsupported_personal_event_claim
from blob.ai.context_budget import prompt_size_bytes
from blob.ai.llm_engine import NebiusEngine
from blob.ipc import blob_service_pb2
from blob.privacy.controls import PrivacyControls


@pytest.mark.asyncio
async def test_slow_operation_changes_to_waiting_without_canceling_work():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.dispatch_emote = AsyncMock()

    async def slow_operation():
        await asyncio.sleep(0.02)
        return "finished"

    result = await orchestrator._await_with_progress(slow_operation(), 0.001, "WAITING")

    assert result == "finished"
    orchestrator.dispatch_emote.assert_awaited_once_with("WAITING")


@pytest.mark.asyncio
async def test_reminder_skill_async_execute():
    reminder = ReminderSkill()
    dispatcher = AsyncMock()
    reminder.set_dispatcher(dispatcher)

    # Test setting a timer for a very short duration (0.001 mins = 0.06 seconds)
    result = await reminder.async_execute({"message": "Test Stretch", "minutes": 0.001})
    assert result.success is True
    assert "Test Stretch" in result.output
    assert len(reminder.reminders) == 1

    # Wait for timer to fire
    await asyncio.sleep(0.1)

    # Verify dispatcher received broadcast calls (notification + emote)
    assert dispatcher.broadcast.call_count >= 2


def test_weather_skill_uses_requested_city_and_reports_unknown_location(monkeypatch):
    requested = []

    def fake_urlopen(request, timeout):
        requested.append((request.full_url, timeout))
        return SimpleNamespace(read=lambda size: b"New York: Clear, 20 C")

    monkeypatch.setattr("blob.skills.builtin.weather.urllib.request.urlopen", fake_urlopen)
    result = WeatherSkill().execute({"location": "New York"})

    assert result.success
    assert result.output.startswith("New York:")
    assert requested == [("https://wttr.in/New+York?format=3", 10)]

    monkeypatch.setattr("blob.skills.builtin.weather.urllib.request.urlopen",
                        lambda request, timeout: SimpleNamespace(read=lambda size: b"Unknown location"))
    assert not WeatherSkill().execute({"location": "NotARealCity"}).success


@pytest.mark.asyncio
async def test_screen_capture_skill():
    skill = ScreenCaptureSkill()

    mock_sampler = MagicMock()
    mock_sampler.get_active_window_title.return_value = "Test Terminal"
    mock_sampler.privacy_shield.is_capture_blocked.return_value = False
    mock_sampler.privacy_shield.monitor.get_active_window.return_value = SimpleNamespace(
        process_name="ptyxis", bbox=None)
    
    # Mock image capture returning a dummy PIL image or path
    mock_image = MagicMock()
    mock_sampler.capture = AsyncMock(return_value=mock_image)

    mock_ocr = MagicMock()
    mock_ocr.extract_text.return_value = "Hello World on Screen"

    skill.set_sampler(mock_sampler)
    skill.set_ocr(mock_ocr)

    result = await skill.async_execute({})
    assert result.success is True
    assert "Active Window: Terminal" in result.output
    assert "Hello World on Screen" in result.output


@pytest.mark.asyncio
async def test_screen_capture_masks_blob_terminal_and_keeps_visible_lesson():
    skill = ScreenCaptureSkill()
    sampler = MagicMock()
    sampler.get_active_window_title.return_value = "ProjectBlob - Terminal"
    sampler.privacy_shield.is_capture_blocked.return_value = False
    sampler.privacy_shield.monitor.get_active_window.return_value = SimpleNamespace(
        process_name="gnome-terminal-server", bbox=(0, 0, 30, 30))
    sampler.capture = AsyncMock(return_value=Image.new("RGB", (100, 60), "white"))
    seen_pixels = []

    def read_screen(image):
        seen_pixels.append(image.getpixel((5, 5)))
        if len(seen_pixels) == 1:
            return "Blob> Can u help me with whats on the screen\nBlob: Earlier reply\nBarkhausen Criterion"
        return "Barkhausen Criterion\n|Aβ| = 1"

    skill.set_sampler(sampler)
    skill.set_ocr(SimpleNamespace(extract_text=read_screen))

    result = await skill.async_execute({})

    assert result.success
    assert seen_pixels == [(255, 255, 255), (0, 0, 0)]
    assert "Barkhausen Criterion" in result.output
    assert "Blob>" not in result.output
    assert "ProjectBlob" not in result.output


@pytest.mark.asyncio
async def test_screen_capture_filters_chat_without_window_geometry():
    skill = ScreenCaptureSkill()
    sampler = MagicMock()
    sampler.get_active_window_title.return_value = "Terminal"
    sampler.privacy_shield.is_capture_blocked.return_value = False
    sampler.privacy_shield.monitor.get_active_window.return_value = None
    sampler.capture = AsyncMock(return_value=Image.new("RGB", (20, 20), "white"))
    skill.set_sampler(sampler)
    skill.set_ocr(SimpleNamespace(extract_text=lambda image:
        "Blob> Can u help me with whats on the screen\nBlob: Old answer\nBarkhausen Criterion"))

    result = await skill.async_execute({})

    assert result.success
    assert "Barkhausen Criterion" in result.output
    assert "Blob>" not in result.output
    assert "Blob: Old answer" not in result.output


@pytest.mark.asyncio
async def test_screen_capture_reports_when_only_chat_is_visible():
    skill = ScreenCaptureSkill()
    sampler = MagicMock()
    sampler.get_active_window_title.return_value = "Terminal"
    sampler.privacy_shield.is_capture_blocked.return_value = False
    sampler.privacy_shield.monitor.get_active_window.return_value = None
    sampler.capture = AsyncMock(return_value=Image.new("RGB", (20, 20), "white"))
    skill.set_sampler(sampler)
    skill.set_ocr(SimpleNamespace(extract_text=lambda image: "Blob> What's on my screen?"))

    result = await skill.async_execute({})

    assert not result.success
    assert "Move it aside" in result.output


@pytest.mark.asyncio
async def test_screen_help_sends_cleaned_ocr_to_model():
    sampler = MagicMock()
    sampler.get_active_window_title.return_value = "ProjectBlob - Terminal"
    sampler.privacy_shield.is_capture_blocked.return_value = False
    sampler.privacy_shield.monitor.get_active_window.return_value = None
    sampler.capture = AsyncMock(return_value=Image.new("RGB", (20, 20), "white"))
    screen = ScreenCaptureSkill()
    screen.set_sampler(sampler)
    screen.set_ocr(SimpleNamespace(extract_text=lambda image:
        "Blob> Can u help me with whats on the screen\nBarkhausen Criterion\n|Aβ| = 1"))
    registry = SkillRegistry()
    registry.register(screen)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.screen_sampler = sampler
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "Context"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(
        return_value=SimpleNamespace(content="The Barkhausen Criterion describes sustained oscillation.")))

    await orchestrator.handle_user_message(SimpleNamespace(
        text="Can u help me with whats on the screen"))

    observation = orchestrator.llm.generate_from_messages.call_args.args[0][-1]["content"]
    assert "Barkhausen Criterion" in observation
    assert "Blob>" not in observation
    assert "ProjectBlob" not in observation


@pytest.mark.asyncio
async def test_screen_capture_explains_missing_ocr_after_successful_capture():
    skill = ScreenCaptureSkill()
    sampler = MagicMock()
    sampler.privacy_shield.is_capture_blocked.return_value = False
    sampler.capture = AsyncMock(return_value=MagicMock())
    ocr = MagicMock()
    ocr.extract_text.return_value = "OCR is not available. Please install easyocr."
    skill.set_sampler(sampler)
    skill.set_ocr(ocr)

    result = await skill.async_execute({})

    assert not result.success
    assert "Screen capture succeeded" in result.output
    assert "backend_python[ocr]" in result.output


@pytest.mark.asyncio
async def test_screen_capture_does_not_guess_when_ocr_reads_nothing():
    skill = ScreenCaptureSkill()
    sampler = MagicMock()
    sampler.privacy_shield.is_capture_blocked.return_value = False
    sampler.capture = AsyncMock(return_value=MagicMock())
    skill.set_sampler(sampler)
    skill.set_ocr(SimpleNamespace(extract_text=lambda image: "(No readable text found)"))

    result = await skill.async_execute({})

    assert not result.success
    assert "couldn't read any text" in result.output


def test_file_search_reports_empty_query_and_no_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skill = FileSearchSkill()
    assert not skill.execute({"query": ""}).success
    missing = skill.execute({"query": "notes.pdf"})
    assert not missing.success
    assert "No files matching" in missing.output


@pytest.mark.asyncio
async def test_orchestrator_react_loop_tool_execution():
    config = MagicMock()
    config.nebius_api_key = "test_key"
    config.nebius_base_url = "http://test"
    config.model_name = "test_model"
    vector_store = MagicMock()
    event_dispatcher = AsyncMock()
    
    registry = SkillRegistry()
    reminder_skill = ReminderSkill()
    reminder_skill.set_dispatcher(event_dispatcher)
    registry.register(reminder_skill)

    orchestrator = BlobOrchestrator(
        config=config,
        vector_store=vector_store,
        skill_registry=registry,
        event_dispatcher=event_dispatcher
    )

    # Mock episodic & semantic memories
    orchestrator.episodic.recall_relevant = MagicMock(return_value=[])
    orchestrator.semantic.recall_facts = MagicMock(return_value=[])

    # Mock LLM engine
    orchestrator.llm = AsyncMock()

    # Step 1: LLM returns a tool call block
    msg1 = MagicMock()
    msg1.content = '```tool_call\n{"tool": "reminder", "args": {"message": "Water break", "minutes": 0.001}}\n```'

    orchestrator.llm.generate_from_messages.return_value = msg1

    user_msg = MagicMock()
    user_msg.text = "Remind me to drink water in 0.001 minutes"

    answer = await orchestrator.handle_user_message(user_msg)

    # The confirmed skill result is shown without a second model paraphrase.
    assert orchestrator.llm.generate_from_messages.call_count == 1
    assert "Reminder set" in answer
    assert any(
        call.args[0].HasField("emote") and
        call.args[0].emote.emote == blob_service_pb2.EmoteCommand.WORKING
        for call in event_dispatcher.broadcast.await_args_list
    )

    # Verify reminder was registered
    assert len(reminder_skill.reminders) == 1
    assert reminder_skill.reminders[0]["message"] == "Water break"


def test_tool_parser_accepts_xml_wrapper_and_reversed_json_keys():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)

    assert orchestrator._parse_tool_call(
        '<tool_call>\n{"args": {"location": "Delhi"}, "tool": "weather"}\n</tool_call>'
    ) == ("weather", {"location": "Delhi"})
    assert orchestrator._parse_tool_call(
        'Here is an example: ```tool_call\n{"tool": "reminder", "args": {"minutes": 5}}\n```'
    ) == (None, None)


@pytest.mark.asyncio
async def test_current_weather_uses_confirmed_tool_result_without_model_paraphrase():
    skill = SimpleNamespace(name="weather", description="Current weather", async_execute=AsyncMock(
        return_value=SkillResult("Bengaluru: Clear, 29 C", True, "HAPPY")))
    registry = SkillRegistry()
    registry.register(skill)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.screen_sampler = None
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "No relevant memories"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(return_value=SimpleNamespace(
        content='<tool_call>\n{"tool": "weather", "args": {}}\n</tool_call>')))

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="What's the weather right now?"))

    assert answer == "Bengaluru: Clear, 29 C"
    skill.async_execute.assert_awaited_once_with({})
    orchestrator.llm.generate_from_messages.assert_awaited_once()

    skill.async_execute.reset_mock()
    orchestrator.llm.generate_from_messages.return_value = SimpleNamespace(
        content='<tool_call>\n{"tool": "weather", "args": {"location": "Delhi"}}\n</tool_call>')
    await orchestrator.handle_user_message(SimpleNamespace(text="What's the weather in Mumbai right now?"))
    skill.async_execute.assert_awaited_once_with({"location": "Mumbai"})


@pytest.mark.asyncio
async def test_future_weather_request_does_not_get_current_conditions():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text)
    orchestrator.screen_sampler = None
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock())

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="What's the weather tomorrow?"))

    assert "don't have a forecast tool" in answer
    orchestrator.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_reminder_request_without_tool_call_does_not_claim_success():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = SkillRegistry()
    orchestrator.screen_sampler = None
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "No relevant memories"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(return_value=SimpleNamespace(
        content="I set your reminder for five minutes.")))

    # Model fallbacks still require a real receipt; the direct relative-timer
    # route is covered separately by test_natural_reminders.
    answer = await orchestrator._handle_text_message(SimpleNamespace(text="Remind me to stretch in five minutes"))

    assert answer.startswith("I haven't set a reminder")
    assert "I set your reminder" not in answer
    assert orchestrator.event_dispatcher.broadcast.call_args.args[0].notification.text == answer


def test_style_preference_is_recalled_for_unrelated_message():
    config = MagicMock(nebius_api_key="test", nebius_base_url="http://test", model_name="test")
    store = MagicMock(semantic_revision=0)
    orchestrator = BlobOrchestrator(config, store, SkillRegistry(), AsyncMock())
    orchestrator.episodic.recall_relevant = MagicMock(return_value=[])
    orchestrator.semantic.recall_facts = MagicMock(side_effect=[
        [],
        [{"text": "The user prefers a professional, less familiar tone."}],
        [],
        [],
        [{"text": "The user now prefers a casual tone."}],
    ])

    context = orchestrator._build_context("What is the weather?")

    assert "The user prefers a professional, less familiar tone." in context
    assert orchestrator.semantic.recall_facts.call_count == 2
    assert "professional" in orchestrator._build_context("Tell me a joke")
    assert orchestrator.semantic.recall_facts.call_count == 3

    store.semantic_revision += 1
    assert "casual" in orchestrator._build_context("Tell me a joke")
    assert orchestrator.semantic.recall_facts.call_count == 5


def test_memory_question_does_not_repeat_old_assistant_denial():
    config = MagicMock(nebius_api_key="test", nebius_base_url="http://test", model_name="test")
    orchestrator = BlobOrchestrator(config, MagicMock(), SkillRegistry(), AsyncMock())
    orchestrator.episodic.recall_relevant = MagicMock(return_value=[{
        "text": "User: Remember me\nBlob: I don't have persistent memory across sessions."
    }])
    orchestrator.semantic.recall_facts = MagicMock(return_value=[])

    context = orchestrator._build_context("Can you remember me?")

    assert "User: Remember me" in context
    assert "I don't have persistent memory" not in context


def test_old_assistant_reply_is_excluded_unless_user_asks_for_it():
    config = MagicMock(nebius_api_key="test", nebius_base_url="http://test", model_name="test")
    orchestrator = BlobOrchestrator(config, MagicMock(), SkillRegistry(), AsyncMock())
    orchestrator.episodic.recall_relevant = MagicMock(return_value=[{
        "text": "User: What day is it?\nBlob: Sunday."
    }])
    orchestrator.semantic.recall_facts = MagicMock(return_value=[])

    assert "Blob: Sunday" not in orchestrator._build_context("It's Tuesday.")
    assert "User: What day is it?" in orchestrator._build_context("It's Tuesday.")
    assert "Blob: Sunday" in orchestrator._build_context("What did you say earlier?")


def test_retrieved_episode_dates_user_words_without_grounding_old_blob_claim():
    config = MagicMock(nebius_api_key="test", nebius_base_url="http://test", model_name="test")
    orchestrator = BlobOrchestrator(config, MagicMock(), SkillRegistry(), AsyncMock())
    said_at = datetime.now(timezone.utc).timestamp()
    orchestrator.episodic.recall_relevant = MagicMock(return_value=[{
        "text": "User: What presentation?\nBlob: Your presentation is tomorrow.",
        "metadata": {"timestamp": said_at},
    }])
    orchestrator.semantic.recall_facts = MagicMock(return_value=[])
    orchestrator.semantic.recall_middle = MagicMock(return_value=[])

    context = orchestrator._build_context("Which presentation?")

    date = datetime.fromtimestamp(said_at).astimezone().date().isoformat()
    assert f"[User said this on {date}]" in context
    assert "Your presentation is tomorrow" not in context
    assert orchestrator._grounded_user_evidence == [("What presentation?", said_at)]


def test_newer_user_denial_overrides_older_grounded_fact_for_claim_check():
    config = MagicMock(nebius_api_key="test", nebius_base_url="http://test", model_name="test")
    orchestrator = BlobOrchestrator(config, MagicMock(), SkillRegistry(), AsyncMock())
    said_at = datetime.now(timezone.utc).timestamp()
    orchestrator.episodic.recall_relevant = MagicMock(return_value=[{
        "text": "User: I have no presentation.\nBlob: Got it.",
        "metadata": {"timestamp": said_at},
    }])
    orchestrator.semantic.recall_facts = MagicMock(return_value=[{
        "text": "I have a presentation tomorrow.",
        "metadata": {"grounded": True, "source_timestamp": said_at - 86400},
    }])
    orchestrator.semantic.recall_middle = MagicMock(return_value=[])

    orchestrator._build_context("Do I have a presentation?")

    assert orchestrator._grounded_user_evidence[0] == ("I have no presentation.", said_at)
    assert unsupported_personal_event_claim(
        "Your presentation is tomorrow.", orchestrator._grounded_user_evidence)


def test_stale_weekday_fact_is_excluded_from_prompt():
    config = MagicMock(nebius_api_key="test", nebius_base_url="http://test", model_name="test")
    orchestrator = BlobOrchestrator(config, MagicMock(), SkillRegistry(), AsyncMock())
    orchestrator.episodic.recall_relevant = MagicMock(return_value=[])
    orchestrator.semantic.recall_facts = MagicMock(return_value=[
        {"text": "The user says today is Sunday."},
        {"text": "The user prefers concise replies."},
    ])

    context = orchestrator._build_context("How are you?")

    assert "today is Sunday" not in context
    assert "prefers concise replies" in context


def test_middle_term_context_and_explicit_archive_recall():
    config = MagicMock(nebius_api_key="test", nebius_base_url="http://test", model_name="test")
    orchestrator = BlobOrchestrator(config, MagicMock(), SkillRegistry(), AsyncMock())
    orchestrator.episodic.recall_relevant = MagicMock(return_value=[])
    orchestrator.semantic.recall_facts = MagicMock(return_value=[])
    orchestrator.semantic.recall_middle = MagicMock(return_value=[{
        "text": "I have an exam tomorrow.",
        "metadata": {"source_timestamp": 1790700000.0, "expires_at": 1790800000.0},
    }])

    context = orchestrator._build_context("What exam do I have?")
    assert "Active middle-term user quote" in context
    assert "I have an exam tomorrow." in context
    assert orchestrator.episodic.recall_relevant.call_args.kwargs["min_timestamp"] is not None

    orchestrator._build_context("What did we discuss last month?")
    assert orchestrator.episodic.recall_relevant.call_args.kwargs["min_timestamp"] is None

    orchestrator._build_context("What did you say about my project?")
    assert orchestrator.episodic.recall_relevant.call_args.kwargs["search_full_episode"] is True


def test_profile_overview_lists_saved_facts_without_vector_search():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.screen_sampler = None
    orchestrator.last_screen_context = "No screen data captured yet."
    orchestrator.episodic = SimpleNamespace(recall_relevant=MagicMock())
    orchestrator.semantic = SimpleNamespace(
        list_facts=MagicMock(return_value=[{
            "text": "I like astronomy.", "metadata": {"grounded": True}}]),
        list_middle=MagicMock(return_value=[]),
        recall_facts=MagicMock(), recall_middle=MagicMock(),
    )
    orchestrator._get_style_facts = lambda: []

    context = orchestrator._build_context("What do you know about me?")

    assert "I like astronomy." in context
    orchestrator.semantic.list_facts.assert_called_once()
    orchestrator.semantic.recall_facts.assert_not_called()
    orchestrator.episodic.recall_relevant.assert_not_called()


@pytest.mark.asyncio
async def test_grounded_plan_question_keeps_actual_request_last():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = SkillRegistry()
    orchestrator.screen_sampler = None
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(recall_relevant=MagicMock(return_value=[]), add_episode=MagicMock())
    said_at = datetime.now(timezone.utc).timestamp()
    orchestrator.semantic = SimpleNamespace(
        recall_facts=MagicMock(return_value=[]),
        recall_middle=MagicMock(return_value=[{
            "text": "I booked a bike service for next week.",
            "metadata": {"source_timestamp": said_at, "expires_at": said_at + 7 * 86400},
        }]),
    )
    orchestrator._get_style_facts = lambda: []
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(
        return_value=SimpleNamespace(content="Yep, your bike service is next week.")))

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="Do I have any plans next week?"))

    messages = orchestrator.llm.generate_from_messages.call_args.args[0]
    assert "bike service" in messages[1]["content"]
    assert messages[-1] == {"role": "user", "content": "Do I have any plans next week?"}
    assert answer == "Yep, your bike service is next week."


@pytest.mark.asyncio
async def test_unsupported_presentation_claim_is_corrected_before_display_or_storage(capsys):
    async def false_reply(messages, system_prompt):
        yield "Yep, your presentation is tomorrow. <emote>HAPPY</emote>"

    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = SkillRegistry()
    orchestrator.screen_sampler = None
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "User: What presentation?\nBlob: Your presentation is tomorrow."
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages_stream=false_reply)

    answer = await orchestrator.handle_user_message(
        SimpleNamespace(text="Which presentation? I have no presentation."))

    assert answer == "I don't have evidence for that plan. I shouldn't have stated it as fact."
    assert "your presentation is tomorrow" not in capsys.readouterr().out.lower()
    orchestrator.episodic.add_episode.assert_called_once_with(
        "Which presentation? I have no presentation.", answer)
    assert orchestrator.event_dispatcher.broadcast.call_args.args[0].notification.text == answer


@pytest.mark.asyncio
async def test_chat_prompt_is_bounded_before_model_call():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = SkillRegistry()
    orchestrator.screen_sampler = None
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "old fact\n" * 1000
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator._max_prompt_bytes = 400
    orchestrator._recent_turns = [
        {"role": "user", "content": "old question " * 30},
        {"role": "assistant", "content": "old answer " * 30},
    ]
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(
        return_value=SimpleNamespace(content="Here's a brief answer.")))

    await orchestrator.handle_user_message(SimpleNamespace(text="Tell me briefly."))

    messages = orchestrator.llm.generate_from_messages.call_args.args[0]
    assert prompt_size_bytes(messages) <= 400
    assert messages[-1] == {"role": "user", "content": "Tell me briefly."}
    assert all("old question" not in item["content"] for item in messages)


@pytest.mark.asyncio
async def test_oversized_latest_request_is_not_sent_or_saved():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = SkillRegistry()
    orchestrator.screen_sampler = None
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "No relevant memories"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator._max_prompt_bytes = 300
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock())

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="x" * 1000))

    assert "Please narrow or split" in answer
    orchestrator.llm.generate_from_messages.assert_not_awaited()
    orchestrator.episodic.add_episode.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("user_text", "emote", "answer"), [
    ("Can you make melting face?", "MELTING", "Here's my melting face."),
    ("Can you make sad face?", "SAD", "Here's my sad face."),
    ("What about a happy face", "HAPPY", "Here's my happy face."),
    ("Show me your happy expression!", "HAPPY", "Here's my happy face."),
    ("Could you make a sad face for me, please?", "SAD", "Here's my sad face."),
    ("do a melting emotion blobby", "MELTING", "Here's my melting face."),
    ("Show me your melting animation again, Blob!", "MELTING", "Here's my melting face."),
    ("make an angry expression", "ANGRY", "Here's my angry face."),
    ("show your deep thinking mood", "DEEP_THINKING", "Here's my deep thinking face."),
    ("Do a melted emotion, blobby, please!", "MELTING", "Here's my melting face."),
])
async def test_face_request_uses_visible_emote_without_model(tmp_path, user_text, emote, answer):
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text)
    orchestrator.screen_sampler = None
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock())
    orchestrator.controls = PrivacyControls(tmp_path / "privacy.json")
    orchestrator.controls.state["cloud_enabled"] = False
    orchestrator._active_attachments = ["previous-lesson.pdf"]
    orchestrator._handle_attachment_message = AsyncMock(side_effect=AssertionError("Emotion request reached attachment analysis"))

    result = await orchestrator.handle_user_message(SimpleNamespace(text=user_text))

    events = [call.args[0] for call in orchestrator.event_dispatcher.broadcast.call_args_list]
    assert result == answer
    assert len(events) == 2
    assert events[0].emote.emote == getattr(blob_service_pb2.EmoteCommand, emote)
    assert events[1].notification.text == answer
    orchestrator.llm.generate_from_messages.assert_not_awaited()
    orchestrator._handle_attachment_message.assert_not_awaited()
    orchestrator.episodic.add_episode.assert_called_once_with(user_text, answer)
    assert list(orchestrator._recent_turns)[-2:] == [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": answer},
    ]


@pytest.mark.parametrize("user_text", [
    "Why not?",
    "What does a sad face mean?",
    "Can you make a happy face in CSS?",
    "Make a sad face and set a timer",
    "Draw a melting emotion blobby in ASCII",
    "Show me a melting animation in Python",
    "Don't do a melting emotion blobby",
    "What is a melting emotion?",
])
def test_face_request_does_not_hijack_other_tasks(user_text):
    assert _requested_face(user_text) is None


@pytest.mark.asyncio
async def test_day_only_request_uses_local_clock_without_memory_or_model(monkeypatch):
    class FixedClock:
        @staticmethod
        def now():
            return datetime(2026, 9, 29, 10, 25, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    monkeypatch.setattr("blob.ai.orchestrator.datetime", FixedClock)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text)
    orchestrator.screen_sampler = None
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock())
    orchestrator.skill_registry = SkillRegistry()

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="Man just the day"))

    assert answer == "Tuesday."
    assert "Tuesday, 2026-09-29" in orchestrator._build_system_prompt()
    orchestrator.llm.generate_from_messages.assert_not_awaited()
    orchestrator.episodic.add_episode.assert_called_once_with("Man just the day", "Tuesday.")


@pytest.mark.asyncio
async def test_correction_sees_recent_turns_after_historical_memory():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = SkillRegistry()
    orchestrator.screen_sampler = None
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "User: What day is it?\nBlob: Sunday."
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(side_effect=[
        SimpleNamespace(content="Sunday. <emote>IDLE</emote>"),
        SimpleNamespace(content="You're right, it's Tuesday. <emote>CONFUSED</emote>"),
    ]))

    await orchestrator.handle_user_message(SimpleNamespace(text="How's it going?"))
    answer = await orchestrator.handle_user_message(SimpleNamespace(text="It's not. It's Tuesday."))

    messages = orchestrator.llm.generate_from_messages.call_args.args[0]
    assert "Historical background" in messages[1]["content"]
    assert messages[-3:] == [
        {"role": "user", "content": "How's it going?"},
        {"role": "assistant", "content": "Sunday."},
        {"role": "user", "content": "It's not. It's Tuesday."},
    ]
    assert answer == "You're right, it's Tuesday."


@pytest.mark.asyncio
async def test_streamed_reasoning_and_partial_control_tags_stay_hidden(capsys):
    async def reply_stream(messages, system_prompt):
        for part in (
            "<thinking>Old memory says Sunday. ",
            "The user corrected it.</thinking>",
            "You're right. It's Tuesday. Thanks for catching that. ",
            "<emot", "e>CONFUSED</emote>",
        ):
            yield part

    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = SkillRegistry()
    orchestrator.screen_sampler = None
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "Old memory"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages_stream=reply_stream)

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="It's Tuesday."))

    output = capsys.readouterr().out
    assert answer == "You're right. It's Tuesday. Thanks for catching that."
    assert "Old memory says Sunday" not in output
    assert "<thinking>" not in output
    assert "<emot" not in output
    assert output.count("You're right.") == 1
    orchestrator.episodic.add_episode.assert_called_once_with("It's Tuesday.", answer)


def test_emote_markers_are_removed_from_chat_text():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    assert orchestrator._extract_emote("Hello (HAPPY)") == ("HAPPY", "Hello")
    assert orchestrator._extract_emote("Oh no (SAD) <emote>WORRIED</emote>") == ("WORRIED", "Oh no")


@pytest.mark.asyncio
async def test_streamed_reply_previews_text_without_emote_or_tool_block(capsys):
    async def plain_stream(messages, system_prompt):
        for part in ("Hello, ", "I remember your project. ", "<emote>HAPPY</emote>"):
            yield part

    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.llm = SimpleNamespace(generate_from_messages_stream=plain_stream)
    response, preview = await orchestrator._generate_with_preview([], "System")
    output = capsys.readouterr().out
    assert response.endswith("<emote>HAPPY</emote>")
    assert "Hello" in output
    assert "<emote>" not in output
    assert preview in response

    async def tool_stream(messages, system_prompt):
        for part in ("`", "``tool_call\n", '{"tool":"reminder","args":{}}', "\n```"):
            yield part

    orchestrator.llm = SimpleNamespace(generate_from_messages_stream=tool_stream)
    response, preview = await orchestrator._generate_with_preview([], "System")
    assert '"reminder"' in response
    assert preview == ""
    assert capsys.readouterr().out == ""

    async def xml_tool_stream(messages, system_prompt):
        for part in ("<tool", '_call>\n{"tool":"weather","args":{}}', "\n</tool_call>"):
            yield part

    orchestrator.llm = SimpleNamespace(generate_from_messages_stream=xml_tool_stream)
    response, preview = await orchestrator._generate_with_preview([], "System")
    assert '"weather"' in response
    assert preview == ""
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_streaming_failure_falls_back_to_normal_response():
    async def broken_stream(messages, system_prompt):
        raise RuntimeError("streaming disabled")
        yield ""

    normal = AsyncMock(return_value=SimpleNamespace(content="Hello."))
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.llm = SimpleNamespace(
        generate_from_messages_stream=broken_stream,
        generate_from_messages=normal,
    )

    assert await orchestrator._generate_with_preview([], "System") == ("Hello.", "")
    assert orchestrator._streaming_disabled is True
    assert await orchestrator._generate_with_preview([], "System") == ("Hello.", "")
    assert normal.await_count == 2


@pytest.mark.asyncio
async def test_streamed_reply_is_not_printed_twice_after_wrapping(capsys):
    async def reply_stream(messages, system_prompt):
        yield "Midterms gonna midterm, but you're doing solid keeping it together! 🌟 "
        yield "If you want me to ping you before that Wednesday lab exam, just say the word."
        yield " <emote>HAPPY</emote>"

    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = SkillRegistry()
    orchestrator.screen_sampler = None
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "Context"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages_stream=reply_stream)

    response = await orchestrator.handle_user_message(SimpleNamespace(text="Midterms are hectic"))

    output = capsys.readouterr().out
    assert output.count("Blob:") == 1
    assert output.count("Midterms gonna midterm") == 1
    assert output.count("Wednesday lab exam") == 1
    assert "<emote>" not in output
    assert response.endswith("just say the word.")


@pytest.mark.asyncio
async def test_nebius_message_stream_yields_text_chunks():
    async def chunks():
        for content in ("Hello", None, " there"):
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])

    create = AsyncMock(return_value=chunks())
    engine = NebiusEngine.__new__(NebiusEngine)
    engine.model_name = "test-model"
    engine.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    result = [part async for part in engine.generate_from_messages_stream([{"role": "user", "content": "Hi"}], "System")]

    assert result == ["Hello", " there"]
    create.assert_awaited_once_with(
        model="test-model",
        messages=[{"role": "system", "content": "System"}, {"role": "user", "content": "Hi"}],
        stream=True,
    )


@pytest.mark.asyncio
async def test_lightning_chat_skips_hidden_thinking_without_changing_memory_generation():
    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Hello"))])
    create = AsyncMock(return_value=reply)
    engine = NebiusEngine.__new__(NebiusEngine)
    engine.model_name = "nvidia/Nemotron-3_5-Lightning"
    engine.chat_thinking_enabled = False
    engine.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    await engine.generate_from_messages([{"role": "user", "content": "Hi"}], "System")
    await engine.generate("Summarize", "", "Memory extractor")

    assert create.await_args_list[0].kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}}
    assert "extra_body" not in create.await_args_list[1].kwargs
    engine.chat_thinking_enabled = True
    assert engine._chat_kwargs() == {}


@pytest.mark.asyncio
async def test_screen_question_captures_before_model_answer(capsys):
    screen = SimpleNamespace(async_execute=AsyncMock(return_value=SkillResult(
        "Active Window: Notes\n\nExtracted Screen Text:\nProject plan", True, "THINKING")))
    registry = SkillRegistry()
    registry.register(SimpleNamespace(name="screen_capture", description="Capture screen", async_execute=screen.async_execute))
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(is_capture_blocked=lambda: False))
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "Context"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(
        return_value=SimpleNamespace(content="Your Notes window shows a project plan. (HAPPY)")))

    for request in ("What is happening on my screen?", "Can I share my screen?", "/screen",
                    "What does this thing on my screen even mean. Help me understand it"):
        answer = await orchestrator.handle_user_message(SimpleNamespace(text=request))

    assert screen.async_execute.await_count == 4
    screen.async_execute.assert_awaited_with({})
    messages = orchestrator.llm.generate_from_messages.call_args.args[0]
    assert "Project plan" in messages[-1]["content"]
    assert answer == "Your Notes window shows a project plan."
    assert orchestrator.event_dispatcher.broadcast.call_args.args[0].notification.text == answer
    orchestrator.dispatch_emote.assert_any_await("HAPPY")
    assert "(HAPPY)" not in capsys.readouterr().out


def test_screen_followup_understands_go_ahead_without_ignoring_real_denial():
    previous = [{"role": "user", "content":
                 "What does this thing on my screen even mean. Help me understand it"},
                {"role": "assistant", "content": "Could you describe your screen?"}]

    assert _wants_screen_capture("You do not need my permission to capture, just do it", previous)
    assert _wants_screen_capture("Go ahead", previous)
    assert not _wants_screen_capture("Do not capture my screen", previous)
    assert not _wants_screen_capture("Don't do it", previous)
    assert not _wants_screen_capture("I don't need you to capture my screen", previous)
    assert not _wants_screen_capture("How do I capture my screen?", previous)
    assert not _wants_screen_capture("Why can't you capture my screen?", previous)
    assert not _wants_screen_capture("Just do it", [])


@pytest.mark.asyncio
async def test_screen_go_ahead_after_old_permission_reply_captures():
    screen = SimpleNamespace(name="screen_capture", description="Capture screen", async_execute=AsyncMock(
        return_value=SkillResult("Active Window: Notes\n\nExtracted Screen Text:\nVoltage divider", True)))
    registry = SkillRegistry()
    registry.register(screen)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(is_capture_blocked=lambda: False))
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "Context"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator._recent_turns = [
        {"role": "user", "content": "What does this thing on my screen even mean?"},
        {"role": "assistant", "content": "I need permission before I capture it."},
    ]
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(
        return_value=SimpleNamespace(content="A voltage divider reduces the input voltage.")))

    answer = await orchestrator.handle_user_message(SimpleNamespace(
        text="You do not need my permission to capture, just do it"))

    screen.async_execute.assert_awaited_once_with({})
    assert "voltage divider" in answer.lower()
    assert "Voltage divider" in orchestrator.llm.generate_from_messages.call_args.args[0][-1]["content"]


@pytest.mark.asyncio
async def test_successful_capture_retries_false_permission_denial():
    screen = SimpleNamespace(name="screen_capture", description="Capture screen", async_execute=AsyncMock(
        return_value=SkillResult("Active Window: Notes\n\nExtracted Screen Text:\nVoltage divider", True)))
    registry = SkillRegistry()
    registry.register(screen)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(is_capture_blocked=lambda: False))
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "Context"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(side_effect=[
        SimpleNamespace(content="I can't capture the screen without your permission."),
        SimpleNamespace(content="A voltage divider splits voltage across two resistors."),
    ]))

    answer = await orchestrator.handle_user_message(SimpleNamespace(
        text="What does this thing on my screen even mean?"))

    screen.async_execute.assert_awaited_once_with({})
    assert orchestrator.llm.generate_from_messages.await_count == 2
    assert "splits voltage" in answer
    assert "permission" not in answer.lower()


@pytest.mark.asyncio
async def test_study_screen_request_uses_ocr_and_rejects_unrequested_file_search():
    request = "Please help me understand the lesson on my screen"
    assert SCREEN_REQUEST.search(request)
    screen = SimpleNamespace(name="screen_capture", description="Capture screen", async_execute=AsyncMock(
        return_value=SkillResult("Active Window: Practice notes\n\nExtracted Screen Text:\nVoltage divider\nFind Vout for Vin=12 V, R1=2 kΩ, R2=2 kΩ", True, "THINKING")))
    files = SimpleNamespace(name="file_search", description="Find files", async_execute=AsyncMock(
        return_value=SkillResult("No files found", False)))
    registry = SkillRegistry()
    registry.register(screen)
    registry.register(files)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(is_capture_blocked=lambda: False))
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "Context"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(side_effect=[
        SimpleNamespace(content='```tool_call\n{"tool":"file_search","args":{"query":"voltage divider"}}\n```'),
        SimpleNamespace(content="Using Vout = Vin × R2/(R1 + R2), the result is 6 V. <emote>HAPPY</emote>"),
    ]))

    answer = await orchestrator.handle_user_message(SimpleNamespace(text=request))

    screen.async_execute.assert_awaited_once_with({})
    files.async_execute.assert_not_awaited()
    assert "6 V" in answer
    assert "file" not in answer.casefold()
    assert orchestrator.llm.generate_from_messages.await_count == 2
    observation = orchestrator.llm.generate_from_messages.call_args.args[0][-3]["content"]
    assert "work through it" in observation
    assert "Find Vout" in observation


@pytest.mark.asyncio
async def test_screen_answer_cannot_claim_a_file_search_that_did_not_happen():
    screen = SimpleNamespace(name="screen_capture", description="Capture screen", async_execute=AsyncMock(
        return_value=SkillResult("Active Window: Practice notes\n\nExtracted Screen Text:\nVoltage divider", True)))
    registry = SkillRegistry()
    registry.register(screen)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(is_capture_blocked=lambda: False))
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "Context"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(side_effect=[
        SimpleNamespace(content="The file isn't showing up in the search."),
        SimpleNamespace(content="A voltage divider uses two resistors to take a fraction of the input voltage. Which step is confusing?"),
    ]))

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="Help me with what's on my screen"))

    assert "voltage divider" in answer
    assert "file" not in answer.casefold()
    assert orchestrator.llm.generate_from_messages.await_count == 2


@pytest.mark.asyncio
async def test_old_screen_text_is_not_reused_on_next_message():
    screen = SimpleNamespace(name="screen_capture", description="Capture screen", async_execute=AsyncMock(
        return_value=SkillResult("Active Window: Notes\n\nExtracted Screen Text:\nCircuit diagram", True)))
    registry = SkillRegistry()
    registry.register(screen)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(is_capture_blocked=lambda: False))
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: orchestrator.last_screen_context
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(return_value=SimpleNamespace(content="Okay.")))

    await orchestrator.handle_user_message(SimpleNamespace(text="Look at my screen"))
    await orchestrator.handle_user_message(SimpleNamespace(text="Hi"))

    second_context = orchestrator.llm.generate_from_messages.await_args.args[0][1]["content"]
    assert "Circuit diagram" not in second_context
    assert "No fresh screen capture" in second_context


@pytest.mark.asyncio
async def test_screen_capture_failure_is_reported_without_model_guessing():
    screen = SimpleNamespace(name="screen_capture", async_execute=AsyncMock(
        return_value=SkillResult("Screen capture is blocked by the privacy shield.", False, "WORRIED")))
    registry = SkillRegistry()
    registry.register(screen)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock())

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="Look at my screen"))

    assert "privacy shield" in answer
    orchestrator.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_remember_me_uses_local_memory_instead_of_model_denial():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text)
    orchestrator.screen_sampler = None
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(
        return_value=SimpleNamespace(content="I don't have persistent memory.")))

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="Will you remember me tomorrow?"))

    assert "across restarts" in answer
    orchestrator.episodic.add_episode.assert_called_once_with("Will you remember me tomorrow?", answer)
    orchestrator.llm.generate_from_messages.assert_not_awaited()
    assert orchestrator.event_dispatcher.broadcast.call_args.args[0].notification.text == answer


@pytest.mark.asyncio
async def test_remember_me_saves_while_screen_privacy_shield_is_active():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text)
    orchestrator.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(is_capture_blocked=lambda: True))
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="Remember me"))

    assert "persistent local memory" in answer
    orchestrator.episodic.add_episode.assert_called_once_with("Remember me", answer)


@pytest.mark.asyncio
async def test_false_memory_denial_from_model_is_corrected():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(
        sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = SkillRegistry()
    orchestrator.screen_sampler = None
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "Context"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(return_value=SimpleNamespace(
        content="I don't have persistent memory that survives across sessions. <emote>SAD</emote>")))

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="Can you remember things about me?"))

    assert "across restarts" in answer
    assert "don't have" not in answer
    assert orchestrator.event_dispatcher.broadcast.call_args.args[0].notification.text == answer
    orchestrator.episodic.add_episode.assert_called_once_with("Can you remember things about me?", answer)
