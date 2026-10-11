import asyncio
import logging
from blob.privacy.window_monitor import WindowMonitor
from blob.privacy.blacklist import BlacklistManager
from blob.privacy.screen_filter import sensitive_window

logger = logging.getLogger(__name__)

class PrivacyShield:
    def __init__(self, config, event_dispatcher=None, controls=None):
        self.config = config
        self.monitor = WindowMonitor()
        self.blacklist = BlacklistManager(config.blacklist_path)
        self.is_active = False
        self.event_dispatcher = event_dispatcher
        self.controls = controls
        self.awareness = None

    async def _broadcast_state(self, active: bool, reason: str = ""):
        if active and getattr(self, "awareness", None):
            self.awareness.clear("Privacy shield active")
        if not self.event_dispatcher:
            return
        from blob.ipc import blob_service_pb2
        event = blob_service_pb2.BackendEvent()
        event.privacy.activated = active
        event.privacy.reason = reason
        await self.event_dispatcher.broadcast(event)

    def is_capture_blocked(self) -> bool:
        """Recheck the active window at capture time, not only at poll time."""
        if getattr(self, "controls", None) and self.controls.paused:
            return True
        if self.is_active:
            return True
        window_info = self.monitor.get_active_window()
        return (not window_info or not window_info.title or not window_info.process_name or
                self.blacklist.is_blacklisted(window_info) or sensitive_window(window_info))

    async def run(self):
        while True:
            try:
                window_info = self.monitor.get_active_window()
                if ((getattr(self, "controls", None) and self.controls.paused) or
                        not window_info or not window_info.title or not window_info.process_name or
                        self.blacklist.is_blacklisted(window_info) or sensitive_window(window_info)):
                    if not self.is_active:
                        self.is_active = True
                        logger.info("Privacy Shield ACTIVE")
                        await self._broadcast_state(True, "Sensitive or unverified window")
                else:
                    if self.is_active:
                        self.is_active = False
                        logger.info("Privacy Shield INACTIVE")
                        await self._broadcast_state(False)
            except Exception as e:
                logger.error(f"Error in privacy shield: {e}")
            await asyncio.sleep(self.config.privacy_poll_interval_ms / 1000.0)
