"""Selected photos use local enrollment evidence, never a model identity guess."""

from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
from PIL import Image
import pytest

from blob.ipc import blob_service_pb2 as pb
from blob.privacy.controls import PrivacyBlocked, PrivacyControls
from blob.skills.builtin.camera import CameraSkill
from blob.skills.registry import SkillRegistry
from blob.vision.camera import CameraError, CameraVision
from test_attachments import orchestrator


def image_bytes(size=(120, 80), *, exif=None):
    output = BytesIO()
    Image.new("RGB", size, "blue").save(output, "JPEG", **({"exif": exif} if exif else {}))
    return output.getvalue()


def camera(tmp_path, *, enabled=True):
    vision = CameraVision(SimpleNamespace(camera_enabled=enabled, camera_device_index=0,
                                         face_db_path=str(tmp_path / "faces")))
    vision._open = MagicMock(side_effect=AssertionError("Selected photo opened webcam"))
    return vision


def prepared_camera(tmp_path, *, predictions=((0, 30),)):
    vision = camera(tmp_path)
    vision._load_index = lambda: {"a" * 32: "ExamplePerson"}
    cv2 = SimpleNamespace(COLOR_RGB2BGR=4, cvtColor=lambda image, _: image[:, :, ::-1])
    vision._cv2 = lambda: cv2
    vision._face_detector = lambda _: object()
    boxes = [(10 + 50 * index, 10, 40, 40) for index in range(len(predictions))]
    vision._faces = MagicMock(return_value=(np.zeros((80, 400), np.uint8), list(reversed(boxes))))
    vision._crop = lambda *args: np.zeros((100, 100), np.uint8)
    recognizer = SimpleNamespace(predict=MagicMock(side_effect=predictions))
    vision._trained_recognizer = MagicMock(return_value=(recognizer, {0: "ExamplePerson"}))
    return vision


def test_photo_matches_are_ordered_and_uncertain_scores_stay_unknown(tmp_path):
    vision = prepared_camera(tmp_path, predictions=((0, 65), (0, 65.1), (0, float("nan")),
                                                  (0, float("inf")), (0, -1), (7, 20)))
    result = vision.match_image(image_bytes())
    assert result["enrolled"] is True
    assert [face["name"] for face in result["faces"]] == ["ExamplePerson", None, None, None, None, None]
    assert [face["box"][0] for face in result["faces"]] == [10, 60, 110, 160, 210, 260]
    vision._open.assert_not_called()
    assert not vision.face_db_path.exists()


def test_photo_decode_applies_orientation_and_bounds_size(tmp_path):
    vision = prepared_camera(tmp_path)
    exif = Image.Exif()
    exif[274] = 6  # Rotate a portrait stored sideways.
    vision.match_image(image_bytes((2400, 1200), exif=exif))
    frame = vision._faces.call_args.args[2]
    assert frame.shape == (1600, 800, 3)
    assert frame[0, 0, 0] > 240  # RGB blue converted to OpenCV BGR.


def test_absent_profiles_do_not_load_opencv_or_create_face_storage(tmp_path):
    vision = camera(tmp_path)
    vision._cv2 = MagicMock(side_effect=AssertionError("No enrollment needs no recognition dependency"))
    assert vision.match_image(image_bytes()) == {"enrolled": False, "faces": []}
    vision._cv2.assert_not_called()
    assert not vision.face_db_path.exists()


def test_absent_samples_and_absent_faces_never_produce_a_name(tmp_path):
    vision = prepared_camera(tmp_path)
    vision._trained_recognizer.return_value = (None, {0: "ExamplePerson"})
    assert vision.match_image(image_bytes())["faces"][0]["name"] is None
    vision._trained_recognizer.reset_mock()
    vision._faces.return_value = (np.zeros((80, 120), np.uint8), [])
    assert vision.match_image(image_bytes()) == {"enrolled": True, "faces": []}
    vision._trained_recognizer.assert_not_called()


def test_corrupt_photo_and_disabled_camera_fail_without_webcam_access(tmp_path):
    vision = prepared_camera(tmp_path)
    with pytest.raises(CameraError, match="could not be decoded"):
        vision.match_image(b"not an image")
    vision._faces.assert_not_called()
    disabled = camera(tmp_path, enabled=False)
    with pytest.raises(CameraError, match="disabled"):
        disabled.match_image(image_bytes())
    disabled._open.assert_not_called()


def test_native_lbph_matches_synthetic_sample_without_writing_or_opening_camera(tmp_path):
    cv2 = pytest.importorskip("cv2")
    if not hasattr(cv2, "face"):
        pytest.skip("Optional OpenCV recognition dependency is not installed")
    vision = camera(tmp_path)
    person = vision.face_db_path / ("a" * 32)
    person.mkdir(parents=True)
    pixels = np.random.default_rng(17).integers(0, 256, (100, 100), dtype=np.uint8)
    Image.fromarray(pixels).save(person / "00.png")
    (vision.face_db_path / "people.json").write_text(json.dumps({person.name: "ExamplePerson"}))
    output = BytesIO()
    Image.fromarray(pixels).save(output, "PNG")
    # Isolate matching from Haar detection: the synthetic pixels are not a real face.
    vision._face_detector = lambda _: None
    vision._faces = lambda module, detector, frame: (module.cvtColor(frame, module.COLOR_BGR2GRAY), [(0, 0, 100, 100)])
    before = {path: path.read_bytes() for path in vision.face_db_path.rglob("*") if path.is_file()}
    assert vision.match_image(output.getvalue())["faces"][0]["name"] == "ExamplePerson"
    assert {path: path.read_bytes() for path in vision.face_db_path.rglob("*") if path.is_file()} == before
    vision._open.assert_not_called()


@pytest.mark.parametrize("setting", ["paused", "disabled_skills", "cloud_enabled"])
def test_privacy_changes_during_matching_discard_results(tmp_path, setting):
    controls = PrivacyControls(tmp_path / "privacy.json")
    value = {"paused": True, "disabled_skills": ["camera"], "cloud_enabled": False}[setting]
    def changed(data):
        controls.update(**{setting: value})
        return {"enrolled": True, "faces": [{"name": "ExamplePerson"}]}
    skill = CameraSkill(SimpleNamespace(match_image=changed))
    skill.controls = controls
    with pytest.raises(PrivacyBlocked):
        skill.match_image(image_bytes())


def photo_chat(tmp_path):
    instance = orchestrator()
    instance.config.documents_dir_path = str(tmp_path / "documents")
    instance.config.memory_db_path = str(tmp_path / "memory")
    instance.controls = PrivacyControls(tmp_path / "privacy.json")
    instance.controls.update(cloud_enabled=True)
    vision = SimpleNamespace(enabled=True, match_image=MagicMock(return_value={
        "enrolled": True, "faces": [{"name": "ExamplePerson"}]}),
        scan=MagicMock(side_effect=AssertionError("Photo opened webcam")), enroll=MagicMock())
    registry = SkillRegistry(tmp_path / "skills", controls=instance.controls)
    registry.register(CameraSkill(vision))
    instance.skill_registry = registry
    engine = SimpleNamespace(generate_from_messages=AsyncMock(return_value=SimpleNamespace(
        content="A person wearing blue. <emote>IDLE</emote>")))
    instance.llm.vision_engine.return_value = engine
    path = tmp_path / "photo.jpeg"
    path.write_bytes(image_bytes())
    return instance, vision, engine, path


@pytest.mark.asyncio
async def test_drop_summary_and_identity_followups_use_local_evidence_without_cloud_labels(tmp_path):
    instance, vision, engine, path = photo_chat(tmp_path)
    instance._remember_recent_turn("/camera enroll ExamplePerson", "Enrolled ExamplePerson locally from 12 face samples.")
    reply = await instance.handle_attachment_drop([str(path)])
    assert "A person wearing blue." in reply and "possible match to ExamplePerson" in reply
    assert "not verified identities" in reply
    assert "ExamplePerson" not in str(engine.generate_from_messages.call_args)
    assert "ExamplePerson" not in instance._recent_turns[-1]["content"]
    engine.generate_from_messages.reset_mock()
    instance.llm.vision_engine.reset_mock()
    for question in ("Who is the person in this image?", "What about the other person", "Who is this?"):
        reply = await instance.handle_user_message(pb.UserMessage(text=question))
        assert "possible match to ExamplePerson" in reply
    assert vision.match_image.call_count == 4
    assert all(call.args == (path.read_bytes(),) for call in vision.match_image.call_args_list)
    instance.llm.vision_engine.assert_not_awaited()
    engine.generate_from_messages.assert_not_awaited()
    instance.llm.generate_from_messages.assert_not_awaited()
    vision.scan.assert_not_called()
    vision.enroll.assert_not_called()
    assert "ExamplePerson" not in str(list(instance._recent_turns)[2:])
    assert instance._result_library().records() == []
    await instance.handle_user_message(pb.UserMessage(text="Describe the other person"))
    assert "ExamplePerson" not in str(engine.generate_from_messages.call_args)


@pytest.mark.asyncio
async def test_selected_photo_answer_saves_only_visual_description(tmp_path):
    instance, _, engine, path = photo_chat(tmp_path)
    instance._remember_recent_turn("Can you open my webcam?", "Recognized: ExamplePerson.")
    reply = await instance.handle_user_message(pb.UserMessage(text="Describe this picture", attachments=[str(path)]))
    assert "possible match to ExamplePerson" in reply
    records = instance._result_library().records()
    assert len(records) == 1 and records[0]["answer"] == "A person wearing blue."
    assert "ExamplePerson" not in str(engine.generate_from_messages.call_args)
    assert "ExamplePerson" not in instance._recent_turns[-1]["content"]


@pytest.mark.asyncio
async def test_identity_rematches_after_profile_forgetting_and_keeps_other_selected_files(tmp_path):
    instance, vision, _, path = photo_chat(tmp_path)
    instance._active_attachments = [str(tmp_path / "lesson.pdf"), str(path)]
    reply = await instance.handle_user_message(pb.UserMessage(text="Who is in this image?"))
    assert "ExamplePerson" in reply
    vision.match_image.return_value = {"enrolled": False, "faces": []}
    reply = await instance.handle_user_message(pb.UserMessage(text="Who is this?"))
    assert "No face profiles are enrolled" in reply and "ExamplePerson" not in reply
    assert vision.match_image.call_count == 2
    assert len(instance._active_attachments) == 2
    instance.llm.vision_engine.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("result,expected", [
    ({"enrolled": True, "faces": [{"name": None}]}, "unknown; no confident match"),
    ({"enrolled": True, "faces": []}, "No clear face detected"),
    ({"enrolled": False, "faces": []}, "No face profiles are enrolled"),
    ({"enrolled": True, "faces": [{"name": "ExamplePerson"}, {"name": None}]}, "face 2 (ordered left to right): unknown"),
])
async def test_identity_questions_report_unknown_missing_profiles_and_multiple_faces(tmp_path, result, expected):
    instance, vision, _, path = photo_chat(tmp_path)
    vision.match_image.return_value = result
    reply = await instance.handle_user_message(pb.UserMessage(text="Who is in this picture?", attachments=[str(path)]))
    assert expected in reply
    if not any(face["name"] for face in result["faces"]):
        assert "ExamplePerson" not in reply
    instance.llm.vision_engine.assert_not_awaited()
    instance.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_identity_works_with_cloud_off_but_respects_pause_and_skill_disable(tmp_path):
    instance, vision, _, path = photo_chat(tmp_path)
    instance.controls.update(cloud_enabled=False)
    question = pb.UserMessage(text="Who is this?", attachments=[str(path)])
    assert "possible match to ExamplePerson" in await instance.handle_user_message(question)
    vision.match_image.reset_mock()
    instance.controls.update(paused=True)
    assert "Privacy pause is active" in await instance.handle_user_message(question)
    vision.match_image.assert_not_called()
    instance.controls.update(paused=False, disabled_skills=["camera"])
    assert "Disabled" in await instance.handle_user_message(question)
    vision.match_image.assert_not_called()
    instance.llm.vision_engine.assert_not_awaited()
    instance.llm.generate_from_messages.assert_not_awaited()
