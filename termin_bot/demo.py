"""Erfundene Demo-Daten, damit Dashboard und Bot sofort etwas zeigen."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from .booking import BookingError, BookingService
from .slots import free_slots

NAMES = ["Anna K.", "Mehmet Y.", "Julia S.", "Olena P.", "Lukas B.", "Sophie M.", "Ayşe D.", "Max W.",
         "Irina T.", "Leon H.", "Emma F.", "Dmytro K.", "Mia R.", "Can Ö.", "Laura G.", "Paul Z.",
         "Natalia V.", "Finn L.", "Elif A.", "Tim S.", "Hanna J.", "Yusuf E.", "Clara N.", "Ben O."]
LANGS = ["de", "de", "de", "ru", "uk", "tr", "en"]


def fill(service: BookingService, seed: int = 7, past_days: int = 14, future_days: int = 7) -> int:
    rnd = random.Random(seed)
    db, salon = service.db, service.salon
    if db.query("SELECT COUNT(*) AS n FROM appointments")[0]["n"]:
        return 0
    customers = [db.upsert_customer(None, name, rnd.choice(LANGS), f"+49 151 {rnd.randint(1000000, 9999999)}")
                 for name in NAMES]
    now = service.now()
    created = 0
    # Herrenschnitte sind am häufigsten, Färben am seltensten
    weights = [5, 3, 4, 2, 3] if len(salon.services) == 5 else None
    for offset in range(-past_days, future_days + 1):
        day = now.date() + timedelta(days=offset)
        # Vergangenheit: freie Zeiten so berechnen, als wäre es früh morgens an diesem Tag
        reference = datetime.combine(day, datetime.min.time()) - timedelta(hours=3) if offset <= 0 else now
        target = rnd.randint(8, 16) if offset <= 0 else rnd.randint(6, 12)
        for _ in range(target):
            s = rnd.choices(salon.services, weights=weights)[0]
            slots = free_slots(salon, db, s.id, day, reference)
            if not slots:
                continue
            slot = rnd.choice(slots)
            customer = rnd.choice(customers)
            if offset <= 0:
                app = db.insert_appointment(customer.id, s.id, slot.master_id, slot.start, slot.end, s.price)
                if slot.end <= now:
                    roll = rnd.random()
                    if roll < 0.05:
                        db.set_status(app.id, "no_show")
                    elif roll < 0.10:
                        db.set_status(app.id, "cancelled")
                    else:
                        db.set_status(app.id, "done")
                        for flag in ("reminded_24", "reminded_2", "review_asked"):
                            db.mark(app.id, flag)
                        if rnd.random() < 0.6:
                            db.add_review(app.id, rnd.choices([5, 4, 3], weights=[7, 3, 1])[0])
            else:
                try:
                    service.book(customer.id, s.id, slot.start, slot.master_id)
                except BookingError:
                    continue
            created += 1
    lunch = now.date() + timedelta(days=2)
    service.block(datetime.combine(lunch, datetime.min.time()).replace(hour=15),
                  datetime.combine(lunch, datetime.min.time()).replace(hour=17), "lena", "Fortbildung")
    return created
