import asyncio
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from blob.ai.orchestrator import BlobOrchestrator
from blob.ipc import blob_service_pb2
from blob.skills.base import SkillResult
from blob.skills.builtin.reminder import ReminderSkill
from blob.skills.builtin.shell_command import ShellCommandSkill
from blob.skills.builtin.screen_capture import ScreenCaptureSkill
from blob.skills.builtin.weather import WeatherSkill
from blob.skills.commands import handle_skill_command
from blob.skills.contracts import object_schema
from blob.skills.registry import SkillRegistry
from blob.skills.process import run_command
from blob.skills.validator import SkillValidator
from test_skill_registry import SKILL_YAML


@pytest.mark.asyncio
async def test_invalid_arguments_never_reach_skill_and_history_does_not_store_contents():
    skill = WeatherSkill()
    skill.async_execute = AsyncMock(return_value=SkillResult("Delhi: Clear", True))
    registry = SkillRegistry()
    registry.register(skill)
    for args in ({"location": 42}, {"location": "private city", "secret": "private"}, []):
        result = await registry.execute("weather", args)
        assert not result.success
    skill.async_execute.assert_not_awaited()
    result = await registry.execute("weather", {"location": "Delhi"}, source="terminal")
    assert result.success
    skill.async_execute.assert_awaited_once_with({"location": "Delhi"})
    assert all(set(item) == {"name", "success", "duration_ms", "source"} for item in registry.history)
    assert "Delhi" not in str(registry.history)
    assert "private" not in str(registry.history)


@pytest.mark.asyncio
async def test_runtime_timeout_cancels_async_work_and_reports_failure():
    cancelled = asyncio.Event()

    async def slow(args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    registry = SkillRegistry()
    registry.register(SimpleNamespace(name="slow", description="Slow", async_execute=slow,
                                      argument_schema=object_schema(), timeout_seconds=0.01))
    result = await registry.execute("slow", {})
    assert not result.success and "timed out" in result.output
    assert cancelled.is_set()
    assert not registry.history[-1]["success"]


@pytest.mark.asyncio
async def test_runtime_preserves_cancellation_and_bounds_utf8_output():
    registry = SkillRegistry()
    registry.register(SimpleNamespace(name="large", description="Large", async_execute=AsyncMock(
        return_value=SkillResult("日本語 " * 4000, True, "INVALID"))))
    result = await registry.execute("large", {})
    assert result.success and result.emote_suggestion == "IDLE"
    assert len(result.output.encode("utf-8")) <= 8000
    assert result.output.endswith("[Additional skill output omitted.]")
    registry.register(SimpleNamespace(name="cancelled", description="Cancelled", async_execute=AsyncMock(
        side_effect=asyncio.CancelledError)))
    with pytest.raises(asyncio.CancelledError):
        await registry.execute("cancelled", {})


@pytest.mark.asyncio
async def test_model_cannot_open_camera_but_explicit_terminal_command_can():
    skill = SimpleNamespace(name="camera", description="Camera", async_execute=AsyncMock(
        return_value=SkillResult("Camera opened", True)), model_callable=False)
    registry = SkillRegistry()
    registry.register(skill)
    assert "camera" not in registry.prompt_text()
    assert not (await registry.execute("camera", {})).success
    skill.async_execute.assert_not_called()
    assert (await registry.execute("camera", {}, source="terminal")).success
    skill.async_execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_terminal_hub_and_reminder_commands_work_with_active_files_and_no_model(tmp_path):
    skill = ReminderSkill(tmp_path / "reminders.sqlite3")
    registry = SkillRegistry()
    registry.register(skill)
    instance = BlobOrchestrator.__new__(BlobOrchestrator)
    instance.skill_registry = registry
    instance._active_attachments = ["exam_schedule.pdf"]
    instance._send_direct_response = AsyncMock(side_effect=lambda output, emote: output)
    instance.llm = SimpleNamespace(generate_from_messages=AsyncMock())
    instance.dispatch_emote = AsyncMock()
    try:
        for text in ("/skills", "/skills reminder", "/reminders help", "/reminders every 30 Stretch"):
            result = await instance.handle_user_message(blob_service_pb2.UserMessage(text=text))
            assert result
        identifier = skill.reminders[0]["id"]
        assert (await instance.handle_user_message(blob_service_pb2.UserMessage(text="/reminders"))).find(identifier) >= 0
        snoozed = await instance.handle_user_message(blob_service_pb2.UserMessage(text=f"/reminders snooze {identifier} 10"))
        assert "Snoozed" in snoozed
        cancelled = await instance.handle_user_message(blob_service_pb2.UserMessage(text=f"/reminders cancel {identifier}"))
        assert "Cancelled" in cancelled and not skill.reminders
        history = await instance.handle_user_message(blob_service_pb2.UserMessage(text="/skills history"))
        assert "reminder" in history and "terminal" in history
        instance.llm.generate_from_messages.assert_not_awaited()
    finally:
        await registry.close()


@pytest.mark.asyncio
async def test_yaml_typed_arguments_defaults_and_prompt_contract(tmp_path):
    source = tmp_path / "number.skill.yaml"
    source.write_text(SKILL_YAML.replace("{text}", "{count}").replace(
        "name: text\n          required: true", "name: count\n          type: integer\n          required: false\n          default: 3\n          minimum: 1\n          maximum: 10"))
    registry = SkillRegistry(tmp_path / "installed")
    registry.install_file(source)
    result = await registry.execute("echo_example.echo_text", {})
    assert result.success and "3" in result.output
    for args in ({"count": "3"}, {"count": 0}, {"count": 11}, {"count": True}):
        assert not (await registry.execute("echo_example.echo_text", args)).success
    prompt = registry.prompt_text()
    assert '"type":"integer"' in prompt and '"minimum":1' in prompt


@pytest.mark.parametrize("command", [
    "git branch -D main", "git branch new_branch", "git branch -m renamed", "git branch --delete main",
    "git diff --output=changed.txt", "git diff --ext-diff", "git log --textconv", "git log -o changes.txt",
    "git log --show-signature", "git log --format=%G?",
    "find . -fls files.txt", "find . -delete", "date --set=2026-10-05", "date -s2026-10-05", "date 100509302026",
])
def test_disallowed_commands_fail_before_starting_process(command, monkeypatch):
    run = MagicMock(side_effect=AssertionError("Disallowed command reached subprocess"))
    monkeypatch.setattr("blob.skills.builtin.shell_command.run_command", run)
    assert not ShellCommandSkill().execute({"command": command}).success
    run.assert_not_called()
    source = SKILL_YAML.replace('command: "echo {text}"', f'command: "{command}"')
    with pytest.raises(ValueError, match="not allowed"):
        SkillValidator().validate(source)


def test_git_diff_ignores_configured_external_driver(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init")
    file = tmp_path / "lesson.txt"
    file.write_text("original\n")
    git("add", "lesson.txt")
    git("-c", "user.name=Blob Test", "-c", "user.email=blob@example.invalid", "commit", "-m", "Initial")
    marker = tmp_path / "driver_ran"
    driver = tmp_path / "driver.sh"
    driver.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    driver.chmod(0o700)
    git("config", "diff.external", str(driver))
    file.write_text("changed\n")
    monkeypatch.chdir(tmp_path)
    result = ShellCommandSkill().execute({"command": "git diff"})
    assert result.success
    assert "+changed" in result.output
    assert not marker.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/skills run weather []", "/skills run weather {broken", "/skills unknown", "/reminders add nan Study"])
async def test_invalid_terminal_commands_fail_without_side_effects(text):
    registry = SkillRegistry()
    weather = WeatherSkill()
    weather.async_execute = AsyncMock()
    registry.register(weather)
    reminder = ReminderSkill()
    registry.register(reminder)
    try:
        assert not (await handle_skill_command(registry, text)).success
        weather.async_execute.assert_not_called()
        assert reminder.reminders == []
    finally:
        await registry.close()


def test_all_bundled_skill_contracts_still_load(tmp_path):
    registry = SkillRegistry(tmp_path / "installed")
    assert registry.load_directory(Path(__file__).resolve().parents[2] / "skills") == []
    assert len(registry.skills) == 12


def test_process_output_is_bounded_while_large_file_is_read(tmp_path):
    source = tmp_path / "large.txt"
    source.write_text("日本語 " * 200000)
    result = run_command(["cat", str(source)])
    assert result.returncode == 0
    assert len(result.stdout.encode("utf-8")) <= 8000
    assert result.stdout.endswith("[Additional command output omitted.]")


def test_process_deadline_stops_process_and_reader():
    with pytest.raises(subprocess.TimeoutExpired):
        run_command([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.05)


@pytest.mark.parametrize("argument", [
    "required: 'yes'", "type: [integer]", "enum: []",
    "type: integer\n          minimum: 10\n          maximum: 1",
    "type: integer\n          enum: ['one']", "type: number\n          minimum: .nan",
])
def test_invalid_skill_upgrade_preserves_working_tool_and_installed_file(tmp_path, argument):
    source = tmp_path / "example.skill.yaml"
    source.write_text(SKILL_YAML)
    registry = SkillRegistry(tmp_path / "installed")
    registry.install_file(source)
    installed = tmp_path / "installed" / "echo_example.skill.yaml"
    previous = installed.read_bytes()
    source.write_text(SKILL_YAML.replace("required: true", argument))
    with pytest.raises(ValueError):
        registry.install_file(source)
    assert installed.read_bytes() == previous
    assert registry.get_skill("echo_example.echo_text").execute({"text": "Still works"}).success


@pytest.mark.asyncio
async def test_screen_ocr_keeps_loop_responsive_and_owns_image_until_worker_finishes():
    from PIL import Image
    image = Image.new("RGB", (20, 20), "white")
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def read(capture):
        started.set()
        release.wait(2)
        try:
            assert capture.getpixel((0, 0)) == (255, 255, 255)
            return "Voltage equals current times resistance"
        finally:
            finished.set()

    skill = ScreenCaptureSkill()
    skill.set_sampler(SimpleNamespace(capture=AsyncMock(return_value=image),
        privacy_shield=SimpleNamespace(is_capture_blocked=lambda: False), get_active_window_title=lambda: "Lesson"))
    skill.set_ocr(SimpleNamespace(extract_text=read))
    task = asyncio.create_task(skill.async_execute({}))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        assert not task.done()
        await asyncio.wait_for(asyncio.sleep(0.01), 0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert image.getpixel((0, 0)) == (255, 255, 255)
    finally:
        release.set()
        await asyncio.to_thread(finished.wait, 1)


@pytest.mark.asyncio
async def test_screen_privacy_change_during_ocr_discards_extracted_text():
    from PIL import Image
    started, release = threading.Event(), threading.Event()
    blocked = [False]

    def read(image):
        started.set()
        release.wait(2)
        return "Private content"

    skill = ScreenCaptureSkill()
    skill.set_sampler(SimpleNamespace(capture=AsyncMock(return_value=Image.new("RGB", (20, 20))),
        privacy_shield=SimpleNamespace(is_capture_blocked=lambda: blocked[0]), get_active_window_title=lambda: "Lesson"))
    skill.set_ocr(SimpleNamespace(extract_text=read))
    task = asyncio.create_task(skill.async_execute({}))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        blocked[0] = True
    finally:
        release.set()
    result = await asyncio.wait_for(task, 1)
    assert not result.success
    assert "privacy shield" in result.output
    assert "Private content" not in result.output


@pytest.mark.asyncio
async def test_chat_cancellation_uses_confirmed_list_id_and_preserves_other_reminders(tmp_path):
    reminder = ReminderSkill(tmp_path / "reminders.sqlite3")
    await reminder.async_execute({"message": "Stretch", "minutes": 30})
    await reminder.async_execute({"message": "HDL exam", "minutes": 60})
    selected = reminder.reminders[0]["id"]
    registry = SkillRegistry()
    registry.register(reminder)
    instance = BlobOrchestrator.__new__(BlobOrchestrator)
    instance.skill_registry = registry
    instance._active_attachments = ["exam_schedule.pdf"]
    instance.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    instance.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    instance.dispatch_emote = AsyncMock()
    instance._build_context = lambda text: ""
    instance._build_system_prompt = lambda: "System"
    instance._remember_turn = MagicMock()
    instance.llm = SimpleNamespace(generate_from_messages=AsyncMock(side_effect=[
        SimpleNamespace(content='{"tool":"reminder","args":{"action":"list"}}'),
        SimpleNamespace(content='{"tool":"reminder","args":{"action":"cancel","id":"' + selected + '"}}'),
    ]))
    try:
        response = await instance.handle_user_message(blob_service_pb2.UserMessage(text="Cancel my reminder to stretch"))
        assert "Cancelled" in response and selected in response
        assert [record["message"] for record in reminder.reminders] == ["HDL exam"]
        assert instance.llm.generate_from_messages.await_count == 2
        second_prompt = instance.llm.generate_from_messages.await_args_list[1].args[0]
        assert selected in second_prompt[-1]["content"]
        assert "executed successfully" in second_prompt[-1]["content"]
    finally:
        await registry.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("user_text, action", [("Hello Blob", "set"), ("List my reminders", "cancel"),
                                              ("Remind me to cancel a subscription in 10 minutes", "cancel")])
async def test_model_cannot_create_unrequested_reminder_or_change_wrong_action(user_text, action):
    reminder = ReminderSkill()
    reminder.async_execute = AsyncMock()
    registry = SkillRegistry()
    registry.register(reminder)
    instance = BlobOrchestrator.__new__(BlobOrchestrator)
    instance.skill_registry = registry
    instance.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    instance.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    instance.dispatch_emote = AsyncMock()
    instance._build_context = lambda text: ""
    instance._build_system_prompt = lambda: "System"
    instance._remember_turn = MagicMock()
    instance.llm = SimpleNamespace(generate_from_messages=AsyncMock(side_effect=[
        SimpleNamespace(content='{"tool":"reminder","args":{"action":"' + action + '","message":"Study","minutes":10}}'),
        SimpleNamespace(content="I couldn't complete that action."),
    ]))
    try:
        # Exercise model authorization even when the ordinary relative-timer
        # route can now satisfy this request without a model.
        await instance._handle_text_message(blob_service_pb2.UserMessage(text=user_text))
        reminder.async_execute.assert_not_called()
        assert reminder.reminders == []
    finally:
        await registry.close()
