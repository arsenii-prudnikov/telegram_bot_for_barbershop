"""Bot zusammenbauen und starten."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from ..booking import BookingService
from ..config import Settings
from ..i18n import t
from . import admin, handlers, ui

log = logging.getLogger(__name__)


def build_dispatcher(service: BookingService, settings: Settings) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp["service"] = service
    dp["admin_ids"] = settings.admin_ids
    dp["review_url"] = settings.review_url
    dp.include_router(admin.router.build())
    dp.include_router(handlers.router.build())
    return dp


async def send_reminders(bot: Bot, service: BookingService) -> int:
    """Erinnerungen und Bewertungsanfragen verschicken. Gibt die Anzahl gesendeter Nachrichten zurück."""
    sent = 0
    for reminder in service.due_reminders():
        app = reminder.appointment
        customer = service.db.get_customer(app.customer_id)
        if customer and customer.tg_id:
            lang, salon = customer.lang, service.salon
            text_summary = ui.app_summary(lang, salon, app)
            try:
                if reminder.kind == "24h":
                    await bot.send_message(customer.tg_id, t(lang, "reminder_24", summary=text_summary,
                                                             address=salon.address))
                elif reminder.kind == "2h":
                    await bot.send_message(customer.tg_id, t(lang, "reminder_2", summary=text_summary))
                else:
                    await bot.send_message(customer.tg_id, t(lang, "review_ask", salon=salon.name),
                                           reply_markup=ui.rating_menu(app.id))
                sent += 1
            except Exception as exc:  # Kunde hat den Bot blockiert o. Ä.
                log.warning("Erinnerung %s für Termin %s fehlgeschlagen: %s", reminder.kind, app.id, exc)
        service.mark_sent(reminder)
    return sent


async def reminder_loop(bot: Bot, service: BookingService, interval: int = 60) -> None:
    while True:
        try:
            await send_reminders(bot, service)
        except Exception:
            log.exception("Fehler im Erinnerungs-Job")
        await asyncio.sleep(interval)


async def run_bot(service: BookingService, settings: Settings) -> None:
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN fehlt. Token bei @BotFather erstellen und in .env eintragen.")
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands([
        BotCommand(command="start", description="Termin buchen / Menü"),
        BotCommand(command="id", description="Eigene Telegram-ID anzeigen"),
    ])
    dp = build_dispatcher(service, settings)
    task = asyncio.create_task(reminder_loop(bot, service))
    log.info("Bot läuft für %s", service.salon.name)
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        await bot.session.close()
