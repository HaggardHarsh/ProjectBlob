"""Local SQLite reminders, independent of conversational memory."""

import os
from pathlib import Path
import sqlite3
import uuid


class ReminderStore:
    def __init__(self, path=None):
        if path is not None:
            path = Path(path).expanduser()
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path) if path is not None else ":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA secure_delete=ON")
        if path is not None:
            os.chmod(path, 0o600)
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY, message TEXT NOT NULL, due_at REAL NOT NULL,
                repeat_minutes REAL, created_at REAL NOT NULL)""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS reminder_deliveries (
                delivery_id TEXT PRIMARY KEY, reminder_id TEXT NOT NULL UNIQUE,
                message TEXT NOT NULL, due_at REAL NOT NULL, repeat_minutes REAL,
                created_at REAL NOT NULL, occurrences INTEGER NOT NULL DEFAULT 1)""")

    def pending(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM reminders ORDER BY due_at, id")]

    def add(self, message, due_at, repeat_minutes, now):
        if self.db.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] >= 100:
            raise ValueError("You already have 100 reminders. Cancel one before adding another.")
        identifier = uuid.uuid4().hex[:12]
        with self.db:
            self.db.execute("INSERT INTO reminders VALUES (?, ?, ?, ?, ?)",
                            (identifier, message, due_at, repeat_minutes, now))
        return identifier

    def cancel(self, identifier):
        with self.db:
            pending = self.db.execute("DELETE FROM reminders WHERE id = ?", (identifier,)).rowcount
            delivered = self.db.execute("DELETE FROM reminder_deliveries WHERE reminder_id = ?", (identifier,)).rowcount
            return pending + delivered > 0

    def snooze(self, identifier, due_at):
        with self.db:
            changed = self.db.execute("UPDATE reminders SET due_at = ? WHERE id = ?", (due_at, identifier)).rowcount
            if not changed:
                missed = self.db.execute("SELECT * FROM reminder_deliveries WHERE reminder_id = ?", (identifier,)).fetchone()
                if missed is None:
                    return False
                if self.db.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] >= 100:
                    raise ValueError("You already have 100 reminders. Cancel one before snoozing this one.")
                self.db.execute("INSERT INTO reminders VALUES (?, ?, ?, ?, ?)",
                    (identifier, missed["message"], due_at, missed["repeat_minutes"], missed["created_at"]))
            self.db.execute("DELETE FROM reminder_deliveries WHERE reminder_id = ?", (identifier,))
            return True

    def pending_deliveries(self):
        return [dict(row) for row in self.db.execute("""SELECT delivery_id, reminder_id AS id,
            message, due_at, repeat_minutes, created_at, occurrences FROM reminder_deliveries
            ORDER BY due_at, reminder_id""")]

    def acknowledge(self, delivery_id):
        with self.db:
            return self.db.execute("DELETE FROM reminder_deliveries WHERE delivery_id = ?", (delivery_id,)).rowcount > 0

    def take_due(self, now):
        """Atomically queue delivery and advance/remove the scheduled occurrence.

        Recurring reminders produce one catch-up notification after downtime and
        retain their original cadence, rather than flooding the user with misses.
        """
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            due = [dict(row) for row in self.db.execute(
                "SELECT * FROM reminders WHERE due_at <= ? ORDER BY due_at, id LIMIT 1", (now,))]
            for record in due:
                repeat = record["repeat_minutes"]
                occurrences = 1 if repeat is None else int((now - record["due_at"]) // (repeat * 60)) + 1
                previous = self.db.execute("SELECT * FROM reminder_deliveries WHERE reminder_id = ?", (record["id"],)).fetchone()
                if not previous and self.db.execute("SELECT COUNT(*) FROM reminder_deliveries").fetchone()[0] >= 1000:
                    raise ValueError("Pending reminder delivery storage is full. Open chat or dismiss pending reminders.")
                delivery_id = uuid.uuid4().hex
                # Rotate the ID so an ack for an earlier rendered repeat cannot
                # remove a later occurrence that has not yet been displayed.
                self.db.execute("""INSERT INTO reminder_deliveries VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(reminder_id) DO UPDATE SET delivery_id=excluded.delivery_id,
                    occurrences=reminder_deliveries.occurrences+excluded.occurrences""",
                    (delivery_id, record["id"], record["message"], record["due_at"], repeat, record["created_at"], occurrences))
                record["delivery_id"] = delivery_id
                record["occurrences"] = occurrences + (previous["occurrences"] if previous else 0)
                if repeat is None:
                    self.db.execute("DELETE FROM reminders WHERE id = ?", (record["id"],))
                else:
                    interval = repeat * 60
                    next_due = record["due_at"] + (int((now - record["due_at"]) // interval) + 1) * interval
                    self.db.execute("UPDATE reminders SET due_at = ? WHERE id = ?", (next_due, record["id"]))
        return due

    def close(self):
        self.db.close()
