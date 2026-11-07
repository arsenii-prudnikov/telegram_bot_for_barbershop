from datetime import date, datetime, time

from termin_bot.salon import TimeRange
from termin_bot.slots import available_days, free_slots

TUESDAY = date(2026, 11, 10)


def test_closed_on_monday(salon, db, clock):
    assert free_slots(salon, db, "herrenschnitt", date(2026, 11, 9), clock()) == []


def test_slots_respect_opening_hours_and_lunch_break(salon, db, clock):
    slots = free_slots(salon, db, "herrenschnitt", TUESDAY, clock())
    starts = [s.start.time() for s in slots]
    assert starts[0] == time(9, 0)
    # 30 Minuten müssen vor der Mittagspause (13:00) fertig sein
    assert time(12, 30) in starts and time(12, 45) not in starts
    assert time(14, 0) in starts
    assert starts[-1] == time(18, 30)
    assert all(s.master_id == "murat" for s in slots)


def test_long_service_needs_enough_time(salon, db, clock):
    slots = free_slots(salon, db, "farbe", TUESDAY, clock())  # 120 Minuten
    starts = [s.start.time() for s in slots]
    assert time(11, 0) in starts and time(11, 15) not in starts
    assert starts[-1] == time(17, 0)


def test_minimum_lead_time(salon, db, clock):
    clock.value = datetime(2026, 11, 10, 9, 50)
    starts = [s.start.time() for s in free_slots(salon, db, "herrenschnitt", TUESDAY, clock())]
    assert time(11, 45) not in starts
    assert starts[0] == time(12, 0)  # frühestens 2 Stunden später, im 15-Minuten-Raster


def test_booked_time_and_buffer_are_blocked(salon, db, clock, customer):
    db.insert_appointment(customer.id, "herrenschnitt", "murat",
                          datetime(2026, 11, 10, 10, 0), datetime(2026, 11, 10, 10, 30), 25)
    starts = [s.start.time() for s in free_slots(salon, db, "herrenschnitt", TUESDAY, clock())]
    assert time(9, 30) in starts          # endet genau um 10:00
    assert time(9, 45) not in starts      # würde überlappen
    assert time(10, 15) not in starts
    assert time(10, 30) not in starts     # 5 Minuten Puffer
    assert time(10, 45) in starts


def test_block_for_one_master(salon, db, clock):
    db.add_block("murat", datetime(2026, 11, 10, 9, 0), datetime(2026, 11, 10, 19, 0), "Urlaub")
    assert free_slots(salon, db, "herrenschnitt", TUESDAY, clock()) == []
    assert free_slots(salon, db, "damenschnitt", TUESDAY, clock())  # Lena arbeitet


def test_salon_wide_block(salon, db, clock):
    db.add_block(None, datetime(2026, 11, 10, 0, 0), datetime(2026, 11, 11, 0, 0), "Fortbildung")
    assert free_slots(salon, db, "damenschnitt", TUESDAY, clock()) == []


def test_master_with_own_hours(salon, db, clock):
    slots = free_slots(salon, db, "augenbrauen", TUESDAY, clock(), master_id="oksana")
    assert slots and all(s.start.time() < time(13, 0) for s in slots)


def test_any_master_balances_load(salon, db, clock, customer):
    db.insert_appointment(customer.id, "augenbrauen", "lena",
                          datetime(2026, 11, 10, 15, 0), datetime(2026, 11, 10, 15, 30), 29)
    slot = next(s for s in free_slots(salon, db, "augenbrauen", TUESDAY, clock()) if s.start.time() == time(9, 0))
    assert slot.master_id == "oksana"  # Lena hat schon einen Termin


def test_holidays_and_horizon(salon, db, clock):
    assert free_slots(salon, db, "herrenschnitt", date(2026, 12, 24), clock()) == []
    assert free_slots(salon, db, "herrenschnitt", date(2026, 12, 31), clock()) == []
    days = available_days(salon, db, "herrenschnitt", clock())
    assert len(days) == salon.horizon_days + 1
    assert days[date(2026, 11, 9)] == 0 and days[TUESDAY] > 0


def test_time_range_parse():
    assert str(TimeRange.parse("09:00 - 13:30")) == "09:00–13:30"
