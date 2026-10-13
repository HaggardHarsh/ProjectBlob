"""Terminal file selections retain real source content across image follow-ups."""

from types import SimpleNamespace
import asyncio
from unittest.mock import AsyncMock, MagicMock

from PIL import Image
import pytest

from blob.ai.attachments import AttachmentError, parse_selected_files
from blob.config import BlobConfig
from blob.privacy.controls import PrivacyBlocked, PrivacyControls
from blob.ipc import blob_service_pb2 as pb
from test_attachments import orchestrator


@pytest.mark.parametrize("text,path,question", [
    ("/home/cloud/Pictures/Camera/Photo from 2026-09-23 18-58-05.731166.jpeg  who is in this picture",
     "/home/cloud/Pictures/Camera/Photo from 2026-09-23 18-58-05.731166.jpeg", "who is in this picture"),
    ('"/tmp/Photo from Tuesday.jpeg" What is in this picture?', "/tmp/Photo from Tuesday.jpeg", "What is in this picture?"),
    ("'/tmp/Study notes.pdf' Explain page 2", "/tmp/Study notes.pdf", "Explain page 2"),
    (r"/tmp/Photo\ from\ Tuesday.jpeg What's in this picture?", "/tmp/Photo from Tuesday.jpeg", "What's in this picture?"),
    ("~/Pictures/family.png Describe this", "~/Pictures/family.png", "Describe this"),
    ("./sample.webp Describe this", "./sample.webp", "Describe this"),
    ("/tmp/my.report photo.jpeg Describe this", "/tmp/my.report photo.jpeg", "Describe this"),
])
def test_terminal_path_quotes_escapes_and_unquoted_spaces(text, path, question):
    assert parse_selected_files(text) == (question, [path])


@pytest.mark.parametrize("text", [
    "Find /home/cloud/Pictures/photo.jpeg", "Draft a mail about /tmp/photo.jpeg",
    "/privacy allow /tmp/pictures.jpeg", "/files forget /tmp/photo.jpeg",
    "/camera status", "/skills run file_search /tmp/photo.jpeg", "I'm tired",
])
def test_embedded_paths_and_local_commands_are_not_implicit_attachments(text):
    assert parse_selected_files(text) == (text, [])


def test_multiple_selections_and_filename_shell_characters_are_literal():
    question, paths = parse_selected_files('"/tmp/a.jpg" "/tmp/$(command);`other`.png" Describe both')
    assert question == "Describe both"
    assert paths == ["/tmp/a.jpg", "/tmp/$(command);`other`.png"]
    assert parse_selected_files("/tmp/photo.jpeg")[1] == ["/tmp/photo.jpeg"]
    with pytest.raises(AttachmentError, match="unclosed quote"):
        parse_selected_files('"/tmp/photo.jpeg Describe this')


@pytest.mark.asyncio
async def test_pasted_image_path_and_other_person_followup_both_supply_real_pixels(tmp_path):
    path = tmp_path / "Photo from Tuesday.jpeg"
    Image.new("RGB", (32, 24), "blue").save(path)
    instance = orchestrator()
    instance._handle_text_message = AsyncMock(side_effect=AssertionError("Image request used text-only chat"))
    vision = SimpleNamespace(generate_from_messages=AsyncMock(return_value=SimpleNamespace(
        content="Two people are visible. <emote>IDLE</emote>")))
    instance.llm.vision_engine.return_value = vision

    await instance.handle_user_message(pb.UserMessage(text=str(path) + "  Describe the people in this picture"))
    assert instance._active_attachments == [str(path)]
    assert instance._recent_turns[-2]["content"].startswith("Describe the people in this picture\n[Attached: ")
    await instance.handle_user_message(pb.UserMessage(text="What about the other person"))
    await instance.handle_user_message(pb.UserMessage(text="What are they wearing?"))
    assert vision.generate_from_messages.await_count == 3
    for call in vision.generate_from_messages.await_args_list:
        messages = call.args[0]
        assert any(part["type"] == "image_url" for part in messages[-1]["content"])
        assert path.name in str(messages[-1]["content"])
    instance.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_pasted_image_reports_read_error_and_preserves_previous_selection(tmp_path):
    instance = orchestrator()
    instance._active_attachments = ["/previous/photo.jpeg"]
    instance._handle_text_message = AsyncMock(side_effect=AssertionError("Missing image used chat model"))
    reply = await instance.handle_user_message(pb.UserMessage(text=str(tmp_path / "Missing photo.jpeg") + " Describe this"))
    assert "Select the file again" in reply
    assert instance._active_attachments == ["/previous/photo.jpeg"]
    instance.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_image_selection_does_not_make_unrelated_drafting_use_vision(tmp_path):
    path = tmp_path / "photo.jpeg"
    Image.new("RGB", (16, 16), "white").save(path)
    instance = orchestrator()
    instance.llm.vision_engine.return_value = SimpleNamespace(generate_from_messages=AsyncMock(
        return_value=SimpleNamespace(content="A photo. <emote>IDLE</emote>")))
    await instance.handle_user_message(pb.UserMessage(text=str(path) + " Describe this picture"))
    instance._handle_text_message = AsyncMock(return_value="Email draft")
    assert await instance.handle_user_message(pb.UserMessage(text="Draft a mail to my professor")) == "Email draft"
    instance._handle_text_message.assert_awaited_once()
    assert instance._active_attachments == [str(path)]


@pytest.mark.asyncio
async def test_identity_questions_never_guess_names_and_selected_photo_can_be_described(tmp_path):
    path = tmp_path / "Photo from Tuesday.jpeg"
    Image.new("RGB", (16, 16), "white").save(path)
    instance = orchestrator()
    instance.llm.generate_from_messages.side_effect = AssertionError("Photo identity question used chat")
    vision = SimpleNamespace(generate_from_messages=AsyncMock(return_value=SimpleNamespace(
        content="The person on the right is wearing a blue shirt. <emote>IDLE</emote>")))
    instance.llm.vision_engine.return_value = vision
    first = await instance.handle_user_message(pb.UserMessage(text=str(path) + " who is in this picture"))
    second = await instance.handle_user_message(pb.UserMessage(text="What about the other person"))
    assert first == second
    assert "can't establish who" in first
    assert instance._active_attachments == [str(path)]
    instance.llm.vision_engine.assert_not_awaited()
    third = await instance.handle_user_message(pb.UserMessage(text="Describe the other person"))
    assert "blue shirt" in third
    vision.generate_from_messages.assert_awaited_once()
    assert any(part["type"] == "image_url" for part in vision.generate_from_messages.call_args.args[0][-1]["content"])


@pytest.mark.asyncio
async def test_missing_photo_for_identity_question_reports_missing_file_instead_of_guess(tmp_path):
    instance = orchestrator()
    reply = await instance.handle_user_message(pb.UserMessage(text=str(tmp_path / "missing.jpeg") + " Who is this person?"))
    assert "Select the file again" in reply
    instance.llm.vision_engine.assert_not_awaited()
    instance.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_vision_timeout_retries_same_pixels_once_with_backup(tmp_path):
    path = tmp_path / "photo.jpeg"
    Image.new("RGB", (16, 16), "red").save(path)
    instance = orchestrator()
    primary = SimpleNamespace(model_name="primary", generate_from_messages=AsyncMock(side_effect=asyncio.TimeoutError()))
    backup = SimpleNamespace(model_name="backup", generate_from_messages=AsyncMock(return_value=SimpleNamespace(
        content="A red image. <emote>IDLE</emote>")))
    instance.llm.vision_engine.side_effect = [primary, backup]
    reply = await instance.handle_user_message(pb.UserMessage(text=str(path) + " Describe this photo"))
    assert reply == "A red image."
    assert instance.llm.vision_engine.await_args_list[-1].args[0] == "openbmb/MiniCPM-V-4_5"
    primary.generate_from_messages.assert_awaited_once()
    backup.generate_from_messages.assert_awaited_once()
    assert primary.generate_from_messages.call_args.args == backup.generate_from_messages.call_args.args
    assert any(part["type"] == "image_url" for part in backup.generate_from_messages.call_args.args[0][-1]["content"])


@pytest.mark.asyncio
@pytest.mark.parametrize("setting", ["paused", "cloud_enabled"])
async def test_privacy_change_prevents_backup_request(tmp_path, setting):
    instance = orchestrator()
    instance.controls = PrivacyControls(tmp_path / "privacy.json")
    async def stopped(*args):
        instance.controls.update(**{setting: setting == "paused"})
        raise asyncio.TimeoutError()
    primary = SimpleNamespace(model_name="primary", generate_from_messages=stopped)
    with pytest.raises(PrivacyBlocked):
        await instance._generate_attachment_answer([], "System", primary, has_images=True)
    instance.llm.vision_engine.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("has_images,backup_name", [(False, "backup"), (True, "off")])
async def test_text_requests_and_disabled_failover_never_call_backup(has_images, backup_name):
    instance = orchestrator()
    instance.config.vision_fallback_model_name = backup_name
    primary = SimpleNamespace(model_name="primary", generate_from_messages=AsyncMock(side_effect=asyncio.TimeoutError()))
    with pytest.raises(asyncio.TimeoutError):
        await instance._generate_attachment_answer([], "System", primary, has_images=has_images)
    instance.llm.vision_engine.assert_not_awaited()


def test_vision_failover_can_be_disabled_in_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("BLOB_VISION_FALLBACK_MODEL", "off")
    assert BlobConfig.load(str(tmp_path / "missing.yaml")).vision_fallback_model_name == "off"


@pytest.mark.asyncio
async def test_expected_timeout_after_progress_has_no_unhandled_future_error():
    instance = orchestrator()
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    errors = []
    loop.set_exception_handler(lambda loop, context: errors.append(context))
    async def times_out():
        await asyncio.sleep(0.02)
        raise asyncio.TimeoutError()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await instance._await_with_progress(times_out(), 0.001, "WAITING")
        await asyncio.sleep(0)
        assert not errors
        instance.dispatch_emote.assert_awaited_once_with("WAITING")
    finally:
        loop.set_exception_handler(previous_handler)
