import asyncio
import logging
from blob.privacy.window_monitor import WindowMonitor
from blob.privacy.blacklist import BlacklistManager

logger = logging.getLogger(__name__)

class PrivacyShield:
    def __init__(self, config):
        self.config = config
        self.monitor = WindowMonitor()
        self.blacklist = BlacklistManager(config.blacklist_path)
        self.is_active = False

    async def run(self):
        while True:
            try:
                window_info = self.monitor.get_active_window()
                if window_info and self.blacklist.is_blacklisted(window_info):
                    if not self.is_active:
                        self.is_active = True
                        logger.info(f"Privacy Shield ACTIVE: {window_info.title}")
                else:
                    if self.is_active:
                        self.is_active = False
                        logger.info("Privacy Shield INACTIVE")
            except Exception as e:
                logger.error(f"Error in privacy shield: {e}")
            await asyncio.sleep(self.config.privacy_poll_interval_ms / 1000.0)
