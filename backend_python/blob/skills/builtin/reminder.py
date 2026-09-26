import asyncio
import logging
from blob.skills.base import SkillInterface, SkillResult

logger = logging.getLogger(__name__)


class ReminderSkill(SkillInterface):
    def __init__(self):
        self.dispatcher = None
        self.reminders = []
        
    @property
    def name(self): return "reminder"
    
    @property
    def description(self): return "Set a reminder/timer that fires after N minutes. args: {'message': 'what to remind', 'minutes': 5}"
    
    @property
    def triggers(self): return ["remind", "timer", "alarm"]
    
    def set_dispatcher(self, dispatcher):
        self.dispatcher = dispatcher

    async def _fire_reminder(self, message: str):
        """Called when the timer expires. Dispatches notification to frontend + prints to CLI."""
        logger.info(f"⏰ Reminder firing: {message}")
        print(f"\n\033[93m⏰ REMINDER:\033[0m {message}\n")

        if self.dispatcher:
            from blob.ipc import blob_service_pb2

            # Send notification text
            evt = blob_service_pb2.BackendEvent()
            evt.notification.text = f"⏰ REMINDER: {message}"
            await self.dispatcher.broadcast(evt)

            # Send happy emote
            emote_evt = blob_service_pb2.BackendEvent()
            emote_evt.emote.emote = blob_service_pb2.EmoteCommand.HAPPY
            await self.dispatcher.broadcast(emote_evt)
        else:
            logger.warning("ReminderSkill has no dispatcher — notification not sent to frontend")

    async def _wait_and_fire(self, minutes: float, message: str):
        """Background task that sleeps then fires the reminder."""
        try:
            await asyncio.sleep(minutes * 60)
            await self._fire_reminder(message)
        except asyncio.CancelledError:
            logger.info(f"Reminder cancelled: {message}")

    def execute(self, args):
        """Sync fallback — should not be used; async_execute is preferred."""
        return SkillResult("Use async_execute for reminders", False, "CONFUSED")

    async def async_execute(self, args):
        """Set a reminder using asyncio — runs entirely within the event loop."""
        msg = args.get('message')
        mins = args.get('minutes')
        
        if not msg or mins is None:
            return SkillResult("Missing 'message' or 'minutes' in args.", False, "CONFUSED")
            
        try:
            mins = float(mins)
        except (ValueError, TypeError):
            return SkillResult("'minutes' must be a number.", False, "CONFUSED")

        if mins <= 0:
            return SkillResult("'minutes' must be positive.", False, "CONFUSED")

        # Schedule the reminder as an asyncio task in the running loop
        task = asyncio.create_task(self._wait_and_fire(mins, msg))
        self.reminders.append({"message": msg, "minutes": mins, "task": task})
        
        logger.info(f"Reminder scheduled: '{msg}' in {mins} minute(s)")
        
        if mins < 1:
            time_str = f"{int(mins * 60)} seconds"
        elif mins == 1:
            time_str = "1 minute"
        else:
            time_str = f"{mins} minutes"

        return SkillResult(
            f"✅ Reminder set! I'll remind you to '{msg}' in {time_str}.",
            True,
            "HAPPY"
        )
