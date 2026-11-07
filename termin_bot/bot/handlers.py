"""Telegram-Handler für Kunden."""

from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Bot, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message, ReplyKeyboardRemove

from ..booking import BookingError, BookingService, WaitlistOffer
from ..db import Customer
from ..i18n import detect, fmt_day, t
from ..ics import calendar, event
from . import ui
from .callbacks import App, Day, Days, Lang, Menu, Mst, Ok, Rate, Svc, Tm, Wait
from .registry import Registry

log = logging.getLogger(__name__)
router = Registry("kunden")


class Checkout(StatesGroup):
    phone = State()


def customer_for(service: BookingService, user) -> Customer:
    customer = service.db.get_customer_by_tg(user.id)
    if customer is None:
        customer = service.db.upsert_customer(user.id, user.full_name or user.first_name, detect(user.language_code))
    return customer


async def edit(call: CallbackQuery, text: str, markup) -> None:
    """Nachricht bearbeiten statt neue zu senden – so bleibt der Chat aufgeräumt."""
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except Exception:  # z. B. "message is not modified" oder zu alte Nachricht
        await call.message.answer(text, reply_markup=markup)
    await call.answer()


async def notify_admins(bot: Bot, admin_ids: set[int], text: str) -> None:
    for admin in admin_ids:
        try:
            await bot.send_message(admin, text)
        except Exception as exc:  # Inhaber hat den Bot evtl. noch nicht gestartet
            log.warning("Admin %s nicht erreichbar: %s", admin, exc)


async def send_waitlist_offers(bot: Bot, service: BookingService, offers: list[WaitlistOffer]) -> None:
    for offer in offers:
        customer = service.db.get_customer(offer.customer_id)
        if not customer or not customer.tg_id:
            continue
        lang = customer.lang
        text = t(lang, "waitlist_offer", day=fmt_day(lang, offer.day),
                 service=service.salon.service(offer.service_id).name(lang), time=f"{offer.first_free:%H:%M}")
        try:
            await bot.send_message(customer.tg_id, text,
                                   reply_markup=ui.waitlist_offer_menu(lang, offer.service_id, offer.day))
        except Exception as exc:
            log.warning("Wartelisten-Nachricht fehlgeschlagen: %s", exc)


# ---------- Start & Menü ----------
@router.message(CommandStart())
async def start(message: Message, service: BookingService, state: FSMContext) -> None:
    await state.clear()
    customer = customer_for(service, message.from_user)
    first = message.from_user.first_name or customer.name
    await message.answer("💈")  # einzelnes Emoji wird in Telegram animiert dargestellt
    await message.answer(t(customer.lang, "welcome", name=first, salon=service.salon.name))
    await message.answer(t(customer.lang, "menu_title"), reply_markup=ui.main_menu(customer.lang))


@router.callback_query(Menu.filter())
async def menu(call: CallbackQuery, callback_data: Menu, service: BookingService) -> None:
    customer = customer_for(service, call.from_user)
    lang, salon = customer.lang, service.salon
    action = callback_data.action
    if action == "book":
        await edit(call, ui.step(lang, 1, t(lang, "choose_service")), ui.service_menu(lang, salon))
    elif action == "my":
        text, markup = ui.my_appointments(lang, salon, service.upcoming(customer.id))
        await edit(call, text, markup)
    elif action == "services":
        await edit(call, ui.services_text(lang, salon), ui.contact_keyboard(lang, salon))
    elif action == "contact":
        await edit(call, ui.contact_text(lang, salon), ui.contact_keyboard(lang, salon))
    elif action == "lang":
        await edit(call, t(lang, "choose_language"), ui.language_menu())
    else:
        await edit(call, t(lang, "menu_title"), ui.main_menu(lang))


@router.callback_query(Lang.filter())
async def set_language(call: CallbackQuery, callback_data: Lang, service: BookingService) -> None:
    customer = customer_for(service, call.from_user)
    service.db.set_language(customer.id, callback_data.code)
    lang = callback_data.code
    await edit(call, f"{t(lang, 'language_set')}\n\n{t(lang, 'menu_title')}", ui.main_menu(lang))


# ---------- Buchung ----------
@router.callback_query(Svc.filter())
async def choose_service(call: CallbackQuery, callback_data: Svc, service: BookingService) -> None:
    lang = customer_for(service, call.from_user).lang
    masters = service.salon.masters_for(callback_data.sid)
    if len(masters) == 1:
        await show_days(call, service, lang, callback_data.sid, masters[0].id)
        return
    await edit(call, ui.step(lang, 2, t(lang, "choose_master")), ui.master_menu(lang, service.salon, callback_data.sid))


async def show_days(call: CallbackQuery, service: BookingService, lang: str, sid: str, mid: str,
                    page: int = 0, reschedule: int = 0) -> None:
    title = t(lang, "choose_new_day") if reschedule else ui.step(lang, 3, t(lang, "choose_day"))
    await edit(call, title, ui.day_menu(lang, service, sid, mid, page, reschedule))


@router.callback_query(Mst.filter())
async def choose_master(call: CallbackQuery, callback_data: Mst, service: BookingService) -> None:
    lang = customer_for(service, call.from_user).lang
    await show_days(call, service, lang, callback_data.sid, callback_data.mid)


@router.callback_query(Days.filter())
async def page_days(call: CallbackQuery, callback_data: Days, service: BookingService) -> None:
    lang = customer_for(service, call.from_user).lang
    await show_days(call, service, lang, callback_data.sid, callback_data.mid, callback_data.page, callback_data.r)


@router.callback_query(Day.filter())
async def choose_day(call: CallbackQuery, callback_data: Day, service: BookingService) -> None:
    from ..slots import free_slots

    lang = customer_for(service, call.from_user).lang
    day = ui.parse_day(callback_data.day)
    mid = None if callback_data.mid == "any" else callback_data.mid
    slots = free_slots(service.salon, service.db, callback_data.sid, day, service.now(), mid, callback_data.r or None)
    if not slots:
        await edit(call, f"📅 <b>{fmt_day(lang, day)}</b>\n{t(lang, 'no_slots_day')}",
                   ui.full_day_menu(lang, callback_data.sid, callback_data.mid, day, callback_data.r))
        return
    body = t(lang, "choose_time", day=fmt_day(lang, day))
    text = body if callback_data.r else ui.step(lang, 4, body)
    await edit(call, text, ui.time_menu(lang, slots, callback_data.sid, callback_data.mid, day, callback_data.r))


def _slot_for(service: BookingService, cb: Tm | Ok):
    from ..slots import free_slots

    day = ui.parse_day(cb.day)
    start = datetime.combine(day, datetime.strptime(cb.hm, "%H%M").time())
    mid = None if cb.mid == "any" else cb.mid
    slots = free_slots(service.salon, service.db, cb.sid, day, service.now(), mid, cb.r or None)
    return next((s for s in slots if s.start == start), None)


@router.callback_query(Tm.filter())
async def choose_time(call: CallbackQuery, callback_data: Tm, service: BookingService) -> None:
    lang = customer_for(service, call.from_user).lang
    slot = _slot_for(service, callback_data)
    if slot is None:
        await call.answer(t(lang, "slot_taken"), show_alert=True)
        return
    details = ui.summary(lang, service.salon, callback_data.sid, slot.master_id, slot.start, slot.end)
    text = f"{t(lang, 'confirm_title')}\n\n{details}"
    await edit(call, text, ui.confirm_menu(lang, callback_data))


@router.callback_query(Ok.filter())
async def confirm(call: CallbackQuery, callback_data: Ok, service: BookingService, state: FSMContext,
                  bot: Bot, admin_ids: set[int]) -> None:
    customer = customer_for(service, call.from_user)
    lang = customer.lang
    if callback_data.r:
        await do_reschedule(call, callback_data, service, bot, admin_ids)
        return
    if not customer.phone:
        await state.set_state(Checkout.phone)
        await state.update_data(booking=callback_data.pack())
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(t(lang, "ask_phone"), reply_markup=ui.phone_keyboard(lang))
        await call.answer()
        return
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    await finish_booking(call.message, customer, callback_data, service, bot, admin_ids)


@router.message(Checkout.phone)
async def receive_phone(message: Message, state: FSMContext, service: BookingService, bot: Bot,
                        admin_ids: set[int]) -> None:
    customer = customer_for(service, message.from_user)
    if message.contact and message.contact.user_id == message.from_user.id:
        service.db.set_phone(customer.id, message.contact.phone_number)
        customer = service.db.get_customer(customer.id)
    data = await state.get_data()
    await state.clear()
    await message.answer("👍", reply_markup=ReplyKeyboardRemove())
    if data.get("booking"):
        await finish_booking(message, customer, Ok.unpack(data["booking"]), service, bot, admin_ids)


async def finish_booking(message: Message, customer: Customer, cb: Ok, service: BookingService, bot: Bot,
                         admin_ids: set[int]) -> None:
    lang, salon = customer.lang, service.salon
    day = ui.parse_day(cb.day)
    start = datetime.combine(day, datetime.strptime(cb.hm, "%H%M").time())
    try:
        app = service.book(customer.id, cb.sid, start, None if cb.mid == "any" else cb.mid)
    except BookingError as err:
        await message.answer(t(lang, err.key), reply_markup=ui.day_menu(lang, service, cb.sid, cb.mid))
        return
    text = ui.app_summary(lang, salon, app)
    await message.answer("🎉")
    await message.answer(t(lang, "booked", summary=text, address=salon.address), reply_markup=ui.main_menu(lang))
    title = f"{salon.service(app.service_id).name(lang)} – {salon.name}"
    ics = calendar(salon, [event(salon, app, title, f"{salon.master(app.master_id).name} · {salon.phone}")])
    await message.answer_document(BufferedInputFile(ics, filename="termin.ics"), caption=t(lang, "add_to_calendar"))
    await notify_admins(bot, admin_ids, ui.owner_new_booking(salon, app, customer.name, customer.phone))


async def do_reschedule(call: CallbackQuery, cb: Ok, service: BookingService, bot: Bot, admin_ids: set[int]) -> None:
    customer = customer_for(service, call.from_user)
    lang = customer.lang
    start = datetime.combine(ui.parse_day(cb.day), datetime.strptime(cb.hm, "%H%M").time())
    try:
        app, offers = service.reschedule(cb.r, start, customer.id, None if cb.mid == "any" else cb.mid)
    except BookingError as err:
        await call.answer(t(lang, err.key, phone=service.salon.phone), show_alert=True)
        return
    await edit(call, t(lang, "rescheduled", summary=ui.app_summary(lang, service.salon, app)), ui.main_menu(lang))
    await notify_admins(bot, admin_ids, ui.owner_new_booking(service.salon, app, customer.name, customer.phone, True))
    await send_waitlist_offers(bot, service, offers)


@router.callback_query(Wait.filter())
async def join_waitlist(call: CallbackQuery, callback_data: Wait, service: BookingService) -> None:
    customer = customer_for(service, call.from_user)
    lang = customer.lang
    day = ui.parse_day(callback_data.day)
    added = service.join_waitlist(customer.id, callback_data.sid, day)
    text = t(lang, "waitlist_added", day=fmt_day(lang, day)) if added else t(lang, "waitlist_exists")
    await edit(call, text, ui.main_menu(lang))


# ---------- Meine Termine ----------
@router.callback_query(App.filter())
async def manage(call: CallbackQuery, callback_data: App, service: BookingService, bot: Bot,
                 admin_ids: set[int]) -> None:
    customer = customer_for(service, call.from_user)
    lang, salon = customer.lang, service.salon
    app = service.db.get_appointment(callback_data.aid)
    if app is None or app.customer_id != customer.id or app.status != "booked":
        await call.answer(t(lang, "not_found"), show_alert=True)
        return
    if not service.can_change(app):
        await call.answer(t(lang, "too_late", phone=salon.phone), show_alert=True)
        return
    if callback_data.action == "move":
        await show_days(call, service, lang, app.service_id, app.master_id, reschedule=app.id)
    elif callback_data.action == "cancel":
        await edit(call, t(lang, "confirm_cancel", summary=ui.app_summary(lang, salon, app)),
                   ui.cancel_confirm(lang, app.id))
    elif callback_data.action == "cancel_yes":
        cancelled, offers = service.cancel(app.id, customer.id)
        await edit(call, t(lang, "cancelled"), ui.main_menu(lang))
        note = f"❌ <b>Absage</b>\n\n{ui.app_summary('de', salon, cancelled)}\n\n🙋 {customer.name}"
        await notify_admins(bot, admin_ids, note)
        await send_waitlist_offers(bot, service, offers)


@router.callback_query(Rate.filter())
async def rate(call: CallbackQuery, callback_data: Rate, service: BookingService, bot: Bot,
               admin_ids: set[int], review_url: str) -> None:
    customer = customer_for(service, call.from_user)
    lang = customer.lang
    try:
        service.rate(callback_data.aid, customer.id, callback_data.stars)
    except BookingError:
        await call.answer(t(lang, "not_found"), show_alert=True)
        return
    text = t(lang, "review_thanks")
    if callback_data.stars >= 4 and review_url:
        text += "\n\n" + t(lang, "review_google", url=review_url)
    await edit(call, text, None)
    if callback_data.stars <= 3:
        # Schlechte Bewertungen landen direkt beim Inhaber – nicht öffentlich bei Google
        await notify_admins(bot, admin_ids, f"⚠️ <b>Bewertung {'⭐' * callback_data.stars}</b> von {customer.name}"
                            + (f" · 📱 {customer.phone}" if customer.phone else "") + "\nAm besten kurz anrufen.")


@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery) -> None:
    await call.answer()
