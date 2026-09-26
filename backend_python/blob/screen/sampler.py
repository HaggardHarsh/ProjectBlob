import os
import uuid
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class ScreenSampler:
    def __init__(self, config, privacy_shield, orchestrator=None):
        self.config = config
        self.privacy_shield = privacy_shield
        self.orchestrator = orchestrator

    def _get_temp_path(self):
        return f"/tmp/blob_screenshot_{uuid.uuid4().hex}.png"

    def _load_image(self, path):
        try:
            from PIL import Image
            return Image.open(path)
        except ImportError:
            logger.error("PIL is not installed")
            return None
        except Exception as e:
            logger.error(f"Failed to load image from {path}: {e}")
            return None

    def _cleanup(self, path):
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    async def capture(self):
        """
        Tries to capture the screen using multiple backends in priority order.
        Returns a PIL Image on success, None on failure.
        """
        # 1. Try D-Bus XDG Desktop Portal
        image = await self._capture_dbus()
        if image:
            logger.info("Captured screen using D-Bus XDG Desktop Portal")
            return image
            
        # 2. Try gnome-screenshot
        image = await self._capture_gnome_screenshot()
        if image:
            logger.info("Captured screen using gnome-screenshot")
            return image
            
        # 3. Try grim
        image = await self._capture_grim()
        if image:
            logger.info("Captured screen using grim")
            return image
            
        # 4. Try PIL.ImageGrab
        image = await self._capture_pil()
        if image:
            logger.info("Captured screen using PIL.ImageGrab")
            return image
            
        logger.error("All screen capture backends failed")
        return None
        
    async def _capture_dbus(self):
        try:
            from dbus_next.aio import MessageBus
            from dbus_next.constants import BusType
            from dbus_next import Message, Variant
            import urllib.parse
            
            # Note: A full implementation of org.freedesktop.portal.Screenshot requires
            # creating a request and listening to a Response signal. We are including
            # this as a placeholder/stub for the DBus call that initiates it.
            # Realistically, if this doesn't complete the full async dance, it will
            # fail gracefully and fall back to the CLI tools which are much more robust.
            
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            reply = await bus.call(
                Message(
                    destination='org.freedesktop.portal.Desktop',
                    path='/org/freedesktop/portal/desktop',
                    interface='org.freedesktop.portal.Screenshot',
                    member='Screenshot',
                    signature='sa{sv}',
                    body=['', {'interactive': Variant('b', False)}]
                )
            )
            # This returns a request path. Signal handling would be needed here to get the URI.
            pass
        except Exception as e:
            logger.debug(f"D-Bus XDG Desktop Portal capture failed or not fully implemented: {e}")
        return None

    async def _capture_gnome_screenshot(self):
        path = self._get_temp_path()
        try:
            proc = await asyncio.create_subprocess_exec(
                'gnome-screenshot', '-f', path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()
            if proc.returncode == 0 and os.path.exists(path):
                img = self._load_image(path)
                if img:
                    img.load()
                    self._cleanup(path)
                    return img
        except Exception as e:
            logger.debug(f"gnome-screenshot failed: {e}")
        self._cleanup(path)
        return None

    async def _capture_grim(self):
        path = self._get_temp_path()
        try:
            proc = await asyncio.create_subprocess_exec(
                'grim', path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()
            if proc.returncode == 0 and os.path.exists(path):
                img = self._load_image(path)
                if img:
                    img.load()
                    self._cleanup(path)
                    return img
        except Exception as e:
            logger.debug(f"grim failed: {e}")
        self._cleanup(path)
        return None

    async def _capture_pil(self):
        try:
            from PIL import ImageGrab
            return ImageGrab.grab()
        except ImportError:
            logger.error("PIL is not installed")
        except Exception as e:
            logger.debug(f"PIL ImageGrab failed: {e}")
        return None

    def get_active_window_title(self) -> Optional[str]:
        import subprocess
        try:
            result = subprocess.run(
                ['xdotool', 'getactivewindow', 'getwindowname'],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.debug(f"xdotool failed: {e}")
            
        return None
