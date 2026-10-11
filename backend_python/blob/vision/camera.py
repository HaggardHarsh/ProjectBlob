"""On-demand camera detection and explicit, local face enrollment."""

import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid
from contextlib import nullcontext


class CameraError(RuntimeError):
    pass


class CameraVision:
    def __init__(self, config):
        self.enabled = config.camera_enabled
        self.device_index = config.camera_device_index
        self.face_db_path = Path(config.face_db_path).expanduser()
        self.controls = None

    def _check_privacy(self):
        if self.controls:
            self.controls.check()

    @staticmethod
    def _cv2():
        try:
            import cv2
        except ImportError as exc:
            raise CameraError("Camera support is missing. Install the vision extra: pip install -e 'backend_python[vision]'.") from exc
        return cv2

    def _open(self, cv2):
        self._check_privacy()
        if not self.enabled:
            raise CameraError("Camera access is disabled. Set BLOB_CAMERA_ENABLED=1 and restart Blob to enable it.")
        if self.device_index < 0:
            raise CameraError("Camera device index must be nonnegative.")
        capture = cv2.VideoCapture(self.device_index)
        if not capture.isOpened():
            capture.release()
            device = Path(f"/dev/video{self.device_index}")
            if sys.platform == "linux" and not device.exists():
                raise CameraError(
                    f"Camera device {device} is not visible to Blob. Check that the camera is connected "
                    "and Blob runs in your desktop session, or set BLOB_CAMERA_DEVICE_INDEX."
                )
            raise CameraError(
                f"Could not open camera device {self.device_index}. It may be busy or blocked by device "
                "permissions. Wayland screen sharing permission does not control the webcam."
            )
        return capture

    def status(self):
        """Verify camera access without doing face recognition or storing a frame."""
        self._require_enabled()
        cv2 = self._cv2()
        capture = self._open(cv2)
        try:
            ok, _ = capture.read()
            if not ok:
                raise CameraError("Camera opened, but it did not return a frame.")
            return f"Camera device {self.device_index} opened and returned a frame."
        finally:
            capture.release()

    def _require_enabled(self):
        self._check_privacy()
        if not self.enabled:
            raise CameraError("Camera access is disabled. Set BLOB_CAMERA_ENABLED=1 and restart Blob to enable it.")

    @staticmethod
    def _face_detector(cv2):
        detector = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
        if detector.empty():
            raise CameraError("OpenCV's frontal face detector is unavailable.")
        return detector

    @staticmethod
    def _faces(cv2, detector, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        boxes = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        return gray, list(boxes)

    @staticmethod
    def _crop(cv2, gray, box):
        x, y, w, h = [int(value) for value in box]
        return cv2.resize(gray[y:y+h, x:x+w], (100, 100))

    def _index_path(self):
        return self.face_db_path / "people.json"

    def _load_index(self):
        path = self._index_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CameraError("The face enrollment index cannot be read.") from exc
        if not isinstance(data, dict) or any(
            not isinstance(person_id, str)
            or not re.fullmatch(r"[0-9a-f]{32}", person_id)
            or not isinstance(name, str)
            for person_id, name in data.items()
        ):
            raise CameraError("The face enrollment index is invalid.")
        return data

    def _save_index(self, data):
        self.face_db_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.face_db_path, 0o700)
        temp = self.face_db_path / f".people-{uuid.uuid4().hex}.json"
        try:
            with temp.open("x", encoding="utf-8") as file:
                os.chmod(temp, 0o600)
                json.dump(data, file)
            temp.replace(self._index_path())
        finally:
            temp.unlink(missing_ok=True)

    def _recognizer(self, cv2):
        if not hasattr(cv2, "face") or not hasattr(cv2.face, "LBPHFaceRecognizer_create"):
            raise CameraError("Named face recognition needs opencv-contrib-python. Install the vision extra.")
        return cv2.face.LBPHFaceRecognizer_create()

    def _trained_recognizer(self, cv2, people):
        import numpy as np

        images, labels = [], []
        names = {}
        for number, (person_id, name) in enumerate(sorted(people.items())):
            names[number] = name
            for path in (self.face_db_path / person_id).glob("*.png"):
                image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                if image is not None:
                    images.append(image)
                    labels.append(number)
        if not images:
            return None, names
        recognizer = self._recognizer(cv2)
        recognizer.train(images, np.asarray(labels, dtype=np.int32))
        return recognizer, names

    def scan(self):
        self._require_enabled()
        cv2 = self._cv2()
        capture = self._open(cv2)
        try:
            # Let auto exposure settle before inspecting a frame.
            for _ in range(3):
                self._check_privacy()
                ok, frame = capture.read()
                if not ok:
                    raise CameraError("The camera opened but did not return a frame.")
            frame = cv2.resize(frame, (640, 480))
            gray, faces = self._faces(cv2, self._face_detector(cv2), frame)
            hog = cv2.HOGDescriptor()
            hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            people_boxes, _ = hog.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.05)
            enrolled = self._load_index()
            names = []
            if enrolled and faces:
                recognizer, labels = self._trained_recognizer(cv2, enrolled)
                if recognizer:
                    for box in faces:
                        label, distance = recognizer.predict(self._crop(cv2, gray, box))
                        if distance <= 65 and label in labels:
                            names.append(labels[label])
            return {
                "faces": len(faces),
                "full_bodies": len(people_boxes),
                "recognized": sorted(set(names)),
                "unknown_faces": len(faces) - len(names),
            }
        finally:
            capture.release()

    def enroll(self, name: str):
        name = name.strip()
        if not re.fullmatch(r"[\w .'-]{1,60}", name, flags=re.UNICODE):
            raise CameraError("Provide a name of 1–60 letters, numbers, spaces, or . ' - characters.")
        self._require_enabled()
        people = self._load_index()
        if any(existing.casefold() == name.casefold() for existing in people.values()):
            raise CameraError(f"{name} is already enrolled. Forget that person before enrolling again.")
        cv2 = self._cv2()
        self._recognizer(cv2)  # Check the optional recognition dependency first.
        capture = self._open(cv2)
        samples = []
        try:
            detector = self._face_detector(cv2)
            for _ in range(45):
                self._check_privacy()
                ok, frame = capture.read()
                if not ok:
                    break
                frame = cv2.resize(frame, (640, 480))
                gray, faces = self._faces(cv2, detector, frame)
                if len(faces) == 1:
                    samples.append(self._crop(cv2, gray, faces[0]))
                    if len(samples) >= 12:
                        break
                    time.sleep(0.08)
        finally:
            capture.release()
        if len(samples) < 8:
            raise CameraError("Enrollment needs one clearly visible face for at least eight frames. Try better lighting and keep other people out of view.")
        person_id = uuid.uuid4().hex
        self._check_privacy()
        person_dir = self.face_db_path / person_id
        person_dir.mkdir(mode=0o700, parents=True)
        try:
            for number, sample in enumerate(samples):
                with self.controls.writing() if self.controls else nullcontext():
                    path = person_dir / f"{number:02d}.png"
                    if not cv2.imwrite(str(path), sample):
                        raise CameraError("Could not save face template.")
                    os.chmod(path, 0o600)
            with self.controls.writing() if self.controls else nullcontext():
                people[person_id] = name
                self._save_index(people)
        except Exception:
            shutil.rmtree(person_dir)
            raise
        return len(samples)

    def forget(self, name: str):
        people = self._load_index()
        person_id = next((key for key, value in people.items() if value.casefold() == name.strip().casefold()), None)
        if person_id is None:
            raise CameraError(f"No enrolled person named {name!r}.")
        shutil.rmtree(self.face_db_path / person_id)
        del people[person_id]
        self._save_index(people)

    def list_people(self):
        return sorted(self._load_index().values(), key=str.casefold)
