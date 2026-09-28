import asyncio
from types import SimpleNamespace
import pytest
from unittest.mock import AsyncMock, MagicMock
from blob.skills.base import SkillResult
from blob.skills.builtin.reminder import ReminderSkill
from blob.skills.builtin.screen_capture import ScreenCaptureSkill
from blob.skills.registry import SkillRegistry
from blob.ai.orchestrator import BlobOrchestrator
from blob.ai.llm_engine import NebiusEngine


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


@pytest.mark.asyncio
async def test_screen_capture_skill():
    skill = ScreenCaptureSkill()

    mock_sampler = MagicMock()
    mock_sampler.get_active_window_title.return_value = "Test Terminal"
    mock_sampler.privacy_shield.is_capture_blocked.return_value = False
    
    # Mock image capture returning a dummy PIL image or path
    mock_image = MagicMock()
    mock_sampler.capture = AsyncMock(return_value=mock_image)

    mock_ocr = MagicMock()
    mock_ocr.extract_text.return_value = "Hello World on Screen"

    skill.set_sampler(mock_sampler)
    skill.set_ocr(mock_ocr)

    result = await skill.async_execute({})
    assert result.success is True
    assert "Test Terminal" in result.output
    assert "Hello World on Screen" in result.output


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

    # Step 2: LLM returns final response after seeing tool observation
    msg2 = MagicMock()
    msg2.content = "I have set a reminder for your water break! <emote>HAPPY</emote>"

    orchestrator.llm.generate_from_messages.side_effect = [msg1, msg2]

    user_msg = MagicMock()
    user_msg.text = "Remind me to drink water in 0.001 minutes"

    await orchestrator.handle_user_message(user_msg)

    # Verify LLM was called twice (tool call iteration + final response iteration)
    assert orchestrator.llm.generate_from_messages.call_count == 2

    # Verify reminder was registered
    assert len(reminder_skill.reminders) == 1
    assert reminder_skill.reminders[0]["message"] == "Water break"


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

    for request in ("What is happening on my screen?", "Can I share my screen?", "/screen"):
        answer = await orchestrator.handle_user_message(SimpleNamespace(text=request))

    assert screen.async_execute.await_count == 3
    screen.async_execute.assert_awaited_with({})
    messages = orchestrator.llm.generate_from_messages.call_args.args[0]
    assert "Project plan" in messages[-1]["content"]
    assert answer == "Your Notes window shows a project plan."
    assert orchestrator.event_dispatcher.broadcast.call_args.args[0].notification.text == answer
    orchestrator.dispatch_emote.assert_any_await("HAPPY")
    assert "(HAPPY)" not in capsys.readouterr().out


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
async def test_remember_me_reports_when_privacy_shield_pauses_storage():
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text)
    orchestrator.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(is_capture_blocked=lambda: True))
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="Remember me"))

    assert "privacy shield" in answer
    orchestrator.episodic.add_episode.assert_not_called()


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
