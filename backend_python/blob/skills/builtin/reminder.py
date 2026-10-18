"""Persistent timers and scheduled reminders with a single background worker."""

import asyncio
from datetime import datetime
import logging
import sys
import time

from blob.skills.base import SkillInterface, SkillResult
from blob.skills.contracts import object_schema, validate_arguments
from blob.skills.reminder_store import ReminderStore

logger = logging.getLogger(__name__)
MINUTES = {"type": "number", "exclusiveMinimum": 0, "maximum": 525600}


class ReminderSkill(SkillInterface):
    argument_schema = object_schema({
        "action": {"type": "string", "enum": ["set", "list", "cancel", "snooze"], "default": "set"},
        "message": {"type": "string", "minLength": 1, "maxLength": 1000},
        "minutes": MINUTES,
        "at": {"type": "string", "minLength": 1, "maxLength": 64,
               "description": "ISO date/time, e.g. 2026-10-05T09:00:00+05:30. No offset means local time."},
        "repeat_minutes": {"type": "number", "minimum": 1, "maximum": 525600},
        "id": {"type": "string", "minLength": 1, "maxLength": 12}})
    permissions = ("reminders.manage",)

    def __init__(self, db_path=None, *, now=None):
        self.dispatcher = None
        self.store = ReminderStore(db_path)
        self._now = now or time.time
        self._wake = asyncio.Event()
        self._worker = None
        self._closed = False
        self.prompt_waiting = lambda: False
        self.maintaining = lambda: False

    @property
    def name(self):
        return "reminder"

    @property
    def description(self):
        return ("Manage reminders: set with message and either minutes from now or an ISO 'at' date/time; "
                "optional repeat_minutes repeats on a fixed interval. list shows IDs; cancel uses id; "
                "snooze uses id and minutes. Reminders persist locally and catch up when Blob restarts.")

    @property
    def triggers(self):
        return ["remind", "timer", "alarm", "snooze", "cancel reminder", "list reminders"]

    @property
    def reminders(self):
        return self.store.pending()

    def set_dispatcher(self, dispatcher):
        self.dispatcher = dispatcher

    def start(self):
        if self._closed:
            raise ValueError("Reminder service is closed.")
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run(), name="blob-reminders")

    async def close(self):
        if self._closed:
            return
        self._closed = True
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        self.store.close()

    @staticmethod
    def _date(timestamp):
        return datetime.fromtimestamp(timestamp).astimezone().strftime("%a, %Y-%m-%d %H:%M:%S %Z (%z)")

    def notification_event(self, record):
        from blob.ipc import blob_service_pb2
        message = record["message"]
        overdue = self._now() - record["due_at"] > 60
        text = ("⏰ Overdue reminder" if overdue else "⏰ REMINDER") + f" [{record['id']}]: {message}"
        if overdue:
            text += f" (was due {self._date(record['due_at'])})"
        if record.get("occurrences", 1) > 1:
            text += f" ({record['occurrences']} occurrences pending)"
        event = blob_service_pb2.BackendEvent()
        event.notification.text = text
        event.notification.delivery_id = record["delivery_id"]
        return event

    def pending_notifications(self):
        return [self.notification_event(record) for record in self.store.pending_deliveries()]

    async def _fire_reminder(self, record):
        event = self.notification_event(record)
        text = event.notification.text
        print(f"\n\033[93m{text}\033[0m\n", flush=True)
        if sys.stdout.isatty():
            self.store.acknowledge(record["delivery_id"])
        if self.dispatcher is not None:
            from blob.ipc import blob_service_pb2
            try:
                await self.dispatcher.broadcast(event)
                emote = blob_service_pb2.BackendEvent()
                emote.emote.emote = blob_service_pb2.EmoteCommand.HAPPY
                await self.dispatcher.broadcast(emote)
            except Exception:
                logger.exception("Could not broadcast reminder; pending delivery is retained")
        if self.prompt_waiting():
            print("Blob> ", end="", flush=True)

    async def _run(self):
        replayed = False
        while True:
            if self.maintaining():
                await asyncio.sleep(0.25)
                continue
            self._wake.clear()
            try:
                if not replayed:
                    for record in self.store.pending_deliveries():
                        await self._fire_reminder(record)
                    replayed = True
                while due := self.store.take_due(self._now()):
                    await self._fire_reminder(due[0])
                pending = self.store.pending()
                delay = min(60, max(0, pending[0]["due_at"] - self._now())) if pending else 60
                try:
                    await asyncio.wait_for(self._wake.wait(), delay)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Reminder worker failed; retrying in one minute")
                await asyncio.sleep(60)

    def execute(self, args):
        return SkillResult("Use async_execute for reminders.", False, "CONFUSED")

    async def async_execute(self, args):
        try:
            args = validate_arguments(self.argument_schema, args)
            if self._closed:
                raise ValueError("Reminder service is closed.")
            action = args.get("action", "set")
            allowed = {"set": {"action", "message", "minutes", "at", "repeat_minutes"},
                       "list": {"action"}, "cancel": {"action", "id"}, "snooze": {"action", "id", "minutes"}}
            if set(args) - allowed[action]:
                raise ValueError(f"Unexpected arguments for reminder action '{action}'.")
            if action == "list":
                pending = self.store.pending()
                missed = self.store.pending_deliveries()
                if not pending and not missed:
                    return SkillResult("No reminders scheduled.", True)
                lines = [f"{r['id']} · {self._date(r['due_at'])} · {r['message']}"
                         + (f" · repeats every {r['repeat_minutes']:g} minutes" if r["repeat_minutes"] is not None else "")
                         for r in pending]
                text = "Scheduled reminders:\n" + "\n".join(lines) if pending else "No reminders scheduled."
                if missed:
                    text += "\nPending deliveries (cancel or snooze by reminder ID):\n" + "\n".join(
                        f"{r['id']} · due {self._date(r['due_at'])} · {r['message']} · {r['occurrences']} occurrence(s)"
                        for r in missed)
                return SkillResult(text, True)
            now = self._now()
            if action in {"cancel", "snooze"}:
                identifier = args.get("id")
                if not identifier:
                    raise ValueError("Missing reminder id. List reminders to find it.")
                if action == "cancel":
                    changed = self.store.cancel(identifier)
                    output = f"Cancelled reminder {identifier}."
                else:
                    if "minutes" not in args:
                        raise ValueError("Snooze needs minutes.")
                    due_at = now + args["minutes"] * 60
                    changed = self.store.snooze(identifier, due_at)
                    output = f"Snoozed reminder {identifier} until {self._date(due_at)}."
                if not changed:
                    raise ValueError(f"No pending reminder with id {identifier}.")
            else:
                message = args.get("message", "").strip()
                if not message:
                    raise ValueError("Tell me what to remind you about.")
                if ("minutes" in args) == ("at" in args):
                    raise ValueError("Provide either minutes from now or an ISO 'at' date/time.")
                if "at" in args:
                    try:
                        due_at = datetime.fromisoformat(args["at"]).astimezone().timestamp()
                    except ValueError as exc:
                        raise ValueError("'at' must be an ISO date/time, e.g. 2026-10-05T09:00:00+05:30.") from exc
                    if due_at <= now:
                        raise ValueError("That time has already passed. Choose a future time.")
                else:
                    due_at = now + args["minutes"] * 60
                identifier = self.store.add(message, due_at, args.get("repeat_minutes"), now)
                output = f"✅ Reminder set [{identifier}]! I'll remind you to '{message}' at {self._date(due_at)}."
                if "repeat_minutes" in args:
                    output += f" Repeats every {args['repeat_minutes']:g} minutes."
            self.start()
            self._wake.set()
            return SkillResult(output, True, "HAPPY")
        except (ValueError, OverflowError) as exc:
            return SkillResult(str(exc), False, "CONFUSED")
        except Exception:
            logger.exception("Could not save reminder")
            return SkillResult("I couldn't update reminders. Check the local database path and backend logs.", False, "WORRIED")
