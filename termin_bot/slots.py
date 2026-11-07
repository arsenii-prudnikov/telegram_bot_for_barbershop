"""Berechnung freier Termine.

Ein Startzeitpunkt ist frei, wenn die komplette Leistung (plus Puffer) in die Arbeitszeit des
Mitarbeiters passt und sich weder mit einem Termin noch mit einer Sperrzeit überschneidet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .db import Database
from .salon import Master, Salon


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    master_id: str


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def _busy(salon: Salon, db: Database, master: Master, day: date) -> list[tuple[datetime, datetime]]:
    day_start = datetime.combine(day, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    pad = timedelta(minutes=salon.buffer)
    busy = [(a.start, a.end + pad) for a in db.appointments_between(day_start, day_end, master.id)]
    busy += [
        (b.start, b.end)
        for b in db.blocks_between(day_start, day_end)
        if b.master_id in (None, master.id)
    ]
    return busy


def master_slots(salon: Salon, db: Database, master: Master, service_id: str, day: date,
                 now: datetime, exclude_appointment: int | None = None) -> list[Slot]:
    if not master.offers(service_id):
        return []
    service = salon.service(service_id)
    duration = timedelta(minutes=service.duration)
    step = timedelta(minutes=salon.slot_step)
    earliest = now + timedelta(minutes=salon.min_lead_minutes)
    busy = _busy(salon, db, master, day)
    if exclude_appointment is not None:
        own = db.get_appointment(exclude_appointment)
        if own:
            pad = timedelta(minutes=salon.buffer)
            busy = [b for b in busy if b != (own.start, own.end + pad)]

    slots: list[Slot] = []
    for rng in salon.working_ranges(master, day):
        t = datetime.combine(day, rng.start)
        limit = datetime.combine(day, rng.end)
        while t + duration <= limit:
            end = t + duration
            if t >= earliest and not any(_overlaps(t, end, b0, b1) for b0, b1 in busy):
                slots.append(Slot(t, end, master.id))
            t += step
    return slots


def free_slots(salon: Salon, db: Database, service_id: str, day: date, now: datetime,
               master_id: str | None = None, exclude_appointment: int | None = None) -> list[Slot]:
    """Freie Startzeiten für einen Tag.

    Ohne Wunsch-Mitarbeiter wird pro Uhrzeit der Mitarbeiter mit den wenigsten Terminen
    an diesem Tag gewählt – so verteilt sich die Arbeit gleichmäßig im Team.
    """
    if (day - now.date()).days > salon.horizon_days or day < now.date():
        return []
    masters = [salon.master(master_id)] if master_id else salon.masters_for(service_id)
    if master_id:
        return master_slots(salon, db, masters[0], service_id, day, now, exclude_appointment)

    day_start = datetime.combine(day, datetime.min.time())
    load = {
        m.id: len(db.appointments_between(day_start, day_start + timedelta(days=1), m.id)) for m in masters
    }
    best: dict[datetime, Slot] = {}
    for m in sorted(masters, key=lambda m: (load[m.id], m.id)):
        for slot in master_slots(salon, db, m, service_id, day, now, exclude_appointment):
            best.setdefault(slot.start, slot)
    return [best[k] for k in sorted(best)]


def available_days(salon: Salon, db: Database, service_id: str, now: datetime,
                   master_id: str | None = None, days: int | None = None) -> dict[date, int]:
    """Anzahl freier Startzeiten pro Tag (für den Kalender)."""
    result = {}
    for offset in range((days or salon.horizon_days) + 1):
        day = now.date() + timedelta(days=offset)
        result[day] = len(free_slots(salon, db, service_id, day, now, master_id))
    return result
