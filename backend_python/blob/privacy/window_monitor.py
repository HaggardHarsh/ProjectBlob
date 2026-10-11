import sys
import os
import subprocess
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

@dataclass
class WindowInfo:
    title: str
    process_name: str
    pid: int
    bbox: Optional[Tuple[int, int, int, int]] = None # (left, top, right, bottom)
    identity: str = ""
    backend: str = "x11"

class WindowMonitor:
    def get_active_window(self) -> Optional[WindowInfo]:
        if sys.platform == "linux":
            if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
                from blob.screen.gnome_bridge import window_state
                state = window_state()
                if not state:
                    return None
                return WindowInfo(state["title"], state["process_name"], state.get("pid", 0),
                                  tuple(state.get("bbox", ())), state["id"], "gnome")
            return self._get_active_window_linux()
        elif sys.platform == "win32":
            return self._get_active_window_windows()
        return None

    def _get_active_window_linux(self) -> Optional[WindowInfo]:
        try:
            # Requires xdotool to be installed: sudo dnf install xdotool
            win_id = subprocess.check_output(["xdotool", "getactivewindow"], stderr=subprocess.DEVNULL).decode().strip()
            title = subprocess.check_output(["xdotool", "getwindowname", win_id], stderr=subprocess.DEVNULL).decode().strip()
            
            try:
                pid_str = subprocess.check_output(["xdotool", "getwindowpid", win_id], stderr=subprocess.DEVNULL).decode().strip()
                pid = int(pid_str) if pid_str.isdigit() else 0
            except subprocess.CalledProcessError:
                pid = 0
            
            process_name = ""
            if pid > 0:
                try:
                    process_name = subprocess.check_output(["ps", "-p", str(pid), "-o", "comm="], stderr=subprocess.DEVNULL).decode().strip()
                except subprocess.CalledProcessError:
                    pass

            # Get Geometry for bounding box
            geom_output = subprocess.check_output(["xdotool", "getwindowgeometry", win_id], stderr=subprocess.DEVNULL).decode()
            # Parse output like:
            # Position: 100,50 (screen: 0)
            # Geometry: 800x600
            x, y, w, h = 0, 0, 0, 0
            for line in geom_output.split('\n'):
                if "Position:" in line:
                    coords = line.split(':')[1].split('(')[0].strip()
                    x, y = map(int, coords.split(','))
                elif "Geometry:" in line:
                    dims = line.split(':')[1].strip()
                    w, h = map(int, dims.split('x'))
            
            bbox = (x, y, x + w, y + h) if w > 0 and h > 0 else None
            
            return WindowInfo(title=title, process_name=process_name, pid=pid, bbox=bbox,
                              identity=win_id + ":" + title)
        except Exception as e:
            # logger.debug(f"Linux window fetch failed (is xdotool installed?): {e}")
            return None

    def _get_active_window_windows(self) -> Optional[WindowInfo]:
        try:
            import ctypes
            from ctypes import wintypes
            import psutil
            
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd: return None
            
            length = user32.GetWindowTextLengthW(hwnd)
            title_buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buf, length + 1)
            title = title_buf.value
            
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            
            try:
                process_name = psutil.Process(pid.value).name()
            except Exception:
                process_name = ""
                
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                bbox = (rect.left, rect.top, rect.right, rect.bottom)
            else:
                bbox = None
                
            return WindowInfo(title=title, process_name=process_name, pid=pid.value, bbox=bbox)
        except Exception as e:
            logger.error(f"Windows window fetch failed: {e}")
            return None
