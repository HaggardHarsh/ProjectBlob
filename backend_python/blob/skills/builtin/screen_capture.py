import asyncio
import logging
from blob.skills.base import SkillInterface, SkillResult

logger = logging.getLogger(__name__)


class ScreenCaptureSkill(SkillInterface):
    def __init__(self):
        self.sampler = None
        self.ocr = None

    @property
    def name(self): return "screen_capture"

    @property
    def description(self): return "Capture the current screen and describe what's visible. Returns active window title and OCR text from the screen. args: {} (no arguments needed)"

    @property
    def triggers(self): return ["screen", "see", "look", "what's on screen", "screenshot"]

    def set_sampler(self, sampler):
        self.sampler = sampler

    def set_ocr(self, ocr_processor):
        self.ocr = ocr_processor

    def execute(self, args: dict) -> SkillResult:
        """Sync fallback — should not be used; async_execute is preferred."""
        return SkillResult("Use async_execute for screen capture", False, "CONFUSED")

    async def async_execute(self, args: dict) -> SkillResult:
        """Capture the screen asynchronously and extract text via OCR."""
        if not self.sampler:
            return SkillResult("Screen sampler is not configured.", False, "WORRIED")

        if self.sampler.privacy_shield.is_capture_blocked():
            return SkillResult("Screen capture is blocked by the privacy shield.", False, "WORRIED")

        # Get active window title (lightweight)
        window_title = self.sampler.get_active_window_title() or "Unknown Window"

        # Attempt screen capture
        image = await self.sampler.capture()
        if image and self.sampler.privacy_shield.is_capture_blocked():
            if hasattr(image, "close"):
                image.close()
            return SkillResult("Screen capture is blocked by the privacy shield.", False, "WORRIED")
        if not image:
            return SkillResult(
                f"Active Window: {window_title}\n\nScreen capture failed — could not grab the screen. "
                "This may be due to Wayland permissions. Try running: gnome-screenshot --interactive",
                False,
                "WORRIED"
            )

        # Run OCR if available, then release the image promptly.
        try:
            if self.ocr:
                text = self.ocr.extract_text(image)
            else:
                text = "(OCR processor not configured)"
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            text = f"(OCR failed: {e})"
        finally:
            if hasattr(image, "close"):
                image.close()

        output = f"Active Window: {window_title}\n\nExtracted Screen Text:\n{text}"
        return SkillResult(output, True, "THINKING")
