"""Verwaltung für Inhaber direkt in Telegram (/admin, /sperren, /id)."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta

from aiogram import Bot
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from ..booking import BookingError, BookingService
from ..i18n import t
from . import ui
from .callbacks import Adm
from .handlers import edit, send_waitlist_offers
from .registry import Registry

router = Registry("inhaber")

BLOCK_HELP = (
    "⛔ <b>Zeit sperren</b>\n"
    "<code>/sperren 2026-12-02 12:00-14:00 lena Arzttermin</code>\n"
    "<code>/sperren 2026-12-20 ganztags Betriebsfeier</code>\n\n"
    "Mitarbeiter-ID weglassen = ganzer Salon."
)


def _names(service: BookingService) -> dict[int, str]:
    return {r["id"]: r["name"] for r in service.db.query("SELECT id, name FROM customers")}


def is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


@router.message(Command("id"))
async def my_id(message: Message) -> None:
    await message.answer(f"Deine Telegram-ID: <code>{message.from_user.id}</code>\n"
                         "Trage sie in ADMIN_IDS ein, um den Inhaberbereich freizuschalten.")


@router.message(Command("admin"))
async def admin(message: Message, admin_ids: set[int]) -> None:
    if not is_admin(message.from_user.id, admin_ids):
        return
    await message.answer("👑 <b>Inhaberbereich</b>\n\n" + BLOCK_HELP, reply_markup=ui.admin_menu())


@router.message(Command("sperren"))
async def block(message: Message, command: CommandObject, service: BookingService, admin_ids: set[int]) -> None:
    if not is_admin(message.from_user.id, admin_ids):
        return
    m = re.match(r"(\d{4}-\d{2}-\d{2})\s+(ganztags|\d{1,2}:\d{2}-\d{1,2}:\d{2})\s*(\S+)?\s*(.*)", command.args or "")
    if not m:
        await message.answer(BLOCK_HELP)
        return
    day = datetime.fromisoformat(m.group(1)).date()
    if m.group(2) == "ganztags":
        start, end = datetime.combine(day, time(0)), datetime.combine(day + timedelta(days=1), time(0))
    else:
        a, b = m.group(2).split("-")
        start = datetime.combine(day, time.fromisoformat(a.zfill(5)))
        end = datetime.combine(day, time.fromisoformat(b.zfill(5)))
    master_id, reason = m.group(3), m.group(4)
    if master_id and master_id not in {x.id for x in service.salon.masters}:
        reason, master_id = f"{master_id} {reason}".strip(), None
    try:
        service.block(start, end, master_id, reason)
    except BookingError:
        await message.answer("Ungültiger Zeitraum.\n\n" + BLOCK_HELP)
        return
    who = service.salon.master(master_id).name if master_id else "ganzer Salon"
    clashes = [a for a in service.agenda(day) if a.status == "booked" and a.start < end and a.end > start
               and (master_id is None or a.master_id == master_id)]
    text = f"⛔ Gesperrt: {ui.fmt_day('de', day)}, {start:%H:%M}–{end:%H:%M} ({who})"
    if clashes:
        text += f"\n⚠️ Achtung: {len(clashes)} gebuchte(r) Termin(e) in diesem Zeitraum – bitte im Tagesplan prüfen."
    await message.answer(text)


@router.callback_query(Adm.filter())
async def admin_actions(call: CallbackQuery, callback_data: Adm, service: BookingService, bot: Bot,
                        admin_ids: set[int]) -> None:
    if not is_admin(call.from_user.id, admin_ids):
        await call.answer()
        return
    today = service.now().date()
    action = callback_data.action
    if action in {"today", "tomorrow", "day"}:
        day = {"today": today, "tomorrow": today + timedelta(days=1)}.get(action) or ui.parse_day(callback_data.arg)
        text, markup = ui.admin_day(service, day, _names(service))
        await edit(call, text, markup)
    elif action == "week":
        await edit(call, ui.admin_week(service, today), ui.admin_menu())
    elif action == "stats":
        stats = service.stats(today - timedelta(days=29), today)
        await edit(call, ui.admin_stats(service.salon, stats, "letzte 30 Tage"), ui.admin_menu())
    elif action == "noshow":
        app = service.db.get_appointment(int(callback_data.arg))
        service.mark_no_show(app.id)
        text, markup = ui.admin_day(service, app.start.date(), _names(service))
        await edit(call, text, markup)
    elif action == "cancel":
        app, offers = service.cancel(int(callback_data.arg))
        customer = service.db.get_customer(app.customer_id)
        if customer and customer.tg_id:
            lang = customer.lang
            await bot.send_message(
                customer.tg_id,
                f"😔 {t(lang, 'cancelled')}\n\n{ui.app_summary(lang, service.salon, app)}\n\n📞 {service.salon.phone}",
                reply_markup=ui.main_menu(lang),
            )
        await send_waitlist_offers(bot, service, offers)
        text, markup = ui.admin_day(service, app.start.date(), _names(service))
        await edit(call, text, markup)
    else:
        await edit(call, "👑 <b>Inhaberbereich</b>", ui.admin_menu())
