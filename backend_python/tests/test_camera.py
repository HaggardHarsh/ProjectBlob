import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from blob.ai.orchestrator import BlobOrchestrator
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


@pytest.mark.asyncio
async def test_explicit_camera_command_bypasses_llm():
    vision = MagicMock()
    vision.scan.return_value = {"faces": 1, "full_bodies": 0, "recognized": ["Asha"], "unknown_faces": 0}
    registry = SkillRegistry()
    registry.register(CameraSkill(vision))
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock())

    await orchestrator.handle_user_message(SimpleNamespace(text="/camera scan"))

    vision.scan.assert_called_once_with()
    orchestrator.llm.generate_from_messages.assert_not_awaited()
    assert "Asha" in orchestrator.event_dispatcher.broadcast.call_args.args[0].notification.text
