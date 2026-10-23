"""Persistent user facts must personalize PDFs across restarts and corrections."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.ai.attachments import AttachmentReader
from blob.ai.context_budget import prompt_size_bytes
from blob.ipc import blob_service_pb2
from blob.evals.document_memory import SUBJECTS, PAGES, make_blob, make_pdf


def buffered_blob(root, *, max_bytes=32000):
    blob = make_blob(root, max_bytes=max_bytes)
    blob.llm.generate_from_messages = AsyncMock(return_value=SimpleNamespace(content="An analysis. <emote>IDLE</emote>"))
    return blob


async def attach_and_declare(root, *, statement=SUBJECTS):
    path = root / "exam_schedule.pdf"
    make_pdf(path)
    blob = buffered_blob(root)
    await blob.handle_attachment_drop([str(path)])
    await blob.handle_user_message(blob_service_pb2.UserMessage(text=statement))
    return blob, path


@pytest.mark.asyncio
async def test_subjects_saved_before_consolidation_and_retrieved_after_restart(tmp_path):
    first, original = await attach_and_declare(tmp_path)
    archive = first.vector_store.episodic.get(include=["documents", "metadatas"])
    assert archive["documents"] == [f"User: {SUBJECTS}"]
    assert archive["metadatas"][0]["user_only"] is True
    assert archive["metadatas"][0]["consolidated"] is False
    assert "Digital Electronics" not in archive["documents"][0]
    original.unlink()
    restarted = buffered_blob(tmp_path)
    # The vectors deliberately fail to match the subject list to "Monday".
    assert not restarted.episodic.recall_relevant("Monday", max_distance=1.35)
    await restarted.handle_user_message(blob_service_pb2.UserMessage(text="What exam do I have on Monday?"))
    messages, system = restarted.llm.generate_from_messages.call_args.args
    assert SUBJECTS in system
    assert "Current user statement" in system
    assert "without asking again" in system
    assert "ECE 201 Digital Design with HDL" in messages[-1]["content"]
    assert "ECE 211 Internet of Things" in messages[-1]["content"]
    assert "exam_schedule.pdf, page 2" in messages[-1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("statement", [
    "My subjects are Probability and Analog.",
    "Actually, my current subjects are Probability and Analog.",
    "My course list is Probability and Analog.",
])
async def test_new_subject_list_supersedes_previous_list_and_old_assistant_program_guess(tmp_path, statement):
    first, original = await attach_and_declare(tmp_path)
    await first.handle_user_message(blob_service_pb2.UserMessage(text=statement))
    first.episodic.add_episode("Thanks", "You're definitely CSE and take Discrete Mathematics.")
    restarted = buffered_blob(tmp_path)
    context = restarted.semantic.document_context("What is my exam on Monday?")
    assert statement in context
    assert SUBJECTS not in context
    assert "definitely CSE" not in context
    current = restarted.vector_store.list_active("middle", topic_keys=("education:subjects",))
    assert [item["text"] for item in current] == [statement]


@pytest.mark.asyncio
async def test_reasserting_original_subjects_replaces_a_later_wrong_list(tmp_path):
    first, original = await attach_and_declare(tmp_path)
    await first.handle_user_message(blob_service_pb2.UserMessage(text="My subjects are Digital Electronics and Discrete Mathematics."))
    await first.handle_user_message(blob_service_pb2.UserMessage(text=SUBJECTS))
    restarted = buffered_blob(tmp_path)
    context = restarted.semantic.document_context("Monday")
    assert SUBJECTS in context
    assert "Discrete Mathematics" not in context
    assert len(restarted.vector_store.list_active("middle", topic_keys=("education:subjects",))) == 1


@pytest.mark.asyncio
async def test_profile_is_preserved_when_model_fails_before_any_reply(tmp_path):
    path = tmp_path / "exam_schedule.pdf"
    make_pdf(path)
    first = buffered_blob(tmp_path)
    await first.handle_attachment_drop([str(path)])
    first.llm.generate_from_messages.side_effect = RuntimeError("Provider unavailable")
    reply = await first.handle_user_message(blob_service_pb2.UserMessage(text=SUBJECTS))
    assert "couldn't analyze" in reply
    assert SUBJECTS in buffered_blob(tmp_path).semantic.document_context("Monday")


@pytest.mark.asyncio
async def test_user_facts_survive_shutdown_while_model_is_still_pending(tmp_path):
    path = tmp_path / "exam_schedule.pdf"
    make_pdf(path)
    first = buffered_blob(tmp_path)
    await first.handle_attachment_drop([str(path)])
    started = asyncio.Event()

    async def waiting_provider(messages, system_prompt):
        started.set()
        await asyncio.Event().wait()

    first.llm.generate_from_messages = waiting_provider
    task = asyncio.create_task(first.handle_user_message(blob_service_pb2.UserMessage(text=SUBJECTS)))
    await asyncio.wait_for(started.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert SUBJECTS in buffered_blob(tmp_path).semantic.document_context("Monday")


@pytest.mark.asyncio
async def test_old_ordinary_chat_archive_is_migrated_from_user_words_not_assistant(tmp_path):
    first = buffered_blob(tmp_path)
    first.episodic.add_episode(SUBJECTS, "You're CSE and have Discrete Mathematics.")
    first.episodic.add_episode("Thanks", "My subjects are Digital Electronics and Discrete Mathematics.")
    restarted = buffered_blob(tmp_path)
    context = restarted.semantic.document_context("Monday")
    assert SUBJECTS in context
    assert "Discrete Mathematics" not in context
    assert not restarted.vector_store.list_active("middle", topic_keys=("education:program",))


@pytest.mark.asyncio
async def test_archived_question_cannot_hide_an_earlier_subject_declaration(tmp_path):
    first = buffered_blob(tmp_path)
    first.episodic.add_episode(SUBJECTS, "Got it.")
    first.episodic.add_episode("My subjects are Digital Electronics and Discrete Mathematics?", "You're CSE.")
    restarted = buffered_blob(tmp_path)
    context = restarted.semantic.document_context("Monday")
    assert SUBJECTS in context and "Discrete Mathematics" not in context


@pytest.mark.asyncio
async def test_user_profile_is_readable_in_a_fresh_os_process(tmp_path):
    first, original = await attach_and_declare(tmp_path)
    script = (
        "import json,sys; from pathlib import Path; from blob.evals.document_memory import make_blob; "
        "blob=make_blob(Path(sys.argv[1])); print(json.dumps({'context':blob.semantic.document_context('Monday')}))"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], env=environment,
                            capture_output=True, text=True, timeout=30, check=True)
    assert SUBJECTS in json.loads(result.stdout)["context"]


@pytest.mark.asyncio
async def test_long_conversation_and_low_prompt_budget_keep_current_subjects(tmp_path):
    first, original = await attach_and_declare(tmp_path)
    for index in range(24):
        await first.handle_user_message(blob_service_pb2.UserMessage(text=f"Unrelated chat number {index}."))
    assert all(SUBJECTS not in turn["content"] for turn in first._recent_turns)
    restarted = buffered_blob(tmp_path, max_bytes=4096)
    await restarted.handle_user_message(blob_service_pb2.UserMessage(text="What exam do I have on Monday?"))
    messages, system = restarted.llm.generate_from_messages.call_args.args
    assert SUBJECTS in system
    assert prompt_size_bytes(messages) <= 4096
    assert "HDL" in messages[-1]["content"]


@pytest.mark.asyncio
async def test_subjects_from_ordinary_chat_are_available_when_a_pdf_is_opened_later(tmp_path):
    first = buffered_blob(tmp_path)
    first.llm.generate_from_messages = AsyncMock(return_value=SimpleNamespace(content="Got it."))
    await first.handle_user_message(blob_service_pb2.UserMessage(text=SUBJECTS))
    restarted = buffered_blob(tmp_path)
    path = tmp_path / "exam_schedule.pdf"
    make_pdf(path)
    await restarted.handle_attachment_drop([str(path)])
    assert SUBJECTS in restarted.llm.generate_from_messages.call_args.args[1]


@pytest.mark.asyncio
async def test_personal_statement_after_pasted_file_path_keeps_its_original_archived_source(tmp_path):
    path = tmp_path / "exam schedule.pdf"
    make_pdf(path)
    blob = buffered_blob(tmp_path)
    blob.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(is_capture_blocked=lambda: True))
    text = f'"{path}" {SUBJECTS}'
    await blob.handle_user_message(blob_service_pb2.UserMessage(text=text))
    archive = blob.vector_store.episodic.get(include=["documents"])
    assert archive["documents"] == ["User: " + text]
    current = blob.vector_store.list_active("middle", topic_keys=("education:subjects",))
    assert current[0]["text"] == SUBJECTS
    assert current[0]["metadata"]["source_episode_id"] == archive["ids"][0]
    assert SUBJECTS in buffered_blob(tmp_path).semantic.document_context("Monday")


@pytest.mark.asyncio
async def test_screen_privacy_shield_preserves_authored_document_chat_and_saved_answers(tmp_path):
    path = tmp_path / "exam_schedule.pdf"
    make_pdf(path)
    blob = buffered_blob(tmp_path)
    blob.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(is_capture_blocked=lambda: True))
    await blob.handle_attachment_drop([str(path)])
    await blob.handle_user_message(blob_service_pb2.UserMessage(text=SUBJECTS))
    assert blob.llm.generate_from_messages.await_count == 2
    assert blob.vector_store.episodic.get(include=["documents"])["documents"] == [f"User: {SUBJECTS}"]
    assert blob.vector_store.middle.get(include=["documents"])["documents"] == [SUBJECTS]
    assert blob._result_library().records()


@pytest.mark.asyncio
async def test_expired_subjects_do_not_return_through_episode_retrieval_or_backfill(tmp_path):
    blob = buffered_blob(tmp_path)
    old = time.time() - 31 * 86400
    episode_id = blob.vector_store.store(f"User: {SUBJECTS}", {"timestamp": old}, collection="episodic")
    blob.semantic.remember_explicit_statements(SUBJECTS, episode_id, old)
    restarted = buffered_blob(tmp_path)
    assert SUBJECTS not in restarted.semantic.document_context("Monday")


@pytest.mark.asyncio
@pytest.mark.parametrize("utterance", [
    "My friend's subjects are Digital Electronics and Discrete Mathematics.",
    "Do you remember my subjects are Digital Electronics and Discrete Mathematics?",
    "The PDF says: My subjects are Digital Electronics and Discrete Mathematics.",
])
async def test_third_party_quotes_and_questions_do_not_replace_personal_subject_list(tmp_path, utterance):
    first, original = await attach_and_declare(tmp_path)
    await first.handle_user_message(blob_service_pb2.UserMessage(text=utterance))
    current = first.vector_store.list_active("middle", topic_keys=("education:subjects",))
    assert [item["text"] for item in current] == [SUBJECTS]


def test_remembered_subjects_find_a_deep_pdf_page_without_changing_explicit_page_selection(tmp_path):
    path = tmp_path / "long_schedule.pdf"
    make_pdf(path, [PAGES[0] * 20] * 99 + [PAGES[1]])
    reader = AttachmentReader()
    prepared = reader.prepare([str(path)], "What exam do I have on Monday?", vision=False,
                              text_budget=1600, search_context="Current user statement: My subjects are HDL and IoT.")
    text = "\n".join(part.get("text", "") for part in prepared.parts)
    assert "long_schedule.pdf, page 100" in text
    assert "Digital Design with HDL" in text
    explicit = reader.prepare([str(path)], "Explain page 1", vision=False, text_budget=1600,
                              search_context="My subjects are HDL and IoT. See page 999.")
    text = "\n".join(part.get("text", "") for part in explicit.parts)
    assert "long_schedule.pdf, page 1:" in text
    assert "page 100:" not in text


def test_explicit_request_for_another_program_overrides_personal_pdf_search_terms(tmp_path):
    path = tmp_path / "long_schedule.pdf"
    make_pdf(path, [PAGES[1] * 20] * 99 + [PAGES[0]])
    prepared = AttachmentReader().prepare([str(path)], "Explain the CSE exams", vision=False,
        text_budget=1600, search_context="Current user statement: My subjects are HDL and IoT.")
    text = "\n".join(part.get("text", "") for part in prepared.parts)
    assert "long_schedule.pdf, page 100" in text
    assert "CSE 203 Discrete Mathematics" in text


@pytest.mark.asyncio
async def test_user_memory_read_failure_does_not_fall_back_to_guessing_a_branch(tmp_path):
    first, original = await attach_and_declare(tmp_path)
    first.semantic.document_context = lambda query: (_ for _ in ()).throw(RuntimeError("Memory unavailable"))
    first.llm.generate_from_messages.reset_mock()
    reply = await first.handle_user_message(blob_service_pb2.UserMessage(text="What exam do I have on Monday?"))
    assert "couldn't load your saved personal context" in reply
    first.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("quote", [None, "My subjects are unknown.", "My friend's subjects are Digital Electronics and Discrete Mathematics."])
async def test_model_cannot_assign_cse_exams_without_a_personal_selector(tmp_path, quote):
    blob = buffered_blob(tmp_path)
    path = tmp_path / "exam_schedule.pdf"
    make_pdf(path)
    await blob.handle_attachment_drop([str(path)])
    if quote:
        await blob.handle_user_message(blob_service_pb2.UserMessage(text=quote))
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content=
        "You have CSE 207 Digital Electronics and CSE 203 Discrete Mathematics on Monday. <emote>HAPPY</emote>")
    reply = await blob.handle_user_message(blob_service_pb2.UserMessage(text="What exam do I have on Monday?"))
    assert "Tell me your subjects or program" in reply
    assert "CSE" not in reply and "Discrete Mathematics" not in reply
    assert "<emote>" not in reply


@pytest.mark.asyncio
async def test_newer_subjects_cannot_be_overwritten_by_late_old_consolidation(tmp_path):
    blob, original = await attach_and_declare(tmp_path)
    first_episode = blob.vector_store.episodic.get(include=["documents", "metadatas"])
    correction = "My subjects are Probability and Analog."
    await blob.handle_user_message(blob_service_pb2.UserMessage(text=correction))
    blob.semantic.llm = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(content="L1")))
    assert await blob.semantic.summarize_and_store([{
        "id": first_episode["ids"][0], "text": first_episode["documents"][0], "metadata": first_episode["metadatas"][0]}])
    context = buffered_blob(tmp_path).semantic.document_context("Monday")
    assert correction in context and SUBJECTS not in context
