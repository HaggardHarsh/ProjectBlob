import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from blob.skills.base import SkillResult
from blob.skills.builtin.reminder import ReminderSkill
from blob.skills.builtin.screen_capture import ScreenCaptureSkill
from blob.skills.registry import SkillRegistry
from blob.ai.orchestrator import BlobOrchestrator


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
    orchestrator = BlobOrchestrator(config, MagicMock(), SkillRegistry(), AsyncMock())
    orchestrator.episodic.recall_relevant = MagicMock(return_value=[])
    orchestrator.semantic.recall_facts = MagicMock(side_effect=[
        [],
        [{"text": "The user prefers a professional, less familiar tone."}],
    ])

    context = orchestrator._build_context("What is the weather?")

    assert "The user prefers a professional, less familiar tone." in context
    assert orchestrator.semantic.recall_facts.call_count == 2
