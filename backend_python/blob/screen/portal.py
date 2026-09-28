"""Ask the desktop portal for a user-approved screenshot on Wayland."""

import asyncio
from pathlib import Path
from urllib.parse import unquote, urlparse
import uuid


class PortalUnavailable(RuntimeError):
    """The desktop portal cannot be reached or does not support screenshots."""


class PortalCaptureError(RuntimeError):
    """The portal handled the request but did not provide a screenshot."""


async def screenshot(timeout_seconds: int = 120):
    try:
        from dbus_next import Message, MessageType, Variant
        from dbus_next.aio import MessageBus
    except ImportError as exc:
        raise PortalUnavailable("Screen portal support is missing (install dbus-next).") from exc

    try:
        bus = await MessageBus().connect()
    except Exception as exc:
        raise PortalUnavailable(f"Cannot connect to the desktop session bus: {exc}") from exc

    token = "blob_" + uuid.uuid4().hex
    sender = bus.unique_name.removeprefix(":").replace(".", "_")
    request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
    response = asyncio.get_running_loop().create_future()

    def on_message(message):
        if (message.message_type == MessageType.SIGNAL
                and message.path == request_path
                and message.interface == "org.freedesktop.portal.Request"
                and message.member == "Response"
                and not response.done()):
            response.set_result(message.body)

    bus.add_message_handler(on_message)
    match_rule = ("type='signal',sender='org.freedesktop.portal.Desktop',"
                  "interface='org.freedesktop.portal.Request',member='Response',"
                  f"path='{request_path}'")
    try:
        match_reply = await bus.call(Message(
            destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus", member="AddMatch",
            signature="s", body=[match_rule],
        ))
        if match_reply.message_type == MessageType.ERROR:
            raise PortalUnavailable(f"Cannot listen for portal permission result: {match_reply.body[0]}")

        call_reply = await bus.call(Message(
            destination="org.freedesktop.portal.Desktop",
            path="/org/freedesktop/portal/desktop",
            interface="org.freedesktop.portal.Screenshot", member="Screenshot",
            signature="sa{sv}",
            body=["", {"handle_token": Variant("s", token), "interactive": Variant("b", False)}],
        ))
        if call_reply.message_type == MessageType.ERROR:
            raise PortalUnavailable(f"Screenshot portal unavailable: {call_reply.body[0]}")
        if not call_reply.body or call_reply.body[0] != request_path:
            raise PortalCaptureError("Screenshot portal returned an unexpected request handle.")

        try:
            code, results = await asyncio.wait_for(response, timeout_seconds)
        except asyncio.TimeoutError as exc:
            await bus.call(Message(
                destination="org.freedesktop.portal.Desktop", path=request_path,
                interface="org.freedesktop.portal.Request", member="Close",
            ))
            raise PortalCaptureError("Screen sharing timed out waiting for desktop permission.") from exc
        if code == 1:
            raise PortalCaptureError("Screen sharing was cancelled in the desktop permission dialog.")
        if code != 0:
            raise PortalCaptureError("The desktop denied the screen capture request.")

        uri = results.get("uri")
        uri = uri.value if uri else ""
        parsed = urlparse(uri)
        if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
            raise PortalCaptureError("Screenshot portal returned an unsupported image URI.")
        path = Path(unquote(parsed.path))
        from PIL import Image
        try:
            with Image.open(path) as image:
                image.load()
                return image.copy()
        except OSError as exc:
            raise PortalCaptureError("The screenshot provided by the desktop is unreadable.") from exc
    finally:
        bus.remove_message_handler(on_message)
        bus.disconnect()
