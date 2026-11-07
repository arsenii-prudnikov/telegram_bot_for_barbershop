from datetime import datetime
from pathlib import Path

import pytest

from termin_bot.booking import BookingService
from termin_bot.db import Database
from termin_bot.salon import load_salon

ROOT = Path(__file__).resolve().parent.parent


class Clock:
    """Steuerbare Uhr für Tests."""

    def __init__(self, now: datetime):
        self.value = now

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def salon():
    return load_salon(ROOT / "salon.example.yaml")


@pytest.fixture
def db():
    return Database(":memory:")


@pytest.fixture
def clock():
    # Montag, 9. November 2026, 10:00 Uhr (montags ist der Beispielsalon geschlossen)
    return Clock(datetime(2026, 11, 9, 10, 0))


@pytest.fixture
def service(salon, db, clock):
    return BookingService(salon, db, clock)


@pytest.fixture
def customer(db):
    return db.upsert_customer(111, "Anna", "de", "+49 151 0000000")
