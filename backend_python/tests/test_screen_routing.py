"""Screen help selects a fresh capture even while a PDF conversation is active."""

from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from blob.ai.attachments import AttachmentReader
from blob.ai.orchestrator import _wants_screen_capture
from blob.ipc import blob_service_pb2
from blob.memory.documents import DocumentLibrary
from blob.skills.builtin.screen_capture import ScreenCaptureSkill
from blob.skills.registry import SkillRegistry
from test_attachments import orchestrator, text_pdf

SCREEN_HELP = [
    "dude the stuff on my screen is so hard, can you dumb it down for me",
    "No the stuff on my screen, not the pdf",
    "bro this stuff on my screen is so hard. Can you dumb it down for me",
    "This equation on my screen is confusing. Break it down for me",
    "Make the material on my display simpler",
    "The lesson on my desktop is difficult",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("utterance", [
    "whats going on my screen rn",
    "whats happening on my screen rn",
    "whats on my screen",
    "what’s going on my screen rn",
    "my screen, whats on it?",
])
async def test_informal_screen_question_captures_before_answer(tmp_path, utterance):
    instance, screen, library = setup_screen_chat(tmp_path, "attached")
    await instance.handle_user_message(blob_service_pb2.UserMessage(text=utterance))
    screen.sampler.capture.assert_awaited_once_with()
    observation = instance.llm.generate_from_messages.call_args.args[0][-1]["content"]
    assert "A fresh screen capture succeeded" in observation
    assert "Voltage divider" in observation
    instance._handle_attachment_message.assert_not_awaited()
    library.find.assert_not_called()


@pytest.mark.asyncio
async def test_do_the_capture_after_reported_screen_access_denial(tmp_path):
    instance, screen, library = setup_screen_chat(tmp_path, "attached")
    instance._recent_turns = deque([
        {"role": "user", "content": "whats going on my screen rn"},
        {"role": "assistant", "content":
            "I don’t have a fresh screen capture right now, so I can’t see what’s on your screen."},
    ], maxlen=12)
    await instance.handle_user_message(blob_service_pb2.UserMessage(text="do the capture"))
    screen.sampler.capture.assert_awaited_once_with()
    assert "A fresh screen capture succeeded" in instance.llm.generate_from_messages.call_args.args[0][-1]["content"]
    instance._handle_attachment_message.assert_not_awaited()
    library.find.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [
    "The voltage divider gives 6 V.",
    "I don’t have a screen‑capture tool available in this environment.",
])
async def test_hermes_screen_exchange_uses_fresh_capture_and_rejects_false_tool_denial(tmp_path, answer):
    instance, screen, library = setup_screen_chat(tmp_path, "attached")
    instance.agent_runtime = SimpleNamespace(run=AsyncMock(return_value=answer))
    for count, utterance in enumerate(("whats going on my screen rn", "do the capture"), 1):
        reply = await instance.handle_user_message(blob_service_pb2.UserMessage(text=utterance))
        assert screen.sampler.capture.await_count == count
        observation = instance.agent_runtime.run.call_args.args[0][-1]["content"]
        assert "A fresh screen capture succeeded" in observation
        assert "Voltage divider" in observation
        if "tool available" in answer:
            assert reply.startswith("I captured your screen")
            assert "tool available" not in reply
        else:
            assert reply == answer
    instance.llm.generate_from_messages.assert_not_awaited()
    instance._handle_attachment_message.assert_not_awaited()
    library.find.assert_not_called()


def setup_screen_chat(tmp_path, mode):
    instance = orchestrator()
    instance.screen_sampler = SimpleNamespace(
        privacy_shield=SimpleNamespace(is_capture_blocked=lambda: False),
        get_active_window_title=lambda: "Lecture notes",
        capture=AsyncMock(side_effect=lambda: Image.new("RGB", (100, 80), "white")),
        last_error="",
    )
    screen = ScreenCaptureSkill()
    screen.set_sampler(instance.screen_sampler)
    screen.set_ocr(SimpleNamespace(extract_text=MagicMock(return_value=
        "Voltage divider: Find Vout for Vin=12 V, R1=2 kohm, R2=2 kohm.")))
    instance.skill_registry = SkillRegistry(tmp_path / "skills")
    instance.skill_registry.register(screen)
    instance._build_context = lambda text: "Earlier conversation mentioned HDL and IoT exams in a PDF timetable."
    instance._recent_turns = deque([
        {"role": "user", "content": SCREEN_HELP[0]},
        {"role": "assistant", "content": "Your PDF subjects are HDL and IoT. I can't see your screen."},
    ], maxlen=12)
    instance.llm.generate_from_messages.return_value = SimpleNamespace(content="The divider gives you 6 V. <emote>HAPPY</emote>")
    library = DocumentLibrary(tmp_path / "documents")
    instance._documents = library
    instance._active_attachments = []
    if mode != "none":
        path = tmp_path / "exam_schedule.pdf"
        # These words deliberately match the request: saved recall must still be bypassed.
        text_pdf(path, ["HDL and IoT exams. Study hard. Simplify the lesson on my screen."])
        library.remember(AttachmentReader().prepare([str(path)], "Explain", vision=False).sources)
        if mode == "attached":
            instance._active_attachments = [str(path)]
    library.find = MagicMock(wraps=library.find)
    library.reopen = MagicMock(wraps=library.reopen)
    instance._handle_attachment_message = AsyncMock(side_effect=AssertionError("Screen help was routed to a PDF"))
    return instance, screen, library


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["none", "attached", "saved"])
@pytest.mark.parametrize("utterance", SCREEN_HELP)
async def test_screen_help_captures_before_answer_in_every_document_state(tmp_path, mode, utterance):
    instance, screen, library = setup_screen_chat(tmp_path, mode)
    # Screen priority belongs at the entry point, independent of the attachment fallback.
    instance._uses_attachment_context = lambda text: True
    reply = await instance.handle_user_message(blob_service_pb2.UserMessage(text=utterance))
    screen.sampler.capture.assert_awaited_once_with()
    screen.ocr.extract_text.assert_called_once()
    instance._handle_attachment_message.assert_not_awaited()
    library.find.assert_not_called()
    library.reopen.assert_not_called()
    observation = instance.llm.generate_from_messages.call_args.args[0][-1]["content"]
    assert "A fresh screen capture succeeded" in observation
    assert "Voltage divider" in observation
    assert "work through it" in observation
    assert "HDL" not in observation and "IoT" not in observation
    assert "not an earlier attached or saved document" in observation
    assert reply == "The divider gives you 6 V."


@pytest.mark.asyncio
async def test_screen_request_also_takes_priority_over_explicit_attachment_paths(tmp_path):
    instance, screen, library = setup_screen_chat(tmp_path, "attached")
    await instance.handle_user_message(blob_service_pb2.UserMessage(
        text=SCREEN_HELP[0], attachments=instance._active_attachments))
    screen.sampler.capture.assert_awaited_once_with()
    instance._handle_attachment_message.assert_not_awaited()
    library.find.assert_not_called()


@pytest.mark.asyncio
async def test_actual_conversation_captures_fresh_material_before_and_after_detaching_pdf(tmp_path):
    instance, screen, library = setup_screen_chat(tmp_path, "attached")
    screen.ocr.extract_text.side_effect = [
        "Voltage divider: Vin=12 V, R1=2 kohm, R2=2 kohm.",
        "Signals: A sine wave has an amplitude and a frequency.",
        "Probability: Independent events satisfy P(A and B) = P(A) P(B).",
    ]
    for index, request in enumerate(SCREEN_HELP[:3]):
        if index == 2:
            reply = await instance.handle_user_message(blob_service_pb2.UserMessage(text="/files remove 1"))
            assert "Detached exam_schedule.pdf" in reply
            assert not instance._active_attachments
            assert library.records()  # Its persistent copy must not steal the next screen request.
        await instance.handle_user_message(blob_service_pb2.UserMessage(text=request))
        observation = instance.llm.generate_from_messages.call_args.args[0][-1]["content"]
        assert ["Voltage divider", "A sine wave", "Independent events"][index] in observation
        for stale in ["Voltage divider", "A sine wave", "Independent events"][:index]:
            assert stale not in observation
    assert screen.sampler.capture.await_count == 3
    assert instance.llm.generate_from_messages.await_count == 3
    library.find.assert_not_called()
    instance._handle_attachment_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["privacy", "portal", "ocr"])
async def test_screen_failure_reports_real_reason_instead_of_falling_back_to_pdf(tmp_path, failure):
    instance, screen, library = setup_screen_chat(tmp_path, "attached")
    if failure == "privacy":
        screen.sampler.privacy_shield.is_capture_blocked = lambda: True
        expected = "privacy shield"
    elif failure == "portal":
        screen.sampler.capture.side_effect = None
        screen.sampler.capture.return_value = None
        screen.sampler.last_error = "Desktop screenshot permission was declined."
        expected = "permission was declined"
    else:
        screen.ocr.extract_text.return_value = "OCR is not available."
        expected = "cannot read text"
    reply = await instance.handle_user_message(blob_service_pb2.UserMessage(text=SCREEN_HELP[0]))
    assert expected in reply
    instance.llm.generate_from_messages.assert_not_awaited()
    instance._handle_attachment_message.assert_not_awaited()
    library.find.assert_not_called()
    assert not getattr(instance, "_thinking_placeholder_visible", False)


@pytest.mark.asyncio
@pytest.mark.parametrize("utterance", [
    "Don't capture my screen. Explain the PDF instead.",
    "Don’t capture my screen. Explain the PDF instead.",
    "I don't need you to capture my screen. Explain the PDF.",
    "No capture of my screen. Explain the PDF instead.",
    "I don’t want my screen captured. Explain the PDF instead.",
    "Explain the PDF, not my screen.",
])
async def test_screen_denial_keeps_requested_pdf_analysis_and_never_captures(tmp_path, utterance):
    instance, screen, library = setup_screen_chat(tmp_path, "attached")
    instance._handle_attachment_message.side_effect = None
    instance._handle_attachment_message.return_value = "The PDF timetable"
    reply = await instance.handle_user_message(blob_service_pb2.UserMessage(text=utterance))
    assert reply == "The PDF timetable"
    screen.sampler.capture.assert_not_awaited()
    instance._handle_attachment_message.assert_awaited_once()


def test_screen_followup_accepts_natural_help_but_not_unrelated_or_denied_capture():
    previous = [{"role": "user", "content": SCREEN_HELP[0]}]
    assert _wants_screen_capture("Go ahead", previous)
    assert _wants_screen_capture("No, I meant my screen", previous)
    for request in ["My PDF is hard. Dumb it down", "How do I capture my screen?", "Don't look at my screen"]:
        assert not _wants_screen_capture(request, previous)
    assert not _wants_screen_capture("Go ahead", [{"role": "user", "content": "Don't capture my screen"}])


@pytest.mark.parametrize("utterance", [
    "Don’t capture my screen",
    "No capture of my screen",
    "Explain the PDF, not my screen",
    "How do I capture my screen?",
    "Why can’t you capture my screen?",
    "Why won’t you capture my screen?",
    "Explain the PDF instead",
])
def test_informal_screen_question_does_not_override_denial_or_topic_change(utterance):
    history = [{"role": "user", "content": "whats going on my screen rn"}]
    assert not _wants_screen_capture(utterance, history)


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", [
    "I can't peek at your screen or any files you haven't dropped here.",
    "I can’t see your screen unless you send me a screenshot.",
    "I don't have access to your screen.",
    "I don’t have a screen‑capture tool available in this environment.",
])
async def test_prior_pdf_access_denial_cannot_override_a_successful_fresh_capture(tmp_path, denial):
    instance, screen, library = setup_screen_chat(tmp_path, "attached")
    instance.llm.generate_from_messages.side_effect = [
        SimpleNamespace(content=denial), SimpleNamespace(content="The voltage divider gives 6 V."),
    ]
    reply = await instance.handle_user_message(blob_service_pb2.UserMessage(text=SCREEN_HELP[0]))
    screen.sampler.capture.assert_awaited_once_with()
    assert instance.llm.generate_from_messages.await_count == 2
    assert reply == "The voltage divider gives 6 V."
    instance._handle_attachment_message.assert_not_awaited()
