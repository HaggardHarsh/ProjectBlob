import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from blob.ai.orchestrator import BlobOrchestrator, _requested_camera_action
from blob.privacy.controls import PrivacyControls
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


def test_zero_face_scan_explains_camera_opened_but_no_face_detected():
    vision = SimpleNamespace(scan=lambda: {
        "faces": 0, "full_bodies": 0, "recognized": [], "unknown_faces": 0,
    })

    result = CameraSkill(vision).execute({"action": "scan"})

    assert result.success
    assert "Camera opened successfully" in result.output
    assert "No face was detected" in result.output
    assert "good light" in result.output


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
async def test_camera_retry_and_face_recognition_requests_repeat_direct_scan():
    scan_result = "Camera opened successfully. Scan: 0 face(s). Recognized: none."
    skill = SimpleNamespace(name="camera", async_execute=AsyncMock(return_value=SkillResult(
        scan_result, True, "HAPPY")))
    registry = SkillRegistry()
    registry.register(skill)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock())

    requests = (
        "Can you look at me with camera",
        "try again",
        "no try camera again",
        "recognize my face with camera",
    )
    replies = [await orchestrator.handle_user_message(SimpleNamespace(text=text))
               for text in requests]

    assert replies == [scan_result] * len(requests)
    assert skill.async_execute.await_count == len(requests)
    assert all(call.args[0] == {"action": "scan", "name": ""}
               for call in skill.async_execute.await_args_list)
    orchestrator.llm.generate_from_messages.assert_not_awaited()
    orchestrator.episodic.add_episode.assert_not_called()
    assert [turn["content"] for turn in orchestrator._recent_turns if turn["role"] == "user"] == list(requests)


@pytest.mark.asyncio
async def test_try_again_does_not_reopen_camera_after_unrelated_turn():
    skill = SimpleNamespace(name="camera", async_execute=AsyncMock(return_value=SkillResult(
        "Camera opened successfully.", True, "HAPPY")))
    registry = SkillRegistry()
    registry.register(skill)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.screen_sampler = None
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "Context"
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(
        return_value=SimpleNamespace(content="Okay.")))

    await orchestrator.handle_user_message(SimpleNamespace(text="Look at me with camera"))
    await orchestrator.handle_user_message(SimpleNamespace(text="Hi"))
    await orchestrator.handle_user_message(SimpleNamespace(text="Try again"))

    skill.async_execute.assert_awaited_once_with({"action": "scan", "name": ""})
    assert orchestrator.llm.generate_from_messages.await_count == 2


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
@pytest.mark.parametrize("question", [
    "How do I use my camera?",
    "How do I recognize my face with camera?",
])
async def test_model_camera_call_gives_command_instructions_without_opening_camera(question):
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

    answer = await orchestrator.handle_user_message(SimpleNamespace(text=question))

    assert "/camera scan" in answer
    skill.async_execute.assert_not_awaited()


def test_camera_is_available_by_default_but_can_be_disabled():
    from blob.config import BlobConfig

    assert BlobConfig().camera_enabled is True
    assert BlobConfig(camera_enabled=False).camera_enabled is False


def camera_chat(tmp_path, *, cloud_enabled=True):
    skill = SimpleNamespace(name="camera", async_execute=AsyncMock(return_value=SkillResult(
        "Camera opened successfully. Scan: 1 face(s). Recognized: none. Unknown faces: 1.", True, "HAPPY")))
    controls = PrivacyControls(tmp_path / "privacy.json")
    controls.update(cloud_enabled=cloud_enabled)
    registry = SkillRegistry(tmp_path / "skills", controls=controls)
    registry.register(skill)
    orchestrator = BlobOrchestrator.__new__(BlobOrchestrator)
    orchestrator.controls = controls
    orchestrator.guardrails = SimpleNamespace(sanitize_input=lambda text: text, filter_output=lambda text: text)
    orchestrator.skill_registry = registry
    orchestrator.screen_sampler = None
    orchestrator.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    orchestrator.dispatch_emote = AsyncMock()
    orchestrator.episodic = SimpleNamespace(add_episode=MagicMock())
    orchestrator._build_context = lambda text: "No relevant memories."
    orchestrator._build_system_prompt = lambda: "System"
    orchestrator.llm = SimpleNamespace(generate_from_messages=AsyncMock(return_value=SimpleNamespace(content="Okay.")))
    return orchestrator, skill


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["Can you recognize me", "Could you recognise me?", "Recognize me please"])
@pytest.mark.parametrize("cloud_enabled", [False, True])
async def test_recognize_me_runs_local_camera_scan_even_with_files_and_cloud_off(tmp_path, text, cloud_enabled):
    orchestrator, skill = camera_chat(tmp_path, cloud_enabled=cloud_enabled)
    orchestrator._active_attachments = ["/some/exam_schedule.pdf"]
    orchestrator._handle_attachment_message = AsyncMock(side_effect=AssertionError("Camera request analyzed a file"))
    answer = await orchestrator.handle_user_message(SimpleNamespace(text=text))
    assert answer.startswith("Camera opened successfully.")
    skill.async_execute.assert_awaited_once_with({"action": "scan", "name": ""})
    orchestrator.llm.generate_from_messages.assert_not_awaited()
    orchestrator._handle_attachment_message.assert_not_awaited()
    orchestrator.episodic.add_episode.assert_not_called()


@pytest.mark.asyncio
async def test_yes_it_is_retries_only_immediately_after_real_camera_request(tmp_path):
    orchestrator, skill = camera_chat(tmp_path)
    await orchestrator.handle_user_message(SimpleNamespace(text="Can you recognize me"))
    await orchestrator.handle_user_message(SimpleNamespace(text="yes it is"))
    assert skill.async_execute.await_count == 2
    # An unrelated local command must also break the camera follow-up context.
    await orchestrator.handle_user_message(SimpleNamespace(text="/skills"))
    await orchestrator.handle_user_message(SimpleNamespace(text="yes it is"))
    assert skill.async_execute.await_count == 2
    orchestrator.llm.generate_from_messages.assert_awaited_once()


@pytest.mark.asyncio
async def test_recognition_request_respects_manual_pause(tmp_path):
    orchestrator, skill = camera_chat(tmp_path)
    orchestrator.controls.update(paused=True)
    answer = await orchestrator.handle_user_message(SimpleNamespace(text="Can you recognize me"))
    assert "Privacy pause is active" in answer
    skill.async_execute.assert_not_awaited()
    orchestrator.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.parametrize("text", [
    "Don't recognize me",
    "Don’t open my camera",
    "Never scan my face",
    "How do I recognize my face with camera?",
    "Can you recognize me from our previous chats?",
    "Can you recognize me in the attached photo?",
])
def test_denials_memory_and_photo_questions_are_not_live_camera_requests(text):
    assert _requested_camera_action(text) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("claim", [
    "I'll try to use the camera to see if I can recognize you.",
    "I tried to access the camera, but I didn't get a clear view of your face.",
    "I'm not seeing a clear face right now.",
    "Attempting to access the camera…",
])
async def test_model_camera_claims_are_replaced_before_streamed_or_final_output(tmp_path, capsys, claim):
    orchestrator, skill = camera_chat(tmp_path)
    async def streamed(messages, system):
        yield claim
    orchestrator.llm.generate_from_messages_stream = streamed
    answer = await orchestrator.handle_user_message(SimpleNamespace(text="How do I use my camera?"))
    assert answer.startswith("I haven't opened or read the camera for this request.")
    assert claim not in capsys.readouterr().out
    skill.async_execute.assert_not_awaited()


def test_unknown_face_reports_enrollment_instruction_without_enrolling():
    vision = SimpleNamespace(scan=lambda: {"faces": 1, "full_bodies": 0, "recognized": [], "unknown_faces": 1},
                             enroll=MagicMock())
    result = CameraSkill(vision).execute({"action": "scan"})
    assert result.success and "Unknown faces: 1" in result.output
    assert "/camera enroll <name>" in result.output
    vision.enroll.assert_not_called()
