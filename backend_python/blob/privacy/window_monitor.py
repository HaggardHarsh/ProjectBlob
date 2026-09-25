import sys
import subprocess
from dataclasses import dataclass

@dataclass
class WindowInfo:
    title: str
    process_name: str
    pid: int

class WindowMonitor:
    def get_active_window(self) -> WindowInfo:
        if sys.platform == "linux":
            try:
                title = subprocess.check_output(["xdotool", "getactivewindow", "getwindowname"]).decode().strip()
                return WindowInfo(title=title, process_name="", pid=0)
            except Exception:
                return None
        return None
