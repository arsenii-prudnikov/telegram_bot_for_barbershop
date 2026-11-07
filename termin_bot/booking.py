"""Geschäftslogik: Buchen, Verschieben, Absagen, Warteliste, Erinnerungen und Statistik.

Diese Schicht kennt kein Telegram – dadurch ist sie vollständig mit Tests abgedeckt und
könnte genauso von WhatsApp, einer Website oder einer App benutzt werden.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .db import Appointment, Database
from .salon import Salon
from .slots import free_slots


class BookingError(Exception):
    """Fachlicher Fehler, der dem Kunden angezeigt wird (Schlüssel für die Übersetzung)."""

    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


@dataclass
class WaitlistOffer:
    customer_id: int
    service_id: str
    day: date
    first_free: datetime


@dataclass
class Reminder:
    appointment: Appointment
    kind: str  # "24h", "2h" oder "review"


@dataclass
class Stats:
    appointments: int = 0
    revenue: float = 0.0
    cancelled: int = 0
    no_shows: int = 0
    new_customers: int = 0
    rating: float | None = None
    reviews: int = 0
    top_services: list[tuple[str, int]] = field(default_factory=list)
    per_master: list[tuple[str, int]] = field(default_factory=list)
    utilization: float = 0.0  # Auslastung in Prozent


class BookingService:
    def __init__(self, salon: Salon, db: Database, clock: Callable[[], datetime] | None = None):
        self.salon = salon
        self.db = db
        self._clock = clock

    def now(self) -> datetime:
        if self._clock:
            return self._clock()
        return datetime.now(self.salon.tz).replace(tzinfo=None, second=0, microsecond=0)

    # ---------- Buchen ----------
    def book(self, customer_id: int, service_id: str, start: datetime, master_id: str | None = None) -> Appointment:
        service = self.salon.service(service_id)
        with self.db.lock:
            # Erneut prüfen: zwei Kunden könnten gleichzeitig dieselbe Zeit wählen
            slots = free_slots(self.salon, self.db, service_id, start.date(), self.now(), master_id)
            match = next((s for s in slots if s.start == start), None)
            if match is None:
                raise BookingError("slot_taken")
            return self.db.insert_appointment(
                customer_id, service_id, match.master_id, match.start, match.end, service.price
            )

    def can_change(self, appointment: Appointment) -> bool:
        return appointment.start - self.now() >= timedelta(hours=self.salon.cancel_hours)

    def _own(self, appointment_id: int, customer_id: int | None) -> Appointment:
        app = self.db.get_appointment(appointment_id)
        if app is None or app.status != "booked":
            raise BookingError("not_found")
        if customer_id is not None and app.customer_id != customer_id:
            raise BookingError("not_found")
        return app

    def cancel(self, appointment_id: int, customer_id: int | None = None) -> tuple[Appointment, list[WaitlistOffer]]:
        """Sagt einen Termin ab. ``customer_id=None`` bedeutet: Absage durch den Salon."""
        with self.db.lock:
            app = self._own(appointment_id, customer_id)
            if customer_id is not None and not self.can_change(app):
                raise BookingError("too_late")
            self.db.set_status(app.id, "cancelled")
            return app, self.waitlist_offers(app.start.date())

    def reschedule(self, appointment_id: int, new_start: datetime, customer_id: int | None = None,
                   master_id: str | None = None) -> tuple[Appointment, list[WaitlistOffer]]:
        with self.db.lock:
            app = self._own(appointment_id, customer_id)
            if customer_id is not None and not self.can_change(app):
                raise BookingError("too_late")
            slots = free_slots(self.salon, self.db, app.service_id, new_start.date(), self.now(),
                               master_id, exclude_appointment=app.id)
            match = next((s for s in slots if s.start == new_start), None)
            if match is None:
                raise BookingError("slot_taken")
            old_day = app.start.date()
            self.db.move_appointment(app.id, match.master_id, match.start, match.end)
            offers = self.waitlist_offers(old_day) if old_day != new_start.date() else []
            return self.db.get_appointment(app.id), offers

    def upcoming(self, customer_id: int) -> list[Appointment]:
        return self.db.customer_appointments(customer_id, self.now())

    # ---------- Warteliste ----------
    def join_waitlist(self, customer_id: int, service_id: str, day: date) -> bool:
        return self.db.add_waitlist(customer_id, service_id, day.isoformat())

    def waitlist_offers(self, day: date) -> list[WaitlistOffer]:
        """Wer auf der Warteliste steht und jetzt einen freien Termin bekommen kann."""
        offers = []
        for entry in self.db.waitlist_for_day(day.isoformat()):
            slots = free_slots(self.salon, self.db, entry["service_id"], day, self.now())
            if slots:
                self.db.mark_waitlist_notified(entry["id"])
                offers.append(WaitlistOffer(entry["customer_id"], entry["service_id"], day, slots[0].start))
        return offers

    # ---------- Erinnerungen ----------
    def due_reminders(self) -> list[Reminder]:
        now = self.now()
        due: list[Reminder] = []
        window = self.db.appointments_between(now - timedelta(days=1), now + timedelta(hours=24, minutes=1))
        for app in window:
            until = app.start - now
            if not app.reminded_24 and timedelta(hours=2, minutes=1) < until <= timedelta(hours=24):
                due.append(Reminder(app, "24h"))
            elif not app.reminded_2 and timedelta(0) < until <= timedelta(hours=2):
                due.append(Reminder(app, "2h"))
            elif not app.review_asked and now - app.end >= timedelta(hours=2):
                due.append(Reminder(app, "review"))
        return due

    def mark_sent(self, reminder: Reminder) -> None:
        app = reminder.appointment
        if reminder.kind == "24h":
            self.db.mark(app.id, "reminded_24")
        elif reminder.kind == "2h":
            self.db.mark(app.id, "reminded_2")
        else:
            self.db.mark(app.id, "review_asked")
            self.db.set_status(app.id, "done")

    def rate(self, appointment_id: int, customer_id: int, stars: int) -> bool:
        app = self.db.get_appointment(appointment_id)
        if app is None or app.customer_id != customer_id or not 1 <= stars <= 5:
            raise BookingError("not_found")
        return self.db.add_review(appointment_id, stars)

    # ---------- Verwaltung ----------
    def agenda(self, day: date) -> list[Appointment]:
        start = datetime.combine(day, datetime.min.time())
        return self.db.appointments_between(start, start + timedelta(days=1), statuses=("booked", "done", "no_show"))

    def mark_no_show(self, appointment_id: int) -> None:
        self.db.set_status(appointment_id, "no_show")

    def block(self, start: datetime, end: datetime, master_id: str | None = None, reason: str = "") -> int:
        if end <= start:
            raise BookingError("invalid_range")
        return self.db.add_block(master_id, start, end, reason or None)

    def stats(self, start: date, end: date) -> Stats:
        """Kennzahlen für den Zeitraum [start, end]."""
        a = datetime.combine(start, datetime.min.time())
        b = datetime.combine(end + timedelta(days=1), datetime.min.time())
        rows = self.db.appointments_between(a, b, statuses=("booked", "done", "no_show", "cancelled"))
        result = Stats()
        services: Counter[str] = Counter()
        masters: Counter[str] = Counter()
        booked_minutes = 0
        for app in rows:
            if app.status == "cancelled":
                result.cancelled += 1
                continue
            if app.status == "no_show":
                result.no_shows += 1
                continue
            result.appointments += 1
            result.revenue += app.price
            services[app.service_id] += 1
            masters[app.master_id] += 1
            booked_minutes += int((app.end - app.start).total_seconds() // 60)
        result.top_services = services.most_common(5)
        result.per_master = masters.most_common()
        result.new_customers = self.db.query(
            "SELECT COUNT(*) AS n FROM customers WHERE created_at >= ? AND created_at < ?",
            (a.strftime("%Y-%m-%dT%H:%M"), b.strftime("%Y-%m-%dT%H:%M")),
        )[0]["n"]
        result.rating, result.reviews = self.db.average_rating()

        capacity = 0
        day = start
        while day <= end:
            for m in self.salon.masters:
                for rng in self.salon.working_ranges(m, day):
                    capacity += (datetime.combine(day, rng.end) - datetime.combine(day, rng.start)).seconds // 60
            day += timedelta(days=1)
        result.utilization = round(100 * booked_minutes / capacity, 1) if capacity else 0.0
        return result
