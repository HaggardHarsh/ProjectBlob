"""Model routes must receive the task's recent conversation within their budget."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image
import pytest

from blob.ai.attachments import AttachmentReader
from blob.ai.context_budget import prompt_size_bytes
from blob.ai.prompt_templates import CONVERSATION_CONTINUITY, SYSTEM_PROMPT
from blob.ipc import blob_service_pb2 as pb
from blob.skills.registry import SkillRegistry
from test_attachments import orchestrator, text_pdf


def assistant(tmp_path):
    blob = orchestrator()
    blob.config.documents_dir_path = tmp_path / "documents"
    blob.config.memory_db_path = str(tmp_path / "memory")
    blob.screen_sampler = None
    blob.skill_registry = SkillRegistry(tmp_path / "skills")
    blob._build_context = lambda text: "Old memory\n" * 4000
    blob._build_system_prompt = lambda: SYSTEM_PROMPT.replace("{skills}", "No tools available.")
    # Continuity checks need pixels and PDF text, not a real OCR model.
    blob._attachment_reader = AttachmentReader(ocr=SimpleNamespace(extract_text=lambda image: ""))
    return blob


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_chat_to_vision_and_back_preserves_task_and_corrections(tmp_path, native):
    blob = assistant(tmp_path)
    blob._max_prompt_bytes = 16000
    chat = blob.llm.generate_from_messages
    if native:
        chat = AsyncMock()
        blob.agent_runtime = SimpleNamespace(run=chat)
    draft = "Subject: Extension request\nDear Professor, could I have two more days?"
    chat.return_value = draft if native else SimpleNamespace(content=draft)
    request = "Draft an email asking my professor for two more days. Keep it friendly."
    await blob.handle_user_message(pb.UserMessage(text=request))

    image = tmp_path / "instructions.png"
    Image.new("RGB", (16, 16), "blue").save(image)
    revised = "Subject: Extension request\nDear Professor, could I have until Friday?"
    vision = SimpleNamespace(generate_from_messages=AsyncMock(
        return_value=SimpleNamespace(content=revised)))
    blob.llm.vision_engine.return_value = vision
    correction = "Use the attached image to revise the draft. Ask for Friday instead."
    await blob.handle_user_message(pb.UserMessage(text=correction, attachments=[str(image)]))
    messages, system = vision.generate_from_messages.call_args.args
    assert {"role": "user", "content": request} in messages
    assert {"role": "assistant", "content": draft} in messages
    assert CONVERSATION_CONTINUITY in system
    assert prompt_size_bytes(messages) <= blob._max_prompt_bytes

    chat.return_value = "A friendlier draft." if native else SimpleNamespace(content="A friendlier draft.")
    await blob.handle_user_message(pb.UserMessage(text="Draft a friendlier email with the same deadline."))
    messages, system = chat.call_args.args[:2]
    assert any(item["role"] == "user" and correction in item["content"] for item in messages)
    assert {"role": "assistant", "content": revised} in messages
    assert CONVERSATION_CONTINUITY in system
    assert prompt_size_bytes(messages) <= blob._max_prompt_bytes


@pytest.mark.asyncio
@pytest.mark.parametrize("max_bytes, repeats", [(12000, 150), (18000, 350)])
async def test_dense_pdf_reserves_room_for_previous_task(tmp_path, max_bytes, repeats):
    blob = assistant(tmp_path)
    blob._max_prompt_bytes = max_bytes
    question = "Explain this lesson using short examples and a friendly tone."
    answer = "Here is the previous draft. " * repeats
    blob._remember_recent_turn(question, answer)
    path = tmp_path / "lesson.pdf"
    # A wide text layer keeps the full source readable, rather than clipping
    # the repeated sentence at the edge of a tiny fixture page.
    text_pdf(path, ["Voltage equals current times resistance. " * 100] * 4,
             page_width=40000)
    await blob.handle_user_message(pb.UserMessage(text="Explain the attached PDF the same way.", attachments=[str(path)]))
    messages, _ = blob.llm.generate_from_messages.call_args.args
    assert {"role": "user", "content": question} in messages
    assert {"role": "assistant", "content": answer} in messages
    assert "lesson.pdf, page 1" in messages[-1]["content"]
    assert "[Excerpt; other text omitted]" in messages[-1]["content"]
    assert prompt_size_bytes(messages) <= blob._max_prompt_bytes


@pytest.mark.asyncio
async def test_long_draft_keeps_image_pixels_instead_of_falling_back_to_ocr(tmp_path):
    blob = assistant(tmp_path)
    blob._max_prompt_bytes = 16000
    question = "Keep this friendly draft and its Friday deadline."
    answer = "Here is the previous draft. " * 280
    blob._remember_recent_turn(question, answer)
    image = tmp_path / "instructions.png"
    Image.new("RGB", (16, 16), "blue").save(image)
    vision = SimpleNamespace(generate_from_messages=AsyncMock(
        return_value=SimpleNamespace(content="A revised draft.")))
    blob.llm.vision_engine.return_value = vision

    reply = await blob.handle_user_message(pb.UserMessage(
        text="Revise the draft using this picture.", attachments=[str(image)]))

    assert reply == "A revised draft."
    messages, _ = vision.generate_from_messages.call_args.args
    assert {"role": "user", "content": question} in messages
    assert {"role": "assistant", "content": answer} in messages
    assert any(part["type"] == "image_url" for part in messages[-1]["content"])
    assert prompt_size_bytes(messages) <= blob._max_prompt_bytes


@pytest.mark.asyncio
async def test_vision_fallback_keeps_task_and_pixels(tmp_path):
    blob = assistant(tmp_path)
    blob.config.vision_fallback_model_name = "backup-vision"
    blob._max_prompt_bytes = 16000
    request = "Draft a friendly email asking for an extension until Friday."
    draft = "Dear Professor, could I have until Friday?"
    blob._remember_recent_turn(request, draft)
    image = tmp_path / "instructions.png"
    Image.new("RGB", (16, 16), "blue").save(image)
    primary = SimpleNamespace(model_name="primary-vision",
        generate_from_messages=AsyncMock(side_effect=asyncio.TimeoutError))
    backup = SimpleNamespace(model_name="backup-vision",
        generate_from_messages=AsyncMock(return_value=SimpleNamespace(content="A revised draft.")))
    blob.llm.vision_engine.side_effect = [primary, backup]

    reply = await blob.handle_user_message(pb.UserMessage(
        text="Use this image to revise the draft, keeping the deadline.", attachments=[str(image)]))

    assert reply == "A revised draft."
    messages, system = backup.generate_from_messages.call_args.args
    assert backup.generate_from_messages.call_args == primary.generate_from_messages.call_args
    assert {"role": "user", "content": request} in messages
    assert {"role": "assistant", "content": draft} in messages
    assert any(part["type"] == "image_url" for part in messages[-1]["content"])
    assert CONVERSATION_CONTINUITY in system
    assert prompt_size_bytes(messages) <= blob._max_prompt_bytes


@pytest.mark.asyncio
async def test_native_runtime_refuses_oversized_current_request(tmp_path):
    blob = assistant(tmp_path)
    blob._max_prompt_bytes = 16000
    blob.agent_runtime = SimpleNamespace(run=AsyncMock())
    reply = await blob.handle_user_message(pb.UserMessage(text="Long request " * 2000))
    assert "narrow or split" in reply
    blob.agent_runtime.run.assert_not_awaited()
