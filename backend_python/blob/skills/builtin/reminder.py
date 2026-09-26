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
        
    def _fire_reminder(self, message):
        if self.dispatcher:
            # We can't easily import protobuf here if we want decoupling, but let's assume we can:
            from blob.ipc import blob_service_pb2
            evt = blob_service_pb2.ServerEvent()
            evt.assistant_response.text = f"⏰ REMINDER: {message}"
            self.dispatcher.broadcast(evt)
            
            # also send an emote
            emote_evt = blob_service_pb2.ServerEvent()
            emote_evt.emote_command.emote = blob_service_pb2.EMOTE_HAPPY
            self.dispatcher.broadcast(emote_evt)

    def execute(self, args):
        msg = args.get('message')
        mins = args.get('minutes')
        
        if not msg or mins is None:
            return SkillResult("Missing message or minutes", False, "CONFUSED")
            
        try:
            mins = float(mins)
        except ValueError:
            return SkillResult("Minutes must be a number", False, "CONFUSED")
            
        def timer_func():
            self._fire_reminder(msg)
            
        timer = threading.Timer(mins * 60, timer_func)
        timer.start()
        self.reminders.append({"message": msg, "minutes": mins, "timer": timer})
        
        return SkillResult(f"Reminder set for {mins} minutes: {msg}", True, "HAPPY")
