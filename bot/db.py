"""Записи клиентов в SQLite. Время хранится в UTC (ISO), наружу отдаётся aware datetime."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class Booking:
    id: int
    user_id: int
    username: str
    name: str
    phone: str
    service: str
    price: int
    start: datetime
    end: datetime
    status: str


SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL, username TEXT, name TEXT, phone TEXT,
  service TEXT NOT NULL, price INTEGER, start TEXT NOT NULL, end TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active', created TEXT NOT NULL, reminded TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS bookings_start ON bookings(start);
"""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


class DB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def _row(self, r) -> Booking:
        return Booking(r["id"], r["user_id"], r["username"] or "", r["name"] or "", r["phone"] or "", r["service"],
                       r["price"] or 0, _dt(r["start"]), _dt(r["end"]), r["status"])

    def busy(self, frm: datetime, to: datetime) -> list[tuple[datetime, datetime]]:
        rows = self.conn.execute("SELECT start, end FROM bookings WHERE status='active' AND end > ? AND start < ?",
                                 (_iso(frm), _iso(to))).fetchall()
        return [(_dt(r["start"]), _dt(r["end"])) for r in rows]

    def add(self, user_id: int, username: str, name: str, phone: str, service: str, price: int,
            start: datetime, minutes: int) -> Booking:
        end = start + timedelta(minutes=minutes)
        cur = self.conn.execute(
            "INSERT INTO bookings(user_id, username, name, phone, service, price, start, end, created) VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, username, name, phone, service, price, _iso(start), _iso(end), _iso(datetime.now(timezone.utc))))
        self.conn.commit()
        return self.get(cur.lastrowid)

    def get(self, booking_id: int) -> Booking | None:
        r = self.conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        return self._row(r) if r else None

    def upcoming_for(self, user_id: int, now: datetime) -> list[Booking]:
        rows = self.conn.execute("SELECT * FROM bookings WHERE user_id=? AND status='active' AND start > ? ORDER BY start",
                                 (user_id, _iso(now))).fetchall()
        return [self._row(r) for r in rows]

    def between(self, frm: datetime, to: datetime) -> list[Booking]:
        rows = self.conn.execute("SELECT * FROM bookings WHERE status='active' AND start >= ? AND start < ? ORDER BY start",
                                 (_iso(frm), _iso(to))).fetchall()
        return [self._row(r) for r in rows]

    def cancel(self, booking_id: int) -> None:
        self.conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
        self.conn.commit()

    def due_reminders(self, now: datetime, hours: int) -> list[Booking]:
        """Записи, до которых осталось не больше hours часов и по которым это напоминание ещё не отправляли."""
        tag = f"{hours}h;"
        rows = self.conn.execute(
            "SELECT * FROM bookings WHERE status='active' AND start > ? AND start <= ? AND instr(reminded, ?) = 0",
            (_iso(now), _iso(now + timedelta(hours=hours)), tag)).fetchall()
        return [self._row(r) for r in rows]

    def mark_reminded(self, booking_id: int, hours: int) -> None:
        self.conn.execute("UPDATE bookings SET reminded = reminded || ? WHERE id=?", (f"{hours}h;", booking_id))
        self.conn.commit()
