import asyncio
import logging
import re
from PIL import Image, ImageDraw
from blob.skills.base import SkillInterface, SkillResult

logger = logging.getLogger(__name__)
_BLOB_CHAT_LINE = re.compile(r"^\s*Blob\s*[>:]", re.IGNORECASE)
_TERMINAL_PROCESS = re.compile(
    r"(?:terminal|ptyxis|kgx|konsole|kitty|alacritty|wezterm|xterm|tilix|foot|terminator)",
    re.IGNORECASE,
)


def _remove_blob_chat_lines(text: str) -> tuple[str, bool]:
    """Keep screen content while excluding Blob's own prompt and reply lines."""
    lines = text.splitlines()
    kept = [line for line in lines if not _BLOB_CHAT_LINE.match(line)]
    return "\n".join(kept).strip(), len(kept) != len(lines)


def _active_window_info(sampler):
    monitor = getattr(getattr(sampler, "privacy_shield", None), "monitor", None)
    get_active = getattr(monitor, "get_active_window", None)
    if not callable(get_active):
        return None
    try:
        return get_active()
    except Exception:
        return None


def _terminal_box(info, image) -> tuple[int, int, int, int] | None:
    """Use window geometry only when it safely maps onto this screenshot."""
    if not isinstance(image, Image.Image):
        return None
    process = getattr(info, "process_name", "")
    box = getattr(info, "bbox", None)
    if not isinstance(process, str) or not _TERMINAL_PROCESS.search(process):
        return None
    if not isinstance(box, (tuple, list)) or len(box) != 4 or not all(isinstance(v, int) for v in box):
        return None
    left, top, right, bottom = box
    if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
        return None
    return left, top, right, bottom


class ScreenCaptureSkill(SkillInterface):
    def __init__(self):
        self.sampler = None
        self.ocr = None

    @property
    def name(self): return "screen_capture"

    @property
    def description(self): return "Read text from the current screen. Returns the active window title and OCR text, not a full image description. args: {} (no arguments needed)"

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
        window_title = self.sampler.get_active_window_title()
        if not isinstance(window_title, str) or not window_title:
            window_title = "Unknown Window"
        active_window = _active_window_info(self.sampler)
        process_name = getattr(active_window, "process_name", "")
        if ((isinstance(process_name, str) and _TERMINAL_PROCESS.search(process_name)) or
                _TERMINAL_PROCESS.search(window_title)):
            window_title = "Terminal"

        # Attempt screen capture
        image = await self.sampler.capture()
        if image and self.sampler.privacy_shield.is_capture_blocked():
            if hasattr(image, "close"):
                image.close()
            return SkillResult("Screen capture is blocked by the privacy shield.", False, "WORRIED")
        if not image:
            return SkillResult(
                self.sampler.last_error or "Screen capture failed. Check the backend logs.",
                False,
                "WORRIED"
            )

        # Run OCR if available, then release the image promptly.
        try:
            if self.ocr:
                text = self.ocr.extract_text(image)
                clean_text, chat_seen = _remove_blob_chat_lines(text)
                if chat_seen:
                    terminal_box = _terminal_box(active_window, image)
                    if terminal_box:
                        # Re-run OCR with the visible Blob terminal blacked out.
                        # Text filtering alone cannot remove multiline old replies.
                        try:
                            ImageDraw.Draw(image).rectangle(terminal_box, fill="black")
                            masked_text = self.ocr.extract_text(image)
                            clean_text, _ = _remove_blob_chat_lines(masked_text)
                        except Exception:
                            logger.warning("Could not mask Blob terminal; using filtered OCR text", exc_info=True)
                    text = clean_text or "(No readable text found)"
                    window_title = "Blob chat terminal (excluded)"
            else:
                text = "OCR processor not configured"
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            text = f"(OCR failed: {e})"
        finally:
            if hasattr(image, "close"):
                image.close()

        if text.startswith(("OCR is not available", "OCR processor not configured", "(OCR failed:", "Failed to extract text:")):
            return SkillResult(
                "Screen capture succeeded, but Blob cannot read text from it yet. "
                "Install the OCR extra with pip install -e 'backend_python[ocr]' and restart Blob. "
                f"Details: {text}",
                False,
                "WORRIED",
            )

        if not text.strip() or text.strip() == "(No readable text found)":
            if window_title == "Blob chat terminal (excluded)":
                return SkillResult(
                    "I can only read our chat terminal. Move it aside or focus the material you want explained, then ask me to look again.",
                    False,
                    "CONFUSED",
                )
            return SkillResult(
                "I captured your screen, but couldn't read any text. Try zooming in or opening the page you want help with.",
                False,
                "CONFUSED",
            )

        output = f"Active Window: {window_title}\n\nExtracted Screen Text:\n{text}"
        return SkillResult(output, True, "THINKING")
