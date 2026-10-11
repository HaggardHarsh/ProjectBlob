"""A local, active-window-only GNOME Shell bridge for native Wayland windows."""

import ast
import asyncio
import io
import json
import subprocess
import os
from pathlib import Path

from PIL import Image

PATH = "/org/projectblob/Awareness"
INTERFACE = "org.projectblob.Awareness"


def bridge_token(*, create=False):
    from blob.ipc.auth import ipc_token
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    return ipc_token(runtime / "blob-awareness/token", create=create)


def window_state():
    """Small bounded metadata call, usable by the existing synchronous monitor."""
    try:
        result = subprocess.run([
            "gdbus", "call", "--session", "--dest", "org.gnome.Shell", "--object-path", PATH,
            "--method", INTERFACE + ".GetWindow",
        ], capture_output=True, text=True, timeout=1)
        if result.returncode or len(result.stdout) > 16000:
            return None
        data = json.loads(ast.literal_eval(result.stdout)[0])
        if not isinstance(data, dict):
            return None
        if data.get("blocked") is not False:
            return None
        if not all(isinstance(data.get(key), str) for key in ("title", "process_name", "id")):
            return None
        if (type(data.get("pid")) is not int or not isinstance(data.get("bbox"), list) or
                len(data["bbox"]) != 4 or any(type(value) is not int for value in data["bbox"])):
            return None
        return data
    except (OSError, subprocess.TimeoutExpired, ValueError, SyntaxError, TypeError, KeyError):
        return None


async def capture_window(expected, *, token=None):
    from dbus_next import Message, MessageType
    from dbus_next.aio import MessageBus
    token = bridge_token() if token is None else token
    bus = await MessageBus().connect()
    try:
        reply = await asyncio.wait_for(bus.call(Message(
            destination="org.gnome.Shell", path=PATH, interface=INTERFACE,
            member="Capture", signature="ss", body=[expected, token],
        )), 10)
        if reply.message_type == MessageType.ERROR or len(reply.body) != 2:
            return None
        state = json.loads(reply.body[0])
        data = bytes(reply.body[1])
        if state.get("blocked") is not False or state.get("id") != expected or not 0 < len(data) <= 8 * 1024 * 1024:
            return None
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 16000000:
                return None
            image.load()
            return image.copy()
    finally:
        bus.disconnect()
