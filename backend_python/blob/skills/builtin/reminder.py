import asyncio
import threading
from blob.skills.base import SkillInterface, SkillResult

class ReminderSkill(SkillInterface):
    def __init__(self):
        # We need a reference to event dispatcher to push notifications when timer fires
        # We'll pass it in when registering
        self.dispatcher = None
        self.reminders = []
        
    @property
    def name(self): return "reminder"
    
    @property
    def description(self): return "Set a reminder. args: {'message': 'remind me to...', 'minutes': 5}"
    
    @property
    def triggers(self): return ["remind", "timer", "alarm"]
    
    def set_dispatcher(self, dispatcher):
        self.dispatcher = dispatcher
        
    def _fire_reminder(self, message, loop):
        if self.dispatcher:
            # We can't easily import protobuf here if we want decoupling, but let's assume we can:
            from blob.ipc import blob_service_pb2
            import asyncio
            
            evt = blob_service_pb2.BackendEvent()
            evt.notification.text = f"⏰ REMINDER: {message}"
            
            # also send an emote
            emote_evt = blob_service_pb2.BackendEvent()
            emote_evt.emote.emote = blob_service_pb2.EmoteCommand.HAPPY
            
            if loop:
                asyncio.run_coroutine_threadsafe(self.dispatcher.broadcast(evt), loop)
                asyncio.run_coroutine_threadsafe(self.dispatcher.broadcast(emote_evt), loop)

    def execute(self, args):
        msg = args.get('message')
        mins = args.get('minutes')
        
        if not msg or mins is None:
            return SkillResult("Missing message or minutes", False, "CONFUSED")
            
        try:
            mins = float(mins)
        except ValueError:
            return SkillResult("Minutes must be a number", False, "CONFUSED")
            
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
            
        def timer_func():
            self._fire_reminder(msg, loop)
            
        timer = threading.Timer(mins * 60, timer_func)
        timer.start()
        self.reminders.append({"message": msg, "minutes": mins, "timer": timer})
        
        return SkillResult(f"Reminder set for {mins} minutes: {msg}", True, "HAPPY")
