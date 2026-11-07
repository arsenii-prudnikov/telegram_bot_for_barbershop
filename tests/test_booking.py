from datetime import date, datetime, timedelta

import pytest

from termin_bot.booking import BookingError
from termin_bot.slots import free_slots

T10 = datetime(2026, 11, 10, 10, 0)


def test_book_and_list(service, customer):
    app = service.book(customer.id, "herrenschnitt", T10)
    assert app.master_id == "murat" and app.end == T10 + timedelta(minutes=30) and app.price == 25
    assert [a.id for a in service.upcoming(customer.id)] == [app.id]


def test_double_booking_is_rejected(service, db, customer):
    other = db.upsert_customer(222, "Ben")
    service.book(customer.id, "herrenschnitt", T10)
    with pytest.raises(BookingError) as err:
        service.book(other.id, "herrenschnitt", T10)
    assert err.value.key == "slot_taken"


def test_wrong_master_for_service(service, customer):
    with pytest.raises(BookingError):
        service.book(customer.id, "farbe", T10, master_id="murat")


def test_cancel_frees_slot(service, customer):
    app = service.book(customer.id, "herrenschnitt", T10)
    service.cancel(app.id, customer.id)
    assert service.upcoming(customer.id) == []
    service.book(customer.id, "herrenschnitt", T10)  # wieder frei


def test_cancel_too_late(service, clock, customer):
    app = service.book(customer.id, "herrenschnitt", T10)
    clock.value = T10 - timedelta(hours=2)
    with pytest.raises(BookingError) as err:
        service.cancel(app.id, customer.id)
    assert err.value.key == "too_late"
    service.cancel(app.id)  # der Salon darf immer absagen


def test_cannot_cancel_foreign_appointment(service, db, customer):
    app = service.book(customer.id, "herrenschnitt", T10)
    stranger = db.upsert_customer(999, "Fremd")
    with pytest.raises(BookingError):
        service.cancel(app.id, stranger.id)


def test_reschedule(service, customer):
    app = service.book(customer.id, "herrenschnitt", T10)
    moved, _ = service.reschedule(app.id, datetime(2026, 11, 11, 15, 0), customer.id)
    assert moved.start == datetime(2026, 11, 11, 15, 0)
    assert not moved.reminded_24


def test_reschedule_to_overlapping_own_time(service, customer):
    app = service.book(customer.id, "herrenschnitt", T10)
    moved, _ = service.reschedule(app.id, T10 + timedelta(minutes=15), customer.id)
    assert moved.start == T10 + timedelta(minutes=15)


def test_waitlist_offer_after_cancel(service, db, salon, customer):
    tuesday = date(2026, 11, 10)
    # Murat (einziger Herrenfriseur) an diesem Tag komplett ausbuchen
    booked = []
    while free := free_slots(salon, db, "herrenschnitt", tuesday, service.now()):
        guest = db.upsert_customer(1000 + len(booked), f"Gast {len(booked)}")
        booked.append(service.book(guest.id, "herrenschnitt", free[0].start))
    assert len(booked) > 10
    assert service.join_waitlist(customer.id, "herrenschnitt", tuesday)
    assert not service.join_waitlist(customer.id, "herrenschnitt", tuesday)  # nur einmal
    _, offers = service.cancel(booked[3].id)
    assert len(offers) == 1 and offers[0].customer_id == customer.id
    assert offers[0].first_free == booked[3].start
    _, offers = service.cancel(booked[4].id)
    assert offers == []  # schon benachrichtigt


def test_reminders_flow(service, clock, customer):
    app = service.book(customer.id, "herrenschnitt", datetime(2026, 11, 11, 15, 0))
    clock.value = datetime(2026, 11, 10, 14, 0)
    assert service.due_reminders() == []
    clock.value = datetime(2026, 11, 10, 15, 0)
    due = service.due_reminders()
    assert [r.kind for r in due] == ["24h"]
    service.mark_sent(due[0])
    assert service.due_reminders() == []
    clock.value = datetime(2026, 11, 11, 13, 30)
    due = service.due_reminders()
    assert [r.kind for r in due] == ["2h"]
    service.mark_sent(due[0])
    clock.value = datetime(2026, 11, 11, 17, 30)
    due = service.due_reminders()
    assert [r.kind for r in due] == ["review"]
    service.mark_sent(due[0])
    assert service.db.get_appointment(app.id).status == "done"
    assert service.rate(app.id, customer.id, 5)
    assert not service.rate(app.id, customer.id, 4)  # nur eine Bewertung


def test_late_booking_skips_24h_reminder(service, clock, customer):
    clock.value = datetime(2026, 11, 10, 9, 0)
    service.book(customer.id, "herrenschnitt", datetime(2026, 11, 10, 12, 0))
    clock.value = datetime(2026, 11, 10, 10, 30)
    assert [r.kind for r in service.due_reminders()] == ["2h"]


def test_stats(service, db, customer):
    a = service.book(customer.id, "herrenschnitt", T10)
    service.book(customer.id, "farbe", datetime(2026, 11, 10, 14, 0))
    c = service.book(customer.id, "bart", datetime(2026, 11, 11, 9, 0))
    service.cancel(c.id, customer.id)
    service.mark_no_show(a.id)
    stats = service.stats(date(2026, 11, 9), date(2026, 11, 15))
    assert stats.appointments == 1 and stats.revenue == 89
    assert stats.cancelled == 1 and stats.no_shows == 1
    assert stats.top_services == [("farbe", 1)]
    assert 0 < stats.utilization < 100


def test_block_validation(service):
    with pytest.raises(BookingError):
        service.block(T10, T10)
