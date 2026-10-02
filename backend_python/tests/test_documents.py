"""Document recall must survive a fresh orchestrator and use actual source evidence."""

import hashlib
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from blob.ai.attachments import AttachmentReader
from blob.ipc import blob_service_pb2
from blob.memory.documents import DocumentError, DocumentLibrary
from test_attachments import orchestrator, text_pdf


def source(path, text):
    text_pdf(path, [text])
    return AttachmentReader().prepare([str(path)], "Explain this", vision=False).sources


def chat(directory):
    instance = orchestrator()
    instance.config.documents_dir_path = str(directory)
    instance._handle_text_message = AsyncMock(return_value="Ordinary chat")
    return instance


@pytest.mark.asyncio
async def test_exam_recall_after_restart_uses_saved_pdf_even_if_original_deleted(tmp_path):
    path = tmp_path / "october_2026.pdf"
    text_pdf(path, ["HDL ECE 201: Monday 05.10.2026 at 9:30 am.", "Circuits ECE 202: Wednesday 07.10.2026 at 9:30 am."])
    directory = tmp_path / "library"
    first = chat(directory)
    first.llm.generate_from_messages.return_value = SimpleNamespace(content="Incorrect answer: exams are in January. (HAPPY)")
    await first.handle_attachment_drop([str(path)])
    first.episodic.add_episode.assert_not_called()
    record = DocumentLibrary(directory).records()[0]
    assert "January" not in record["search_text"]
    assert "HDL ECE 201" in record["search_text"]
    path.unlink()  # Recalling must not depend on the user's original path.

    restarted = chat(directory)
    assert not getattr(restarted, "_active_attachments", [])
    await restarted.handle_user_message(blob_service_pb2.UserMessage(text="What is my exam timetable?"))
    messages, system = restarted.llm.generate_from_messages.call_args.args
    assert "HDL ECE 201: Monday 05.10.2026 at 9:30 am" in messages[-1]["content"]
    assert "october_2026.pdf, page 1" in messages[-1]["content"]
    assert "January" not in str(messages)
    assert "Current local date and time" in system
    assert "reopen saved sources after" in system
    assert restarted._active_attachments == [str(DocumentLibrary(directory).path_for(record))]
    restarted._handle_text_message.assert_not_awaited()
    restarted.episodic.add_episode.assert_not_called()

    await restarted.handle_user_message(blob_service_pb2.UserMessage(text="Explain page 2"))
    evidence = restarted.llm.generate_from_messages.call_args.args[0][-1]["content"]
    assert "Circuits ECE 202" in evidence
    assert "october_2026.pdf, page 2" in evidence
    assert "october_2026.pdf, page 1" not in evidence


@pytest.mark.asyncio
async def test_saved_commands_open_and_forget_without_ordinary_model_calls(tmp_path):
    original = tmp_path / "timetable.pdf"
    directory = tmp_path / "library"
    library = DocumentLibrary(directory)
    library.remember(source(original, "HDL examination Monday"))
    record = library.records()[0]
    instance = chat(directory)
    reply = await instance.handle_user_message(blob_service_pb2.UserMessage(text="/files saved"))
    assert record["id"] in reply and original.name in reply
    instance.llm.generate_from_messages.assert_not_awaited()
    await instance.handle_user_message(blob_service_pb2.UserMessage(text=f"/files open {record['id']}"))
    assert instance._active_attachments == [str(library.path_for(record))]
    instance.llm.generate_from_messages.assert_awaited_once()
    reply = await instance.handle_user_message(blob_service_pb2.UserMessage(text=f"/files forget {record['id']}"))
    assert "Deleted saved copies" in reply
    assert original.is_file()
    assert not library.path_for(record).exists()
    assert not library.records()
    assert not instance._active_attachments
    assert not instance._recent_turns
    instance.llm.generate_from_messages.assert_awaited_once()
    restarted = chat(directory)
    await restarted.handle_user_message(blob_service_pb2.UserMessage(text="Show my timetable"))
    restarted._handle_text_message.assert_awaited_once()
    restarted.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_redropping_updated_original_replaces_recalled_copy(tmp_path):
    original = tmp_path / "exam_schedule.pdf"
    directory = tmp_path / "library"
    first = chat(directory)
    text_pdf(original, ["Exam Monday"])
    await first.handle_attachment_drop([str(original)])
    library = DocumentLibrary(directory)
    old = library.records()[0]
    restarted = chat(directory)
    await restarted.handle_user_message(blob_service_pb2.UserMessage(text="Show my exam schedule"))
    text_pdf(original, ["Exam Tuesday - revised schedule"])
    await restarted.handle_attachment_drop([str(original)])
    assert restarted._active_attachments == [str(original)]
    evidence = restarted.llm.generate_from_messages.call_args.args[0][-1]["content"]
    assert "Exam Tuesday" in evidence
    assert evidence.count("exam_schedule.pdf, page 1") == 1
    assert len(library.records()) == 1
    assert library.records()[0]["id"] != old["id"]
    assert not library.path_for(old).exists()


@pytest.mark.asyncio
async def test_corrupt_saved_file_fails_instead_of_answering_from_old_model_text(tmp_path):
    original = tmp_path / "exams.pdf"
    directory = tmp_path / "library"
    library = DocumentLibrary(directory)
    library.remember(source(original, "Exam Monday"))
    library.path_for(library.records()[0]).write_bytes(b"tampered source")
    instance = chat(directory)
    reply = await instance.handle_user_message(blob_service_pb2.UserMessage(text="Show my exam schedule"))
    assert "missing or changed" in reply
    assert "Drop that file again" in reply
    instance.llm.generate_from_messages.assert_not_awaited()
    instance._handle_text_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrelated_chat_and_controls_do_not_send_saved_sources(tmp_path):
    original = tmp_path / "exams.pdf"
    directory = tmp_path / "library"
    DocumentLibrary(directory).remember(source(original, "HDL exam Monday"))
    instance = chat(directory)
    for question in ["Hello Blob", "What day is it?", "Remind me to study my exam at 9", "What do you know about me?"]:
        await instance.handle_user_message(blob_service_pb2.UserMessage(text=question))
    assert instance._handle_text_message.await_count == 4
    instance.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_failure_keeps_analysis_working_and_reports_no_restart_storage(tmp_path, monkeypatch, capsys):
    original = tmp_path / "exam_schedule.pdf"
    text_pdf(original, ["HDL exam Monday"])
    instance = chat(tmp_path / "library")
    monkeypatch.setattr(instance._document_library(), "remember", lambda sources: (_ for _ in ()).throw(OSError("Disk full")))
    reply = await instance.handle_attachment_drop([str(original)])
    assert "Ohm's law" in reply
    output = capsys.readouterr().out
    assert "could not be saved for restart" in output
    assert "Saved local source copies" not in output


def test_storage_permissions_duplicate_sources_search_and_forget_all(tmp_path):
    original = tmp_path / "physics.pdf"
    sources = source(original, "Electromagnetism voltage resistance")
    library = DocumentLibrary(tmp_path / "library")
    assert library.remember(sources)
    assert library.remember(sources)
    record = library.records()[0]
    assert len(library.records()) == 1
    saved = library.path_for(record)
    assert saved.read_bytes() == original.read_bytes()
    assert record["sha256"] == hashlib.sha256(original.read_bytes()).hexdigest()
    assert saved.stat().st_mode & 0o777 == 0o600
    assert saved.parent.stat().st_mode & 0o777 == 0o700
    assert library.root.stat().st_mode & 0o777 == 0o700
    assert (library.root / "index.sqlite3").stat().st_mode & 0o777 == 0o600
    assert library.find("Explain electromagnetism")[0]["id"] == record["id"]
    assert library.find("Can you show that document again?")[0]["id"] == record["id"]
    assert not library.find("Hello Blob")
    cached = AttachmentReader().prepare([str(saved)], "Explain", vision=False)
    assert not library.remember(cached.sources)
    library.forget("all")
    assert not library.records()
    assert original.exists()


def test_quota_rejection_preserves_previous_saved_files(tmp_path, monkeypatch):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    library = DocumentLibrary(tmp_path / "library")
    library.remember(source(first, "First schedule"))
    previous = library.records()
    monkeypatch.setattr("blob.memory.documents.MAX_DOCUMENTS", 1)
    with pytest.raises(DocumentError, match="full"):
        library.remember(source(second, "Second schedule"))
    assert library.records() == previous
    assert library.reopen(previous)
    monkeypatch.setattr("blob.memory.documents.MAX_DOCUMENTS", 20)
    monkeypatch.setattr("blob.memory.documents.MAX_LIBRARY_BYTES", 1)
    with pytest.raises(DocumentError, match="full"):
        library.remember(source(second, "Second schedule"))
    assert library.records() == previous


def test_failed_index_commit_removes_unindexed_new_copy_and_preserves_old_source(tmp_path, monkeypatch):
    original = tmp_path / "schedule.pdf"
    library = DocumentLibrary(tmp_path / "library")
    library.remember(source(original, "Exam Monday"))
    previous = library.records()
    previous_bytes = library.path_for(previous[0]).read_bytes()
    replacement = source(original, "Exam Tuesday - revised")
    connect = library._connect
    calls = 0

    def failing_connect():
        nonlocal calls
        calls += 1
        if calls == 3:  # Initialization and previous records succeed; the final write fails.
            raise sqlite3.OperationalError("Disk full")
        return connect()

    monkeypatch.setattr(library, "_connect", failing_connect)
    with pytest.raises(sqlite3.OperationalError, match="Disk full"):
        library.remember(replacement)
    monkeypatch.setattr(library, "_connect", connect)
    assert library.records() == previous
    assert library.path_for(previous[0]).read_bytes() == previous_bytes
    assert list(library.root.glob("*/*.pdf")) == [library.path_for(previous[0])]


def test_recall_search_uses_distinctive_content_and_keeps_pdf_filename(tmp_path):
    first, second = tmp_path / "schedule.pdf", tmp_path / "notes.pdf"
    library = DocumentLibrary(tmp_path / "library")
    library.remember(source(first, "HDL ECE 201 exam Monday"))
    library.remember(source(second, "Thermodynamics pressure volume"))
    found = library.find("Show my exam timetable again")
    assert [record["name"] for record in found] == ["schedule.pdf"]
    assert [record["name"] for record in library.find("Explain thermodynamics")] == ["notes.pdf"]
    assert not library.find("Show that PDF again")  # Multiple files require a more specific question.


@pytest.mark.asyncio
async def test_ambiguous_document_reference_lists_saved_choices(tmp_path):
    directory = tmp_path / "library"
    library = DocumentLibrary(directory)
    library.remember(source(tmp_path / "circuits.pdf", "Voltage resistance"))
    library.remember(source(tmp_path / "mechanics.pdf", "Velocity acceleration"))
    instance = chat(directory)
    reply = await instance.handle_user_message(blob_service_pb2.UserMessage(text="Show that PDF again"))
    assert "circuits.pdf" in reply and "mechanics.pdf" in reply
    assert "Which one" in reply
    instance.llm.generate_from_messages.assert_not_awaited()
    instance._handle_text_message.assert_not_awaited()


def test_index_cannot_escape_library_or_follow_symlink_directory(tmp_path):
    library = DocumentLibrary(tmp_path / "library")
    for name in ["..", ".", "", "../outside.pdf", "/outside.pdf"]:
        with pytest.raises(DocumentError, match="invalid"):
            library.path_for({"id": "a" * 16, "name": name})
    library.root.mkdir()
    (library.root / ("a" * 16)).symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(DocumentError, match="folder has changed"):
        library.path_for({"id": "a" * 16, "name": "outside.pdf"})


@pytest.mark.asyncio
async def test_image_sources_can_be_reopened_for_vision_after_restart(tmp_path):
    original = tmp_path / "exam_timetable.png"
    Image.new("RGB", (40, 30), "blue").save(original)
    directory = tmp_path / "library"
    engine = SimpleNamespace(generate_from_messages=AsyncMock(return_value=SimpleNamespace(content="An exam timetable. (HAPPY)")))
    first = chat(directory)
    first.llm.vision_engine.return_value = engine
    await first.handle_attachment_drop([str(original)])
    original.unlink()
    restarted = chat(directory)
    restarted.llm.vision_engine.return_value = engine
    await restarted.handle_user_message(blob_service_pb2.UserMessage(text="What does my exam timetable image show?"))
    parts = engine.generate_from_messages.call_args.args[0][-1]["content"]
    assert any(part["type"] == "image_url" for part in parts)
    assert any("exam_timetable.png" in part.get("text", "") for part in parts)
