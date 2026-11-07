"""Ende-zu-Ende-Test des Telegram-Bots – ohne echtes Netzwerk.

Eine Fake-Session nimmt alle API-Aufrufe entgegen, sodass komplette Dialoge
(Start → Leistung → Mitarbeiter → Tag → Uhrzeit → Buchung) getestet werden können.
"""

import asyncio
from datetime import datetime

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, SendDocument, SendMessage
from aiogram.types import CallbackQuery, Chat, Contact, Message, Update, User

from termin_bot.bot import ui
from termin_bot.bot.app import build_dispatcher, send_reminders
from termin_bot.bot.callbacks import Adm, App, Day, Menu, Mst, Ok, Rate, Svc, Tm
from termin_bot.config import Settings

USER = User(id=4242, is_bot=False, first_name="Anna", language_code="de")
OWNER = User(id=1, is_bot=False, first_name="Chefin", language_code="de")


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self._id = 100

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        returning = method.__returning__
        if returning is bool:
            return True
        self._id += 1
        chat_id = getattr(method, "chat_id", USER.id) or USER.id
        return Message(message_id=self._id, date=datetime.now(), chat=Chat(id=chat_id, type="private"),
                       text=getattr(method, "text", None))

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def close(self):
        pass

    def texts(self, chat_id=None):
        return [c.text for c in self.calls if isinstance(c, SendMessage | type(None)) or hasattr(c, "text")
                if getattr(c, "text", None) and (chat_id is None or getattr(c, "chat_id", None) == chat_id)]


def settings():
    return Settings(bot_token="1:x", admin_ids={OWNER.id}, salon_file=None, database=None,
                    dashboard_token="", review_url="https://g.page/r/test", web_host="", web_port=0)


class Harness:
    def __init__(self, service):
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session, default=DefaultBotProperties(parse_mode="HTML"))
        self.dp = build_dispatcher(service, settings())
        self.update_id = 0
        self.msg_id = 1

    def feed(self, **payload):
        self.update_id += 1
        update = Update(update_id=self.update_id, **payload)
        asyncio.run(self.dp.feed_update(self.bot, update))

    def message(self, text=None, user=USER, contact=None):
        self.msg_id += 1
        self.feed(message=Message(message_id=self.msg_id, date=datetime.now(), chat=Chat(id=user.id, type="private"),
                                  from_user=user, text=text, contact=contact))

    def click(self, data, user=USER):
        packed = data.pack() if hasattr(data, "pack") else data
        msg = Message(message_id=self.msg_id, date=datetime.now(), chat=Chat(id=user.id, type="private"),
                      from_user=self.bot_user(), text="…")
        self.feed(callback_query=CallbackQuery(id=str(self.update_id), from_user=user, chat_instance="c",
                                               message=msg, data=packed))

    def bot_user(self):
        return User(id=42, is_bot=True, first_name="Bot")

    def last_text(self):
        return next(c.text for c in reversed(self.session.calls) if getattr(c, "text", None))


def test_full_booking_dialog(service, db, clock):
    h = Harness(service)
    h.message("/start")
    assert "Studio Nordlicht" in "".join(h.session.texts())
    customer = db.get_customer_by_tg(USER.id)
    assert customer and customer.lang == "de"

    h.click(Menu(action="book"))
    assert "Welche Leistung" in h.last_text()
    h.click(Svc(sid="damenschnitt"))
    assert "Bei wem" in h.last_text()
    h.click(Mst(sid="damenschnitt", mid="any"))
    assert "An welchem Tag" in h.last_text()
    h.click(Day(sid="damenschnitt", mid="any", day="20261110"))
    assert "wähle eine Uhrzeit" in h.last_text()
    h.click(Tm(sid="damenschnitt", mid="any", day="20261110", hm="1000"))
    assert "Bitte prüfe deinen Termin" in h.last_text()

    # Telefonnummer fehlt noch → wird abgefragt
    h.click(Ok(sid="damenschnitt", mid="any", day="20261110", hm="1000"))
    assert "Telefonnummer" in h.last_text()
    h.message(contact=Contact(phone_number="+4915112345678", first_name="Anna", user_id=USER.id))

    apps = service.upcoming(customer.id)
    assert len(apps) == 1 and apps[0].start == datetime(2026, 11, 10, 10, 0)
    assert db.get_customer(customer.id).phone == "+4915112345678"
    assert any(isinstance(c, SendDocument) for c in h.session.calls)  # .ics für den Kalender
    owner_msgs = [c.text for c in h.session.calls if isinstance(c, SendMessage) and c.chat_id == OWNER.id]
    assert owner_msgs and "Neue Buchung" in owner_msgs[0]


def test_taken_slot_shows_alert(service, db):
    h = Harness(service)
    h.message("/start")
    other = db.upsert_customer(7, "Konkurrenz")
    service.book(other.id, "herrenschnitt", datetime(2026, 11, 10, 10, 0))
    h.click(Tm(sid="herrenschnitt", mid="murat", day="20261110", hm="1000"))
    alert = [c for c in h.session.calls if isinstance(c, AnswerCallbackQuery) and c.show_alert]
    assert alert and "vergeben" in alert[-1].text


def test_cancel_and_reschedule(service, db, clock):
    h = Harness(service)
    h.message("/start")
    customer = db.get_customer_by_tg(USER.id)
    app = service.book(customer.id, "herrenschnitt", datetime(2026, 11, 10, 10, 0))
    h.click(Menu(action="my"))
    assert "Deine Termine" in h.last_text()

    h.click(Ok(sid="herrenschnitt", mid="murat", day="20261111", hm="1500", r=app.id))
    assert "verschoben" in h.last_text()
    assert db.get_appointment(app.id).start == datetime(2026, 11, 11, 15, 0)

    h.click(App(aid=app.id, action="cancel"))
    assert "wirklich absagen" in h.last_text()
    h.click(App(aid=app.id, action="cancel_yes"))
    assert db.get_appointment(app.id).status == "cancelled"


def test_language_switch_and_russian_flow(service, db):
    h = Harness(service)
    h.message("/start")
    h.click("l:ru")
    assert "Язык: русский" in h.last_text()
    h.click(Menu(action="book"))
    assert "Какая услуга" in h.last_text()


def test_reminders_and_review(service, db, clock):
    h = Harness(service)
    h.message("/start")
    customer = db.get_customer_by_tg(USER.id)
    app = service.book(customer.id, "herrenschnitt", datetime(2026, 11, 11, 15, 0))
    clock.value = datetime(2026, 11, 10, 15, 30)
    assert asyncio.run(send_reminders(h.bot, service)) == 1
    assert "Morgen ist dein Termin" in h.last_text()
    clock.value = datetime(2026, 11, 11, 18, 0)
    asyncio.run(send_reminders(h.bot, service))
    assert "Wie zufrieden" in h.last_text()

    h.click(Rate(aid=app.id, stars=2))
    owner_msgs = [c.text for c in h.session.calls if isinstance(c, SendMessage) and c.chat_id == OWNER.id]
    assert any("Bewertung ⭐⭐" in t for t in owner_msgs)


def test_admin_commands(service, db):
    h = Harness(service)
    h.message("/admin", user=USER)  # normale Kunden sehen nichts
    assert not h.session.calls
    h.message("/admin", user=OWNER)
    assert "Inhaberbereich" in h.last_text()
    h.message("/sperren 2026-11-10 12:00-14:00 murat Arzttermin", user=OWNER)
    assert "Gesperrt" in h.last_text()
    customer = db.upsert_customer(55, "Ben")
    service.book(customer.id, "herrenschnitt", datetime(2026, 11, 10, 10, 0))
    h.click("x:day:20261110", user=OWNER)
    assert "10:00" in h.last_text() and "Ben" in h.last_text()
    h.click(Adm(action="stats"), user=OWNER)
    assert "Statistik" in h.last_text()


def test_day_menu_marks_full_days(service, salon):
    markup = ui.day_menu("de", service, "herrenschnitt", "murat")
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert any(label.startswith("✅ Di, 10. November") for label in labels)
    assert not any("Mo," in label for label in labels)  # Ruhetag wird nicht angezeigt
