import sys
from unittest.mock import MagicMock

# Create a mock for blob_service_pb2
mock_pb2 = MagicMock()
mock_pb2.EmoteCommand.IDLE = 0
mock_pb2.EmoteCommand.HAPPY = 1
mock_pb2.EmoteCommand.WORRIED = 12
mock_pb2.EmoteCommand.CONFUSED = 10
mock_pb2.EmoteCommand.THINKING = 4
mock_pb2.EmoteCommand.CELEBRATE = 6
mock_pb2.EmoteCommand.TIRED = 2
mock_pb2.EmoteCommand.EXCITED = 3

sys.modules['blob.ipc.blob_service_pb2'] = mock_pb2
sys.modules['blob.ipc'] = MagicMock(blob_service_pb2=mock_pb2)

# Mock other external dependencies
for mod in ["openai", "chromadb", "pydantic", "yaml", "PIL", "dbus_next", "easyocr"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

import asyncio
from unittest.mock import AsyncMock
from blob.skills.base import SkillResult
from blob.skills.builtin.reminder import ReminderSkill
from blob.skills.builtin.screen_capture import ScreenCaptureSkill
from blob.skills.registry import SkillRegistry
from blob.ai.orchestrator import BlobOrchestrator


async def test_reminder_skill_async_execute():
    print("Testing ReminderSkill async_execute...")
    reminder = ReminderSkill()
    dispatcher = AsyncMock()
    reminder.set_dispatcher(dispatcher)

    result = await reminder.async_execute({"message": "Test Stretch", "minutes": 0.001})
    assert result.success is True, f"Expected success True, got {result.success}"
    assert "Test Stretch" in result.output, f"Expected message in output: {result.output}"
    assert len(reminder.reminders) == 1

    await asyncio.sleep(0.1)
    assert dispatcher.broadcast.call_count >= 2, f"Expected >=2 broadcasts, got {dispatcher.broadcast.call_count}"
    print("  PASSED ✅")


async def test_screen_capture_skill():
    print("Testing ScreenCaptureSkill...")
    skill = ScreenCaptureSkill()

    mock_sampler = MagicMock()
    mock_sampler.get_active_window_title.return_value = "Test Terminal"
    mock_sampler.privacy_shield.is_capture_blocked.return_value = False
    
    mock_image = MagicMock()
    mock_sampler.capture = AsyncMock(return_value=mock_image)

    mock_ocr = MagicMock()
    mock_ocr.extract_text.return_value = "Hello World on Screen"

    skill.set_sampler(mock_sampler)
    skill.set_ocr(mock_ocr)

    result = await skill.async_execute({})
    assert result.success is True, f"Expected success True, got {result.success}"
    assert "Test Terminal" in result.output, f"Window title missing: {result.output}"
    assert "Hello World on Screen" in result.output, f"OCR text missing: {result.output}"
    print("  PASSED ✅")


async def test_orchestrator_react_loop_tool_execution():
    print("Testing Orchestrator ReAct Loop...")
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

    orchestrator.episodic.recall_relevant = MagicMock(return_value=[])
    orchestrator.semantic.recall_facts = MagicMock(return_value=[])

    orchestrator.llm = AsyncMock()

    msg1 = MagicMock()
    msg1.content = '```tool_call\n{"tool": "reminder", "args": {"message": "Water break", "minutes": 0.001}}\n```'

    orchestrator.llm.generate_from_messages.return_value = msg1

    user_msg = MagicMock()
    user_msg.text = "Remind me to drink water in 0.001 minutes"

    await orchestrator.handle_user_message(user_msg)

    assert orchestrator.llm.generate_from_messages.call_count == 1, f"Expected 1 LLM call, got {orchestrator.llm.generate_from_messages.call_count}"
    assert len(reminder_skill.reminders) == 1, f"Expected 1 reminder registered, got {len(reminder_skill.reminders)}"
    assert reminder_skill.reminders[0]["message"] == "Water break"
    print("  PASSED ✅")


async def main():
    try:
        await test_reminder_skill_async_execute()
        await test_screen_capture_skill()
        await test_orchestrator_react_loop_tool_execution()
        print("\n🎉 ALL UNIT TESTS PASSED SUCCESSFULLY!")
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
