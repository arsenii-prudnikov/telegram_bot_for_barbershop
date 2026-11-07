"""SQLite-Datenbank. Zeiten werden als lokale Salonzeit (ISO, ohne Zeitzone) gespeichert."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    tg_id INTEGER UNIQUE,
    name TEXT NOT NULL,
    phone TEXT,
    lang TEXT NOT NULL DEFAULT 'de',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    service_id TEXT NOT NULL,
    master_id TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    price REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'booked',
    reminded_24 INTEGER NOT NULL DEFAULT 0,
    reminded_2 INTEGER NOT NULL DEFAULT 0,
    review_asked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_app_master_start ON appointments(master_id, start);
CREATE TABLE IF NOT EXISTS blocks (
    id INTEGER PRIMARY KEY,
    master_id TEXT,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS waitlist (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    service_id TEXT NOT NULL,
    day TEXT NOT NULL,
    notified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(customer_id, service_id, day)
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    appointment_id INTEGER UNIQUE NOT NULL REFERENCES appointments(id),
    stars INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""

ACTIVE = "booked"


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def parse(text: str) -> datetime:
    return datetime.fromisoformat(text)


@dataclass
class Customer:
    id: int
    tg_id: int | None
    name: str
    phone: str | None
    lang: str


@dataclass
class Appointment:
    id: int
    customer_id: int
    service_id: str
    master_id: str
    start: datetime
    end: datetime
    price: float
    status: str
    reminded_24: bool
    reminded_2: bool
    review_asked: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Appointment:
        return cls(
            id=row["id"],
            customer_id=row["customer_id"],
            service_id=row["service_id"],
            master_id=row["master_id"],
            start=parse(row["start"]),
            end=parse(row["end"]),
            price=row["price"],
            status=row["status"],
            reminded_24=bool(row["reminded_24"]),
            reminded_2=bool(row["reminded_2"]),
            review_asked=bool(row["review_asked"]),
        )


@dataclass
class Block:
    id: int
    master_id: str | None
    start: datetime
    end: datetime
    reason: str | None


class Database:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        # Bot und Web-Oberfläche laufen parallel – Schreibzugriffe serialisieren
        self.lock = threading.RLock()

    # ---------- Kunden ----------
    def get_customer_by_tg(self, tg_id: int) -> Customer | None:
        row = self.conn.execute("SELECT * FROM customers WHERE tg_id = ?", (tg_id,)).fetchone()
        return self._customer(row)

    def get_customer(self, customer_id: int) -> Customer | None:
        row = self.conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        return self._customer(row)

    def upsert_customer(self, tg_id: int | None, name: str, lang: str = "de", phone: str | None = None) -> Customer:
        with self.lock:
            existing = self.get_customer_by_tg(tg_id) if tg_id is not None else None
            if existing:
                self.conn.execute(
                    "UPDATE customers SET name = ?, phone = COALESCE(?, phone) WHERE id = ?",
                    (name, phone, existing.id),
                )
                return self.get_customer(existing.id)
            cur = self.conn.execute(
                "INSERT INTO customers (tg_id, name, phone, lang, created_at) VALUES (?, ?, ?, ?, ?)",
                (tg_id, name, phone, lang, iso(datetime.now())),
            )
            return self.get_customer(cur.lastrowid)

    def set_language(self, customer_id: int, lang: str) -> None:
        self.conn.execute("UPDATE customers SET lang = ? WHERE id = ?", (lang, customer_id))

    def set_phone(self, customer_id: int, phone: str) -> None:
        self.conn.execute("UPDATE customers SET phone = ? WHERE id = ?", (phone, customer_id))

    @staticmethod
    def _customer(row: sqlite3.Row | None) -> Customer | None:
        if row is None:
            return None
        return Customer(row["id"], row["tg_id"], row["name"], row["phone"], row["lang"])

    # ---------- Termine ----------
    def insert_appointment(self, customer_id: int, service_id: str, master_id: str,
                           start: datetime, end: datetime, price: float) -> Appointment:
        cur = self.conn.execute(
            "INSERT INTO appointments (customer_id, service_id, master_id, start, end, price, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (customer_id, service_id, master_id, iso(start), iso(end), price, iso(datetime.now())),
        )
        return self.get_appointment(cur.lastrowid)

    def get_appointment(self, appointment_id: int) -> Appointment | None:
        row = self.conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        return Appointment.from_row(row) if row else None

    def appointments_between(self, start: datetime, end: datetime, master_id: str | None = None,
                             statuses: tuple[str, ...] = (ACTIVE,)) -> list[Appointment]:
        sql = f"SELECT * FROM appointments WHERE start < ? AND end > ? AND status IN ({','.join('?' * len(statuses))})"
        params: list = [iso(end), iso(start), *statuses]
        if master_id:
            sql += " AND master_id = ?"
            params.append(master_id)
        rows = self.conn.execute(sql + " ORDER BY start", params).fetchall()
        return [Appointment.from_row(r) for r in rows]

    def customer_appointments(self, customer_id: int, after: datetime) -> list[Appointment]:
        rows = self.conn.execute(
            "SELECT * FROM appointments WHERE customer_id = ? AND status = ? AND start >= ? ORDER BY start",
            (customer_id, ACTIVE, iso(after)),
        ).fetchall()
        return [Appointment.from_row(r) for r in rows]

    def set_status(self, appointment_id: int, status: str) -> None:
        self.conn.execute("UPDATE appointments SET status = ? WHERE id = ?", (status, appointment_id))

    def move_appointment(self, appointment_id: int, master_id: str, start: datetime, end: datetime) -> None:
        self.conn.execute(
            "UPDATE appointments SET master_id = ?, start = ?, end = ?, reminded_24 = 0, reminded_2 = 0 WHERE id = ?",
            (master_id, iso(start), iso(end), appointment_id),
        )

    def mark(self, appointment_id: int, flag: str) -> None:
        if flag not in {"reminded_24", "reminded_2", "review_asked"}:
            raise ValueError(flag)
        self.conn.execute(f"UPDATE appointments SET {flag} = 1 WHERE id = ?", (appointment_id,))

    # ---------- Sperrzeiten ----------
    def add_block(self, master_id: str | None, start: datetime, end: datetime, reason: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO blocks (master_id, start, end, reason) VALUES (?, ?, ?, ?)",
            (master_id, iso(start), iso(end), reason),
        )
        return cur.lastrowid

    def blocks_between(self, start: datetime, end: datetime) -> list[Block]:
        rows = self.conn.execute(
            "SELECT * FROM blocks WHERE start < ? AND end > ? ORDER BY start", (iso(end), iso(start))
        ).fetchall()
        return [Block(r["id"], r["master_id"], parse(r["start"]), parse(r["end"]), r["reason"]) for r in rows]

    def delete_block(self, block_id: int) -> None:
        self.conn.execute("DELETE FROM blocks WHERE id = ?", (block_id,))

    # ---------- Warteliste ----------
    def add_waitlist(self, customer_id: int, service_id: str, day: str) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO waitlist (customer_id, service_id, day, created_at) VALUES (?, ?, ?, ?)",
            (customer_id, service_id, day, iso(datetime.now())),
        )
        return cur.rowcount == 1

    def waitlist_for_day(self, day: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM waitlist WHERE day = ? AND notified = 0 ORDER BY created_at, id", (day,)
        ).fetchall()

    def mark_waitlist_notified(self, entry_id: int) -> None:
        self.conn.execute("UPDATE waitlist SET notified = 1 WHERE id = ?", (entry_id,))

    # ---------- Bewertungen ----------
    def add_review(self, appointment_id: int, stars: int) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO reviews (appointment_id, stars, created_at) VALUES (?, ?, ?)",
            (appointment_id, stars, iso(datetime.now())),
        )
        return cur.rowcount == 1

    def average_rating(self) -> tuple[float | None, int]:
        row = self.conn.execute("SELECT AVG(stars) AS avg, COUNT(*) AS n FROM reviews").fetchone()
        return (round(row["avg"], 1) if row["avg"] is not None else None, row["n"])

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()
