import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from blob.ai.orchestrator import BlobOrchestrator
from blob.skills.base import SkillResult
from blob.skills.builtin.camera import CameraSkill
from blob.skills.registry import SkillRegistry
from blob.vision.camera import CameraVision


def test_camera_is_disabled_by_default(tmp_path):
    camera = CameraVision(SimpleNamespace(camera_enabled=False, camera_device_index=0, face_db_path=str(tmp_path)))
    result = CameraSkill(camera).execute({"action": "scan"})
    assert not result.success
    assert "disabled" in result.output


def test_forget_deletes_enrolled_samples(tmp_path):
    person_id = "a" * 32
    person_dir = tmp_path / person_id
    person_dir.mkdir()
    (person_dir / "00.png").write_bytes(b"template")
    (tmp_path / "people.json").write_text(json.dumps({person_id: "Asha"}))
    camera = CameraVision(SimpleNamespace(camera_enabled=False, camera_device_index=0, face_db_path=str(tmp_path)))

    result = CameraSkill(camera).execute({"action": "forget", "name": "asha"})
    assert result.success
    assert not person_dir.exists()
    assert camera.list_people() == []


def test_scan_reports_enrolled_name_and_releases_camera(tmp_path):
    person_id = "b" * 32
    person_dir = tmp_path / person_id
    person_dir.mkdir()
    (person_dir / "00.png").write_bytes(b"template")
    (tmp_path / "people.json").write_text(json.dumps({person_id: "Asha"}))
    camera = CameraVision(SimpleNamespace(camera_enabled=True, camera_device_index=0, face_db_path=str(tmp_path)))

    capture = MagicMock()
    capture.isOpened.return_value = True
    capture.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))
    detector = MagicMock()
    detector.empty.return_value = False
    detector.detectMultiScale.return_value = [(10, 10, 50, 50)]
    hog = MagicMock()
    hog.detectMultiScale.return_value = ([(0, 0, 100, 200)], [])
    recognizer = MagicMock()
    recognizer.predict.return_value = (0, 50)
    cv2 = SimpleNamespace(
        VideoCapture=lambda index: capture,
        CascadeClassifier=lambda path: detector,
        data=SimpleNamespace(haarcascades=str(tmp_path)),
        cvtColor=lambda frame, mode: frame[:, :, 0],
        COLOR_BGR2GRAY=6,
        resize=lambda image, size: image,
        HOGDescriptor=lambda: hog,
        HOGDescriptor_getDefaultPeopleDetector=lambda: [],
        imread=lambda path, mode: np.zeros((100, 100), dtype=np.uint8),
        IMREAD_GRAYSCALE=0,
        face=SimpleNamespace(LBPHFaceRecognizer_create=lambda: recognizer),
    )
    camera._cv2 = lambda: cv2

    result = camera.scan()

    assert result == {"faces": 1, "full_bodies": 1, "recognized": ["Asha"], "unknown_faces": 0}
    recognizer.train.assert_called_once()
    capture.release.assert_called_once()


def test_camera_status_checks_a_frame_and_releases_camera(tmp_path):
    camera = CameraVision(SimpleNamespace(camera_enabled=True, camera_device_index=0, face_db_path=str(tmp_path)))
    capture = MagicMock()
    capture.isOpened.return_value = True
    capture.read.return_value = (True, object())
    camera._cv2 = lambda: SimpleNamespace(VideoCapture=lambda index: capture)

    assert "returned a frame" in camera.status()
    capture.read.assert_called_once()
    capture.release.assert_called_once()


@pytest.mark.asyncio
async def test_explicit_camera_request_bypasses_llm():
    skill = SimpleNamespace(name="camera", async_execute=AsyncMock(return_value=SkillResult(
        "Camera scan: 1 face(s). Recognized: Asha.", True, "HAPPY")))
    registry = SkillRegistry()
    registry.register(skill)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock())

    for message_text in ("/camera scan", "Please open my camera", "Can you turn my webcam on?", "Camera", "webcam?", "Can I share my camera?"):
        await orchestrator.handle_user_message(SimpleNamespace(text=message_text))

    assert skill.async_execute.await_count == 6
    skill.async_execute.assert_awaited_with({"action": "scan", "name": ""})
    orchestrator.llm.generate_from_messages.assert_not_awaited()
    assert "Asha" in orchestrator.event_dispatcher.broadcast.call_args.args[0].notification.text


@pytest.mark.asyncio
async def test_camera_permission_question_checks_actual_camera_status():
    skill = SimpleNamespace(name="camera", async_execute=AsyncMock(return_value=SkillResult(
        "Camera device 0 opened and returned a frame.", True, "HAPPY")))
    registry = SkillRegistry()
    registry.register(skill)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock())

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="Is my camera blocked by Wayland permissions?"))

    assert "returned a frame" in answer
    skill.async_execute.assert_awaited_once_with({"action": "status", "name": ""})
    orchestrator.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_camera_call_gives_command_instructions_without_opening_camera():
    skill = SimpleNamespace(name="camera", async_execute=AsyncMock())
    registry = SkillRegistry()
    registry.register(skill)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator._build_context = lambda text: "Context"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(return_value=SimpleNamespace(
        content='```tool_call\n{"tool": "camera", "args": {"action": "scan"}}\n```')))

    answer = await orchestrator.handle_user_message(SimpleNamespace(text="How do I use my camera?"))

    assert "/camera scan" in answer
    skill.async_execute.assert_not_awaited()


def test_camera_is_available_by_default_but_can_be_disabled():
    from blob.config import BlobConfig

    assert BlobConfig().camera_enabled is True
    assert BlobConfig(camera_enabled=False).camera_enabled is False
