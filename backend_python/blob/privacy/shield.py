import asyncio
import logging
from blob.privacy.window_monitor import WindowMonitor
from blob.privacy.blacklist import BlacklistManager

logger = logging.getLogger(__name__)

class PrivacyShield:
    def __init__(self, config, event_dispatcher=None):
        self.config = config
        self.monitor = WindowMonitor()
        self.blacklist = BlacklistManager(config.blacklist_path)
        self.is_active = False
        self.event_dispatcher = event_dispatcher

    async def _broadcast_state(self, active: bool, reason: str = ""):
        if not self.event_dispatcher:
            return
        from blob.ipc import blob_service_pb2
        event = blob_service_pb2.BackendEvent()
        event.privacy.activated = active
        event.privacy.reason = reason
        await self.event_dispatcher.broadcast(event)

    def is_capture_blocked(self) -> bool:
        """Recheck the active window at capture time, not only at poll time."""
        if self.is_active:
            return True
        window_info = self.monitor.get_active_window()
        return bool(window_info and self.blacklist.is_blacklisted(window_info))

    async def run(self):
        while True:
            try:
                window_info = self.monitor.get_active_window()
                if window_info and self.blacklist.is_blacklisted(window_info):
                    if not self.is_active:
                        self.is_active = True
                        logger.info(f"Privacy Shield ACTIVE: {window_info.title}")
                        await self._broadcast_state(True, "Sensitive window active")
                else:
                    if self.is_active:
                        self.is_active = False
                        logger.info("Privacy Shield INACTIVE")
                        await self._broadcast_state(False)
            except Exception as e:
                logger.error(f"Error in privacy shield: {e}")
            await asyncio.sleep(self.config.privacy_poll_interval_ms / 1000.0)
