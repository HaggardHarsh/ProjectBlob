"""Deleting a source must not delete completed work or turn it into user facts."""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from blob.ai.context_budget import prompt_size_bytes
from blob.evals.document_memory import SUBJECTS, make_blob, make_pdf
from blob.ipc import blob_service_pb2
from blob.memory.results import ResultLibrary, ResultError

TIMETABLE = """Your specialised timetable (exam_schedule.pdf, page 2):

| Date | Time | Subject |
|---|---|---|
| Monday 2026-10-05 | 9:30-10:30 am | HDL |
| Monday 2026-10-05 | 2:30-3:30 pm | IoT |
| Tuesday 2026-10-06 | 9:30-10:30 am | Probability |
| Thursday 2026-10-08 | 9:30-10:30 am | Analog |"""


async def say(blob, text):
    return await blob.handle_user_message(blob_service_pb2.UserMessage(text=text))


async def completed_work(root):
    blob = make_blob(root)
    await say(blob, SUBJECTS)
    path = root / "exam_schedule.pdf"
    make_pdf(path)
    await blob.handle_attachment_drop([str(path)])
    assert not blob._result_library().records()  # Automatic overview is not work requested by the user.
    blob.llm.generate_from_messages = AsyncMock(return_value=SimpleNamespace(content=TIMETABLE + "\n<emote>HAPPY</emote>"))
    assert await say(blob, "Make me a specialised exam timetable") == TIMETABLE
    return blob, path, blob._result_library().records()[0]


@pytest.mark.asyncio
async def test_forget_source_preserves_work_and_unrelated_live_conversation(tmp_path):
    blob, path, result = await completed_work(tmp_path)
    blob._remember_recent_turn("My favourite snack is popcorn.", "Got it.")
    source = blob._document_library().records()[0]
    reply = await say(blob, "/files forget " + source["id"])
    assert "Saved answers and timetables remain" in reply
    assert not blob._document_library().records()
    assert not blob._active_attachments
    assert path.exists() and not blob._document_library().path_for(source).exists()
    recent = str(list(blob._recent_turns))
    assert TIMETABLE.splitlines()[0] in recent and "popcorn" in recent
    assert "[Attached:" not in recent
    assert blob._result_library().get(result["id"])["answer"] == TIMETABLE


@pytest.mark.asyncio
async def test_timetable_replays_after_source_forget_restart_and_original_deletion_without_provider(tmp_path):
    blob, path, result = await completed_work(tmp_path)
    await say(blob, "/files forget all")
    path.unlink()
    restarted = make_blob(tmp_path)
    restarted.llm.generate_from_messages = AsyncMock(side_effect=RuntimeError("Provider offline"))
    assert await say(restarted, "Show my timetable") == TIMETABLE
    assert await say(restarted, "/results show " + result["id"]) == TIMETABLE
    restarted.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_exam_followup_uses_saved_work_with_fresh_clock_and_no_pdf_access(tmp_path):
    blob, path, result = await completed_work(tmp_path)
    await say(blob, "/files forget all")
    path.unlink()
    restarted = make_blob(tmp_path, max_bytes=4096)
    restarted._attachment_reader = SimpleNamespace(prepare=Mock(side_effect=AssertionError("PDF must not be read")))
    restarted.llm.generate_from_messages = AsyncMock(return_value=SimpleNamespace(
        content="You have HDL at 9:30 am and IoT at 2:30 pm on Monday. <emote>HAPPY</emote>"))
    reply = await say(restarted, "What exam do I have on Monday?")
    assert "HDL" in reply and "IoT" in reply and "<emote>" not in reply
    messages, system = restarted.llm.generate_from_messages.call_args.args
    assert any(TIMETABLE in message["content"] for message in messages)
    assert "previously completed file answers" in system
    assert "current local clock" in system and "Current local date and time" in system
    assert "Do not claim you reopened" in system
    assert prompt_size_bytes(messages) <= 4096
    restarted._attachment_reader.prepare.assert_not_called()
    assert not restarted._document_library().records()
    assert restarted.vector_store.middle.get(include=["documents"])["documents"] == [SUBJECTS]
    assert all(TIMETABLE not in text for text in restarted.vector_store.episodic.get(include=["documents"])["documents"])


@pytest.mark.asyncio
async def test_results_are_readable_in_an_independent_process(tmp_path):
    blob, path, result = await completed_work(tmp_path)
    await say(blob, "/files forget all")
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    script = "import json,sys; from blob.memory.results import ResultLibrary; print(json.dumps(ResultLibrary(sys.argv[1]).records()))"
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path / "memory")],
                               env=environment, capture_output=True, text=True, timeout=20, check=True)
    assert json.loads(completed.stdout)[0]["answer"] == TIMETABLE


@pytest.mark.asyncio
async def test_forgetting_result_removes_it_after_restart_and_preserves_source_and_subjects(tmp_path):
    blob, path, result = await completed_work(tmp_path)
    blob.llm.generate_from_messages.reset_mock()
    assert result["id"] in await say(blob, "/results")
    await say(blob, "/results show " + result["id"])
    await say(blob, "/results forget " + result["id"])
    assert not make_blob(tmp_path)._result_library().records()
    assert blob._document_library().records() and path.exists()
    assert SUBJECTS in blob.semantic.document_context("Monday")
    assert all(result["id"] not in item["content"] and TIMETABLE not in item["content"] for item in blob._recent_turns)
    blob.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_countdown_question_does_not_replace_complete_timetable(tmp_path):
    blob, path, result = await completed_work(tmp_path)
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content="Three days. <emote>IDLE</emote>")
    await say(blob, "How many days until my first exam in the timetable?")
    assert blob._result_library().get(result["id"])["answer"] == TIMETABLE
    assert len(blob._result_library().records()) == 2


@pytest.mark.asyncio
async def test_regenerated_timetable_updates_the_existing_work(tmp_path):
    blob, path, result = await completed_work(tmp_path)
    revised = TIMETABLE.replace("9:30-10:30 am", "10:30-11:30 am")
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content=revised + " <emote>IDLE</emote>")
    await say(blob, "Make me the revised exam timetable")
    assert [item["answer"] for item in blob._result_library().records()] == [revised]
    assert blob._result_library().get(result["id"])["answer"] == revised
    assert all(TIMETABLE not in turn["content"] for turn in blob._recent_turns)


@pytest.mark.asyncio
async def test_a_revised_source_is_used_instead_of_an_old_result_after_restart(tmp_path):
    blob, path, result = await completed_work(tmp_path)
    make_pdf(path, ["ECE 201 HDL exam Monday 05.10.2026 now starts 11:30 am."])
    await blob.handle_attachment_drop([str(path)])
    restarted = make_blob(tmp_path)
    restarted.llm.generate_from_messages = AsyncMock(return_value=SimpleNamespace(content="HDL starts at 11:30 am."))
    await say(restarted, "What exam do I have on Monday?")
    messages, system = restarted.llm.generate_from_messages.call_args.args
    assert "now starts 11:30 am" in str(messages)
    assert "Saved generated work" not in str(messages)
    assert all(TIMETABLE not in message["content"] for message in messages)


@pytest.mark.asyncio
async def test_edits_to_saved_work_survive_another_restart_without_the_source(tmp_path):
    blob, path, result = await completed_work(tmp_path)
    await say(blob, "/files forget all")
    restarted = make_blob(tmp_path)
    revised = TIMETABLE.replace("| Date | Time | Subject |", "| Exam date | Exam time | Subject |")
    restarted.llm.generate_from_messages = AsyncMock(return_value=SimpleNamespace(content=revised))
    await say(restarted, "Rewrite my timetable using clearer column names")
    again = make_blob(tmp_path)
    assert await say(again, "/results show " + result["id"]) == revised
    assert not again._document_library().records()


@pytest.mark.asyncio
async def test_discussing_an_edit_without_requesting_it_does_not_overwrite_the_timetable(tmp_path):
    blob, path, result = await completed_work(tmp_path)
    await say(blob, "/files forget all")
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content="The date column is the exam date.")
    await say(blob, "Don't rewrite my timetable; just explain the date column.")
    assert blob._result_library().get(result["id"])["answer"] == TIMETABLE


@pytest.mark.asyncio
async def test_show_by_id_keeps_the_result_available_for_a_followup_edit(tmp_path):
    blob, path, result = await completed_work(tmp_path)
    await say(blob, "/files forget all")
    restarted = make_blob(tmp_path)
    await say(restarted, "/results show " + result["id"])
    revised = TIMETABLE.replace("| Subject |", "| Paper |")
    restarted.llm.generate_from_messages = AsyncMock(return_value=SimpleNamespace(content=revised))
    await say(restarted, "Rewrite it using clearer column names")
    assert restarted._result_library().get(result["id"])["answer"] == revised


def test_replay_picks_the_complete_summary_instead_of_a_more_relevant_short_answer(tmp_path):
    library = ResultLibrary(tmp_path)
    sources = [{"name": "lesson.pdf", "original_path": "/synthetic/lesson.pdf", "sha256": "abc"}]
    summary = library.save("Summarize the PDF", "Full explanation of the lesson.", sources)
    library.save("Does my summary explain the lesson?", "Yes, the summary explains it.", sources)
    assert [item["id"] for item in library.find("Show my summary")] == [summary["id"]]


@pytest.mark.asyncio
async def test_request_to_reread_a_deleted_original_is_not_answered_as_a_saved_work_edit(tmp_path):
    blob, path, result = await completed_work(tmp_path)
    await say(blob, "/files forget all")
    blob._handle_text_message = AsyncMock(return_value="The original PDF is no longer available.")
    blob.llm.generate_from_messages.reset_mock()
    assert "no longer available" in await say(blob, "Update my timetable by rereading the original PDF.")
    blob._handle_text_message.assert_awaited_once()
    blob.llm.generate_from_messages.assert_not_awaited()
    assert blob._result_library().get(result["id"])["answer"] == TIMETABLE


@pytest.mark.asyncio
async def test_privacy_shield_pauses_saved_result_writes(tmp_path):
    blob = make_blob(tmp_path)
    path = tmp_path / "exam_schedule.pdf"
    make_pdf(path)
    await blob.handle_attachment_drop([str(path)])
    blob.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(is_capture_blocked=lambda: True))
    await say(blob, "Summarize the attached PDF")
    assert not blob._result_library().records()


@pytest.mark.asyncio
async def test_save_failure_is_reported_without_discarding_the_current_answer(tmp_path, capsys):
    blob, path, result = await completed_work(tmp_path)
    blob._result_library().save = Mock(side_effect=OSError("Disk full"))
    assert await say(blob, "Make me a new timetable") == TIMETABLE
    assert "could not be saved for later" in capsys.readouterr().out


def test_results_quota_does_not_evict_previous_work_and_complete_answers_remain_on_disk(tmp_path, monkeypatch):
    import blob.memory.results as module
    monkeypatch.setattr(module, "MAX_RESULTS", 2)
    library = ResultLibrary(tmp_path)
    sources = [{"name": "exam.pdf", "original_path": "/synthetic/exam.pdf", "sha256": "abc"}]
    long_answer = TIMETABLE + "\n" + "Lots of extra detail.\n" * 500 + "\nCOMPLETE END"
    first = library.save("Make an exam timetable", long_answer, sources)
    library.save("Summarize the PDF", "Summary", sources)
    with pytest.raises(ResultError):
        library.save("What is on page 1?", "Third answer", sources)
    assert len(library.records()) == 2
    assert library.get(first["id"])["answer"].endswith("COMPLETE END")
    assert len(library.context("Monday", [first], 1100).encode()) <= 1100
    library.save("Make an updated exam timetable", TIMETABLE, sources)
    assert len(library.records()) == 2
    assert (tmp_path / "document_results.sqlite3").stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_saved_work_does_not_take_over_a_screen_request(tmp_path):
    blob, path, result = await completed_work(tmp_path)
    await say(blob, "/files forget all")
    blob._handle_text_message = AsyncMock(return_value="Fresh screen capture")
    assert await say(blob, "The stuff on my screen is hard; dumb it down") == "Fresh screen capture"
    blob._handle_text_message.assert_awaited_once()
