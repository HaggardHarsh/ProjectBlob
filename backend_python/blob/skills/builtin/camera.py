import threading

from blob.skills.base import SkillInterface, SkillResult
from blob.vision.camera import CameraError


class CameraSkill(SkillInterface):
    def __init__(self, vision):
        self.vision = vision
        self._lock = threading.Lock()

    @property
    def name(self):
        return "camera"

    @property
    def description(self):
        return ("On-demand local camera face and full-body detection, with optional named face recognition. "
                "args: {'action':'scan'|'enroll'|'forget'|'list', 'name':'person name'}. "
                "Only enroll a person who agreed to it. Camera can be disabled in settings.")

    @property
    def triggers(self):
        return ["camera", "webcam", "recognize face", "enroll face", "who is in front of me"]

    def execute(self, args: dict) -> SkillResult:
        with self._lock:
            return self._execute(args)

    def _execute(self, args: dict) -> SkillResult:
        action = args.get("action", "scan")
        try:
            if action == "scan":
                result = self.vision.scan()
                names = ", ".join(result["recognized"]) or "none"
                output = (f"Camera scan: {result['faces']} face(s), {result['full_bodies']} full body/person detection(s). "
                          f"Recognized: {names}. Unknown faces: {result['unknown_faces']}.")
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
                return SkillResult("Unknown camera action. Use scan, enroll, forget, or list.", False, "CONFUSED")
            return SkillResult(output, True, "HAPPY")
        except (CameraError, OSError) as exc:
            return SkillResult(str(exc), False, "WORRIED")
