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
        if path is not None:
            os.chmod(path, 0o600)
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY, message TEXT NOT NULL, due_at REAL NOT NULL,
                repeat_minutes REAL, created_at REAL NOT NULL)""")

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
            return self.db.execute("DELETE FROM reminders WHERE id = ?", (identifier,)).rowcount > 0

    def snooze(self, identifier, due_at):
        with self.db:
            return self.db.execute("UPDATE reminders SET due_at = ? WHERE id = ?", (due_at, identifier)).rowcount > 0

    def take_due(self, now):
        """Advance/remove due records atomically before publishing notifications.

        Recurring reminders produce one catch-up notification after downtime and
        retain their original cadence, rather than flooding the user with misses.
        """
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            due = [dict(row) for row in self.db.execute(
                "SELECT * FROM reminders WHERE due_at <= ? ORDER BY due_at, id LIMIT 1", (now,))]
            for record in due:
                repeat = record["repeat_minutes"]
                if repeat is None:
                    self.db.execute("DELETE FROM reminders WHERE id = ?", (record["id"],))
                else:
                    interval = repeat * 60
                    next_due = record["due_at"] + (int((now - record["due_at"]) // interval) + 1) * interval
                    self.db.execute("UPDATE reminders SET due_at = ? WHERE id = ?", (next_due, record["id"]))
        return due

    def close(self):
        self.db.close()
