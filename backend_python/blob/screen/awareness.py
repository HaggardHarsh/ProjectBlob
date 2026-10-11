"""Automatic local observation with an expiring, fixed-vocabulary activity brief."""

import asyncio
from dataclasses import dataclass
import hashlib
import json
import time

from blob.privacy.screen_filter import activity_summary, sensitive_window
from blob.skills.base import _skill_executor


def is_blob_window(window):
    return window.title == "Blob Chat" or window.process_name.casefold() == "blob_overlay"


@dataclass(frozen=True)
class Activity:
    summary: str
    observed_at: float
    identity: str
    generation: int


class ScreenAwareness:
    def __init__(self, config, sampler, ocr, controls, *, clock=time.monotonic):
        self.sampler, self.ocr, self.controls = sampler, ocr, controls
        self.interval = config.screen_sample_interval_sec
        self.ttl = config.screen_context_ttl_sec
        self.clock = clock
        self.activity = None
        self.fingerprint = None
        self.reason = "Waiting for an observable window"
        self._focus = None
        self._focus_since = 0
        self._sampled_at = float("-inf")

    @property
    def enabled(self):
        return self.controls.state.get("awareness_enabled", False)

    def clear(self, reason="Activity context cleared"):
        self.activity = None
        self.fingerprint = None
        self.reason = reason

    def _allowed(self, window):
        return (self.enabled and not self.controls.paused and window is not None and
                "screen_capture" not in self.controls.state["disabled_skills"] and
                bool(window.title and window.process_name and window.identity) and
                not sensitive_window(window) and
                not self.sampler.privacy_shield.blacklist.is_blacklisted(window))

    def context(self):
        # Recheck at use time, including focus changes since the worker's last poll.
        if not self.enabled or self.controls.paused:
            self.clear("Awareness off" if not self.enabled else "Privacy paused")
            return ""
        window = self.sampler.privacy_shield.monitor.get_active_window()
        activity = self.activity
        if not self._allowed(window):
            self.clear("Sensitive or unverified window")
            return ""
        if not activity:
            return ""
        if (self.clock() - activity.observed_at > self.ttl or
                activity.generation != self.controls.generation or
                (window.identity != activity.identity and not is_blob_window(window))):
            self.clear("Activity context expired or window changed")
            return ""
        age = int(max(0, self.clock() - activity.observed_at))
        return (f"Local activity observation ({age}s ago; tentative, not a user-stated fact): "
                + activity.summary)

    def status(self):
        brief = self.context()
        return json.dumps({"enabled": self.enabled, "paused": self.controls.paused,
                           "interval_seconds": self.interval, "ttl_seconds": self.ttl,
                           "activity": brief or None, "status": "Observing" if brief else self.reason,
                           "background_cloud_calls": False, "screen_history_saved": False}, indent=2)

    def command(self, text, orchestrator):
        parts = text.casefold().split()
        if len(parts) == 1 or parts[1:] == ["status"]:
            return self.status()
        if parts[1:] in (["on"], ["off"]):
            enabled = parts[1] == "on"
            self.controls.update(awareness_enabled=enabled)
            if not enabled:
                self.controls.cancel_requests()
                orchestrator.clear_private_context()
                self.clear("Awareness off")
            return ("Screen awareness on. Local active-window observation uses no background model calls. "
                    "Only brief activity labels and recognized topics enter chat. Use /awareness status to check it."
                    if enabled else "Screen awareness off. Activity context cleared.")
        if parts[1:] == ["clear"]:
            with self.controls.lock:
                self.controls.generation += 1
            self.controls.cancel_requests()
            orchestrator.clear_private_context()
            self.clear()
            return "Activity context cleared. Observation remains " + ("on." if self.enabled else "off.")
        return "/awareness status | on | off | clear"

    def _read_frame(self, image, process):
        # The worker owns the frame even when the caller is cancelled mid-OCR.
        try:
            text = self.ocr.extract_text(image)
            if text.startswith(("OCR is not available", "Failed to extract text:", "(No readable text")):
                return "", "OCR unavailable or unreadable"
            if any(line.lstrip().startswith(("Blob>", "Blob:", "Blob >")) for line in text.splitlines()):
                return "", "Blob chat excluded"
            summary = activity_summary(text, process)
            return summary, "Sensitive screen content excluded" if not summary else "Observing"
        finally:
            image.close()

    async def sample_once(self, window=None):
        window = window or await asyncio.to_thread(self.sampler.privacy_shield.monitor.get_active_window)
        if not self._allowed(window):
            self.clear("Sensitive or unverified window")
            return
        if is_blob_window(window):
            return
        generation = self.controls.generation
        with self.controls.operation():
            image = await self.sampler.capture_active_window(window)
            if image is None:
                self.clear("Active-window capture unavailable")
                return
            # Changed settings/focus invalidate even a visually identical frame.
            fingerprint = (window.identity, generation, hashlib.sha256(image.tobytes()).digest())
            if fingerprint == self.fingerprint and self.activity:
                image.close()
                summary, reason = self.activity.summary, "Observing"
            else:
                future = _skill_executor.submit(self._read_frame, image, window.process_name)
                future.add_done_callback(lambda done: image.close() if done.cancelled() else None)
                summary, reason = await asyncio.wrap_future(future)
            current = await asyncio.to_thread(self.sampler.privacy_shield.monitor.get_active_window)
            if (generation != self.controls.generation or not self._allowed(current) or
                    current.identity != window.identity):
                self.clear("Observation discarded after privacy or focus change")
                return
            if not summary:
                self.clear(reason)
                return
            self.activity = Activity(summary, self.clock(), window.identity, generation)
            self.fingerprint = fingerprint
            self.reason = reason

    async def run(self):
        try:
            while True:
                if not self.enabled or self.controls.paused:
                    self.clear("Awareness off" if not self.enabled else "Privacy paused")
                    self._focus = None
                else:
                    window = await asyncio.to_thread(self.sampler.privacy_shield.monitor.get_active_window)
                    if not self._allowed(window):
                        self.clear("Sensitive or unverified window")
                        self._focus = None
                    elif not is_blob_window(window):
                        now = self.clock()
                        if self._focus != window.identity:
                            self.clear("Waiting for the new window to settle")
                            self._focus, self._focus_since = window.identity, now
                            self._sampled_at = float("-inf")
                        if now - self._focus_since >= 2 and now - self._sampled_at >= self.interval:
                            self._sampled_at = now
                            try:
                                # Track the sample, not the persistent observer, so a
                                # privacy cancellation does not permanently stop it.
                                await asyncio.create_task(self.sample_once(window))
                            except asyncio.CancelledError:
                                if asyncio.current_task().cancelling():
                                    raise
                                self.clear("Observation cancelled by privacy controls")
                            except Exception:
                                # Do not put titles, pixels, OCR, or D-Bus payloads in logs.
                                self.clear("Observation unavailable; retrying locally")
                await asyncio.sleep(1)
        finally:
            self.clear("Observer stopped")
