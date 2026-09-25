import asyncio
import logging
from PIL import ImageGrab

logger = logging.getLogger(__name__)

class ScreenSampler:
    def __init__(self, config, privacy_shield, orchestrator):
        self.config = config
        self.privacy_shield = privacy_shield
        self.orchestrator = orchestrator

    async def run(self):
        while True:
            if not self.privacy_shield.is_active:
                try:
                    if self.config.screen_capture_mode == "active_window":
                        win_info = self.privacy_shield.monitor.get_active_window()
                        if win_info and win_info.bbox:
                            logger.debug(f"Sampling active window bbox: {win_info.bbox}")
                            img = ImageGrab.grab(bbox=win_info.bbox)
                        else:
                            logger.debug("Active window bbox not found, falling back to full screen")
                            img = ImageGrab.grab(all_screens=True)
                    else:
                        logger.debug("Sampling full screen")
                        img = ImageGrab.grab(all_screens=True)
                    # process img...
                except Exception as e:
                    logger.error(f"Failed to grab screen: {e}")
            await asyncio.sleep(self.config.screen_sample_interval_sec)
