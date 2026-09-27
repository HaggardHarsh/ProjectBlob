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
        Tries available screenshot backends in priority order.
        Returns a PIL Image on success, None on failure.
        """
        if self.privacy_shield.is_capture_blocked():
            logger.info("Screen capture blocked by privacy shield")
            return None

        # 1. Try gnome-screenshot
        image = await self._capture_gnome_screenshot()
        if image:
            if self.privacy_shield.is_capture_blocked():
                image.close()
                return None
            logger.info("Captured screen using gnome-screenshot")
            return image
            
        # 2. Try grim
        image = await self._capture_grim()
        if image:
            if self.privacy_shield.is_capture_blocked():
                image.close()
                return None
            logger.info("Captured screen using grim")
            return image
            
        # 3. Try PIL.ImageGrab
        image = await self._capture_pil()
        if image:
            if self.privacy_shield.is_capture_blocked():
                image.close()
                return None
            logger.info("Captured screen using PIL.ImageGrab")
            return image
            
        logger.error("All screen capture backends failed")
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
