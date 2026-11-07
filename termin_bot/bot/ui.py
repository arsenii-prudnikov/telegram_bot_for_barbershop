"""Texte und Tastaturen des Bots – ohne Netzwerkzugriff, daher gut testbar."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..booking import BookingService, Stats
from ..db import Appointment
from ..i18n import LANGUAGES, fmt_day, opening_hours, summary, t
from ..salon import Salon
from ..slots import Slot, free_slots
from .callbacks import Adm, App, Day, Days, Lang, Menu, Mst, Ok, Rate, Svc, Tm, Wait

DAYS_PER_PAGE = 10


def day_key(day: date) -> str:
    return day.strftime("%Y%m%d")


def parse_day(key: str) -> date:
    return datetime.strptime(key, "%Y%m%d").date()


def _button(text: str, cb) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb.pack() if hasattr(cb, "pack") else cb)


# ---------- Menü ----------
def main_menu(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_button(t(lang, "menu_book"), Menu(action="book")))
    kb.row(_button(t(lang, "menu_my"), Menu(action="my")))
    kb.row(_button(t(lang, "menu_services"), Menu(action="services")),
           _button(t(lang, "menu_contact"), Menu(action="contact")))
    kb.row(_button(t(lang, "menu_language"), Menu(action="lang")))
    return kb.as_markup()


def language_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code in LANGUAGES:
        kb.button(text=t(code, "lang_name"), callback_data=Lang(code=code))
    kb.adjust(2)
    return kb.as_markup()


def home_button(lang: str) -> InlineKeyboardButton:
    return _button(t(lang, "home"), Menu(action="home"))


def services_text(lang: str, salon: Salon) -> str:
    lines = [t(lang, "services_title"), ""]
    for s in salon.services:
        lines.append(t(lang, "service_line", emoji=s.emoji, name=s.name(lang), duration=s.duration,
                       price=salon.format_price(s.price)))
    return "\n".join(lines)


def contact_text(lang: str, salon: Salon) -> str:
    return t(lang, "contact", salon=salon.name, address=salon.address, phone=salon.phone,
             hours=opening_hours(lang, salon))


def contact_keyboard(lang: str, salon: Salon) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if salon.maps_url:
        kb.row(InlineKeyboardButton(text="🗺 Google Maps", url=salon.maps_url))
    kb.row(_button(t(lang, "menu_book"), Menu(action="book")), home_button(lang))
    return kb.as_markup()


# ---------- Buchung: Leistung → Mitarbeiter → Tag → Uhrzeit ----------
def step(lang: str, n: int, body: str) -> str:
    return f"<i>{t(lang, 'step', n=n)}</i>\n{body}"


def service_menu(lang: str, salon: Salon) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in salon.services:
        kb.row(_button(f"{s.emoji} {s.name(lang)} · {salon.format_price(s.price)}", Svc(sid=s.id)))
    kb.row(home_button(lang))
    return kb.as_markup()


def master_menu(lang: str, salon: Salon, service_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_button(t(lang, "any_master"), Mst(sid=service_id, mid="any")))
    masters = salon.masters_for(service_id)
    for m in masters:
        kb.button(text=f"{m.emoji} {m.name}", callback_data=Mst(sid=service_id, mid=m.id))
    kb.adjust(1, *([2] * ((len(masters) + 1) // 2)))
    kb.row(_button(t(lang, "back"), Menu(action="book")))
    return kb.as_markup()


def day_menu(lang: str, service: BookingService, service_id: str, master_id: str,
             page: int = 0, reschedule: int = 0) -> InlineKeyboardMarkup:
    salon, now = service.salon, service.now()
    mid = None if master_id == "any" else master_id
    days = []
    for offset in range(salon.horizon_days + 1):
        day = now.date() + timedelta(days=offset)
        if not any(salon.working_ranges(m, day) for m in ([salon.master(mid)] if mid else salon.masters)):
            continue  # Ruhetag
        days.append(day)
    chunk = days[page * DAYS_PER_PAGE:(page + 1) * DAYS_PER_PAGE]
    kb = InlineKeyboardBuilder()
    for day in chunk:
        count = len(free_slots(salon, service.db, service_id, day, now, mid, reschedule or None))
        label = f"{'✅' if count else '🔔'} {fmt_day(lang, day)}"
        kb.button(text=label, callback_data=Day(sid=service_id, mid=master_id, day=day_key(day), r=reschedule))
    kb.adjust(2)
    nav = []
    if page > 0:
        nav.append(_button("⬅️", Days(sid=service_id, mid=master_id, page=page - 1, r=reschedule)))
    if (page + 1) * DAYS_PER_PAGE < len(days):
        nav.append(_button("➡️", Days(sid=service_id, mid=master_id, page=page + 1, r=reschedule)))
    if nav:
        kb.row(*nav)
    back = Menu(action="my") if reschedule else (Svc(sid=service_id) if len(salon.masters_for(service_id)) > 1
                                                 else Menu(action="book"))
    kb.row(_button(t(lang, "back"), back), home_button(lang))
    return kb.as_markup()


def time_menu(lang: str, slots: list[Slot], service_id: str, master_id: str, day: date,
              reschedule: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in slots:
        kb.button(text=f"{s.start:%H:%M}",
                  callback_data=Tm(sid=service_id, mid=master_id, day=day_key(day), hm=f"{s.start:%H%M}", r=reschedule))
    kb.adjust(4)
    kb.row(_button(t(lang, "back"), Days(sid=service_id, mid=master_id, page=0, r=reschedule)), home_button(lang))
    return kb.as_markup()


def full_day_menu(lang: str, service_id: str, master_id: str, day: date, reschedule: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if not reschedule:
        kb.row(_button(t(lang, "join_waitlist"), Wait(sid=service_id, day=day_key(day))))
    kb.row(_button(t(lang, "back"), Days(sid=service_id, mid=master_id, page=0, r=reschedule)), home_button(lang))
    return kb.as_markup()


def confirm_menu(lang: str, cb: Tm) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_button(t(lang, "confirm_yes"), Ok(sid=cb.sid, mid=cb.mid, day=cb.day, hm=cb.hm, r=cb.r)))
    kb.row(_button(t(lang, "back"), Day(sid=cb.sid, mid=cb.mid, day=cb.day, r=cb.r)), home_button(lang))
    return kb.as_markup()


def phone_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "share_phone"), request_contact=True)],
                  [KeyboardButton(text=t(lang, "skip_phone"))]],
        resize_keyboard=True, one_time_keyboard=True,
    )


# ---------- Meine Termine ----------
def app_summary(lang: str, salon: Salon, app: Appointment) -> str:
    return summary(lang, salon, app.service_id, app.master_id, app.start, app.end)


def my_appointments(lang: str, salon: Salon, apps: list[Appointment]) -> tuple[str, InlineKeyboardMarkup]:
    kb = InlineKeyboardBuilder()
    if not apps:
        kb.row(_button(t(lang, "menu_book"), Menu(action="book")), home_button(lang))
        return t(lang, "my_none"), kb.as_markup()
    parts = [t(lang, "my_title")]
    for app in apps:
        parts.append(app_summary(lang, salon, app))
        label = f"{fmt_day(lang, app.start)} {app.start:%H:%M}"
        kb.row(_button(f"{t(lang, 'btn_reschedule')} · {label}", App(aid=app.id, action="move")),
               _button("❌", App(aid=app.id, action="cancel")))
    kb.row(home_button(lang))
    return "\n\n".join(parts), kb.as_markup()


def cancel_confirm(lang: str, app_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_button(t(lang, "yes_cancel"), App(aid=app_id, action="cancel_yes")),
           _button(t(lang, "no_keep"), Menu(action="my")))
    return kb.as_markup()


def rating_menu(app_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for stars in range(1, 6):
        kb.button(text="⭐" * stars, callback_data=Rate(aid=app_id, stars=stars))
    kb.adjust(1)
    return kb.as_markup()


def waitlist_offer_menu(lang: str, service_id: str, day: date) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_button(t(lang, "waitlist_book"), Day(sid=service_id, mid="any", day=day_key(day))))
    return kb.as_markup()


# ---------- Verwaltung (Inhaber, immer Deutsch) ----------
STATUS_ICON = {"booked": "🟢", "done": "✅", "no_show": "🚫", "cancelled": "❌"}


def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_button("📋 Heute", Adm(action="today")), _button("📆 Morgen", Adm(action="tomorrow")))
    kb.row(_button("🗓 Diese Woche", Adm(action="week")), _button("📊 Statistik", Adm(action="stats")))
    return kb.as_markup()


def admin_day(service: BookingService, day: date, names: dict[int, str]) -> tuple[str, InlineKeyboardMarkup]:
    salon = service.salon
    apps = service.agenda(day)
    kb = InlineKeyboardBuilder()
    lines = [f"📋 <b>{fmt_day('de', day)}</b> – {len(apps)} Termin(e)"]
    revenue = 0.0
    for app in apps:
        s, m = salon.service(app.service_id), salon.master(app.master_id)
        lines.append(f"{STATUS_ICON[app.status]} <b>{app.start:%H:%M}</b> {s.emoji} {s.name('de')} · {m.name} · "
                     f"{names.get(app.customer_id, '?')}")
        if app.status != "no_show":
            revenue += app.price
        if app.status == "booked":
            kb.row(_button(f"🚫 {app.start:%H:%M} nicht da", Adm(action="noshow", arg=str(app.id))),
                   _button(f"❌ {app.start:%H:%M} absagen", Adm(action="cancel", arg=str(app.id))))
    if not apps:
        lines.append("Keine Termine. ☕")
    else:
        lines.append(f"\n💶 Umsatz: <b>{salon.format_price(revenue)}</b>")
    kb.row(_button("⬅️", Adm(action="day", arg=day_key(day - timedelta(days=1)))),
           _button("🏠", Adm(action="menu")),
           _button("➡️", Adm(action="day", arg=day_key(day + timedelta(days=1)))))
    return "\n".join(lines), kb.as_markup()


def admin_week(service: BookingService, start: date) -> str:
    salon = service.salon
    lines = ["🗓 <b>Die nächsten 7 Tage</b>"]
    for offset in range(7):
        day = start + timedelta(days=offset)
        apps = [a for a in service.agenda(day) if a.status == "booked"]
        if not any(salon.working_ranges(m, day) for m in salon.masters):
            lines.append(f"▫️ {fmt_day('de', day)}: geschlossen")
            continue
        total = sum(a.price for a in apps)
        lines.append(f"{'🟢' if apps else '⚪'} {fmt_day('de', day)}: <b>{len(apps)}</b> Termine · "
                     f"{salon.format_price(total)}")
    return "\n".join(lines)


def admin_stats(salon: Salon, stats: Stats, label: str) -> str:
    rating = f"{stats.rating} ⭐ ({stats.reviews} Bewertungen)" if stats.rating else "noch keine"
    lines = [
        f"📊 <b>Statistik – {label}</b>",
        "",
        f"✂️ Termine: <b>{stats.appointments}</b>",
        f"💶 Umsatz: <b>{salon.format_price(stats.revenue)}</b>",
        f"📈 Auslastung: <b>{stats.utilization} %</b>",
        f"🆕 Neue Kunden: <b>{stats.new_customers}</b>",
        f"❌ Absagen: {stats.cancelled} · 🚫 Nicht erschienen: {stats.no_shows}",
        f"⭐ Bewertung: {rating}",
    ]
    if stats.top_services:
        lines += ["", "<b>Beliebteste Leistungen</b>"]
        lines += [f"{salon.service(sid).emoji} {salon.service(sid).name('de')}: {n}" for sid, n in stats.top_services]
    if stats.per_master:
        lines += ["", "<b>Team</b>"]
        lines += [f"{salon.master(mid).emoji} {salon.master(mid).name}: {n}" for mid, n in stats.per_master]
    return "\n".join(lines)


def owner_new_booking(salon: Salon, app: Appointment, name: str, phone: str | None, moved: bool = False) -> str:
    head = "🔄 <b>Termin verschoben</b>" if moved else "🆕 <b>Neue Buchung</b>"
    return f"{head}\n\n{app_summary('de', salon, app)}\n\n🙋 {name}" + (f" · 📱 {phone}" if phone else "")
