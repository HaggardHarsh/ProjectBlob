import threading

from blob.skills.base import SkillInterface, SkillResult
from blob.skills.contracts import object_schema
from blob.vision.camera import CameraError
from blob.privacy.controls import PrivacyBlocked


class CameraSkill(SkillInterface):
    argument_schema = object_schema({
        "action": {"type": "string", "enum": ["status", "scan", "enroll", "forget", "list"], "default": "scan"},
        "name": {"type": "string", "maxLength": 100, "default": ""}})
    permissions = ("camera.capture",)
    timeout_seconds = 45
    model_callable = False
    def __init__(self, vision):
        self.vision = vision
        self._lock = threading.Lock()

    @property
    def name(self):
        return "camera"

    @property
    def description(self):
        return ("On-demand local camera face and full-body detection, with optional named face recognition. "
                "args: {'action':'status'|'scan'|'enroll'|'forget'|'list', 'name':'person name'}. "
                "Only enroll a person who agreed to it. Camera can be disabled in settings.")

    @property
    def triggers(self):
        return ["camera", "webcam", "recognize face", "enroll face", "who is in front of me"]

    def execute(self, args: dict) -> SkillResult:
        with self._lock:
            return self._execute(args)

    def match_image(self, data):
        """Local selected-image operation, serialized with enrollment and deletion."""
        controls = getattr(self, "controls", None)
        generation = controls.generation if controls else None
        if controls:
            controls.check()
            if "camera" in controls.state["disabled_skills"]:
                raise CameraError("Local face matching is disabled. Use /privacy enable camera to allow it.")
        with self._lock:
            if controls:
                controls.check()
                if controls.generation != generation:
                    raise PrivacyBlocked("Local face check stopped because privacy settings changed.")
            result = self.vision.match_image(data)
            if controls:
                controls.check()
                if controls.generation != generation:
                    raise PrivacyBlocked("Local face check stopped because privacy settings changed.")
            return result

    def _execute(self, args: dict) -> SkillResult:
        action = args.get("action", "scan")
        try:
            if action == "status":
                output = self.vision.status()
            elif action == "scan":
                result = self.vision.scan()
                names = ", ".join(result["recognized"]) or "none"
                output = (f"Camera opened successfully. Scan: {result['faces']} face(s), "
                          f"{result['full_bodies']} full body/person detection(s). "
                          f"Recognized: {names}. Unknown faces: {result['unknown_faces']}.")
                if result["faces"] == 0:
                    output += (" No face was detected in that frame, so there was nothing to recognize. "
                               "Face the camera in good light and try again.")
                elif result["unknown_faces"]:
                    output += " To recognize a consenting person by name, enroll them with /camera enroll <name>."
            elif action == "enroll":
                name = args.get("name", "")
                count = self.vision.enroll(name)
                output = f"Enrolled {name.strip()} locally from {count} face samples."
            elif action == "forget":
                name = args.get("name", "")
                self.vision.forget(name)
                output = f"Forgot {name.strip()} and deleted their stored face samples."
            elif action == "list":
                people = self.vision.list_people()
                output = "Enrolled people: " + (", ".join(people) if people else "none")
            else:
                return SkillResult("Unknown camera action. Use status, scan, enroll, forget, or list.", False, "CONFUSED")
            return SkillResult(output, True, "HAPPY")
        except (CameraError, OSError) as exc:
            return SkillResult(str(exc), False, "WORRIED")
