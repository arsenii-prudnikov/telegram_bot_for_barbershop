from datetime import date, datetime

import pytest
import yaml
from fastapi.testclient import TestClient

from termin_bot.demo import fill
from termin_bot.i18n import LANGUAGES, LOCALE_DIR, detect, fmt_day, summary, t
from termin_bot.ics import calendar, event
from termin_bot.web.app import create_app


def test_all_languages_have_all_keys():
    base = set(yaml.safe_load((LOCALE_DIR / "de.yaml").read_text(encoding="utf-8")))
    for lang in LANGUAGES:
        keys = set(yaml.safe_load((LOCALE_DIR / f"{lang}.yaml").read_text(encoding="utf-8")))
        assert keys == base, f"{lang}: fehlt {base - keys}, zu viel {keys - base}"


@pytest.mark.parametrize("lang", LANGUAGES)
def test_placeholders_work_in_every_language(lang, salon):
    text = summary(lang, salon, "herrenschnitt", "murat", datetime(2026, 11, 10, 10), datetime(2026, 11, 10, 10, 30))
    assert "Murat" in text and "25 €" in text and "10:00" in text
    assert t(lang, "booked", summary=text, address="X")
    assert t(lang, "welcome", name="A", salon="B")


def test_dates_and_detection():
    assert fmt_day("de", date(2026, 11, 10)) == "Di, 10. November"
    assert fmt_day("ru", date(2026, 11, 10)) == "Вт, 10 ноября"
    assert detect("de-AT") == "de" and detect("fr") == "de" and detect(None) == "de"


def test_ics_file(salon, service, customer):
    app = service.book(customer.id, "herrenschnitt", datetime(2026, 11, 10, 10, 0))
    data = calendar(salon, [event(salon, app, "Herrenschnitt, Studio; Nordlicht")]).decode()
    assert data.startswith("BEGIN:VCALENDAR\r\n") and data.endswith("END:VCALENDAR\r\n")
    assert "DTSTART:20261110T090000Z" in data  # 10:00 MEZ = 09:00 UTC
    assert "SUMMARY:Herrenschnitt\\, Studio\\; Nordlicht" in data
    assert all(len(line.encode()) <= 75 for line in data.split("\r\n"))


def test_dashboard_requires_token(service):
    client = TestClient(create_app(service, token="geheim"))
    assert client.get("/api/day").status_code == 401
    assert client.get("/api/day?t=falsch").status_code == 401
    assert client.get("/api/day", headers={"x-token": "geheim"}).status_code == 200
    page = client.get("/?t=geheim")
    assert page.status_code == 200 and "token" in page.cookies
    assert client.get("/api/health").status_code == 200


def test_dashboard_api(service, customer):
    client = TestClient(create_app(service))
    app = service.book(customer.id, "herrenschnitt", datetime(2026, 11, 10, 10, 0))
    day = client.get("/api/day?d=2026-11-10").json()
    assert day["label"] == "Di, 10. November"
    assert [a["customer"] for a in day["appointments"]] == ["Anna"]
    assert {m["id"] for m in day["masters"]} == {"lena", "murat", "oksana"}

    assert client.post(f"/api/appointments/{app.id}/noshow").json() == {"ok": True}
    assert client.post("/api/appointments/999/cancel").status_code == 404
    r = client.post("/api/blocks", json={"start": "2026-11-12T12:00", "end": "2026-11-12T13:00", "master_id": "lena"})
    assert r.status_code == 200
    assert client.post("/api/blocks", json={"start": "2026-11-12T13:00", "end": "2026-11-12T12:00"}).status_code == 400
    assert "BEGIN:VCALENDAR" in client.get("/kalender.ics").text


def test_demo_data(service):
    created = fill(service)
    assert created > 40
    assert fill(service) == 0  # nicht doppelt
    stats = TestClient(create_app(service)).get("/api/stats").json()
    assert stats["appointments"] > 0 and stats["revenue"] > 0 and stats["rating"]
    assert len(stats["series"]) == 14
