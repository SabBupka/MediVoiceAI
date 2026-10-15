from datetime import datetime, timedelta
import sqlite3
from pathlib import Path


class ReminderManager:
    """Локальный планировщик исходящих напоминаний без реального SIP."""

    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, visit_id INTEGER NOT NULL,
            caller_id TEXT NOT NULL, scheduled_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            last_result TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, score INTEGER NOT NULL,
            comment TEXT, created_at TEXT NOT NULL
        )""")
        self.db.commit()

    def create(self, visit: dict, caller_id: str) -> dict:
        now = datetime.now().isoformat()
        scheduled = datetime.strptime(visit["scheduled_at"], "%d.%m.%Y %H:%M")
        row = self.db.execute(
            "SELECT id FROM reminders WHERE visit_id=? AND status IN ('pending','confirmed')",
            (visit["id"],),
        ).fetchone()
        if row:
            return self.get(row[0])
        self.db.execute(
            "INSERT INTO reminders(visit_id,caller_id,scheduled_at,created_at,updated_at)"
            " VALUES (?,?,?,?,?)",
            (visit["id"], caller_id, scheduled.isoformat(), now, now),
        )
        self.db.commit()
        return self.get(self.db.execute("SELECT last_insert_rowid()").fetchone()[0])

    def get(self, reminder_id: int) -> dict:
        row = self.db.execute(
            "SELECT id,visit_id,caller_id,scheduled_at,status,attempts,last_result,"
            "created_at,updated_at FROM reminders WHERE id=?", (reminder_id,),
        ).fetchone()
        if not row:
            raise KeyError(reminder_id)
        keys = ("id", "visit_id", "caller_id", "scheduled_at", "status", "attempts",
                "last_result", "created_at", "updated_at")
        return dict(zip(keys, row))

    def due(self, days: int = 1) -> list[dict]:
        now = datetime.now()
        upper = now + timedelta(days=days)
        rows = self.db.execute(
            "SELECT id FROM reminders WHERE status='pending' AND attempts < 2 "
            "AND scheduled_at BETWEEN ? AND ? ORDER BY scheduled_at",
            (now.isoformat(), upper.isoformat()),
        ).fetchall()
        return [self.get(row[0]) for row in rows]

    def result(self, reminder_id: int, result: str) -> dict:
        reminder = self.get(reminder_id)
        status = {"confirmed": "confirmed", "cancel": "cancelled",
                  "reschedule": "needs_reschedule", "no_answer": "pending"}[result]
        now = datetime.now().isoformat()
        self.db.execute(
            "UPDATE reminders SET status=?,attempts=?,last_result=?,updated_at=? WHERE id=?",
            (status, reminder["attempts"] + 1, result, now, reminder_id),
        )
        self.db.commit()
        return self.get(reminder_id)

    def feedback(self, session_id: str | None, score: int, comment: str | None) -> dict:
        now = datetime.now().isoformat()
        cur = self.db.execute(
            "INSERT INTO feedback(session_id,score,comment,created_at) VALUES (?,?,?,?)",
            (session_id, score, comment, now),
        )
        self.db.commit()
        return {"id": cur.lastrowid, "session_id": session_id, "score": score,
                "comment": comment, "created_at": now}
