"""Kommandozeile.

    python -m termin_bot run     # Bot + Dashboard
    python -m termin_bot bot     # nur Telegram-Bot
    python -m termin_bot web     # nur Dashboard
    python -m termin_bot demo    # Dashboard mit Demo-Daten (ohne Telegram)
    python -m termin_bot check   # Salon-Konfiguration prüfen
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from .booking import BookingService
from .config import Settings
from .db import Database
from .salon import load_salon


def make_service(settings: Settings, database: str | None = None) -> BookingService:
    salon = load_salon(settings.salon_file)
    return BookingService(salon, Database(database or settings.database))


async def _serve_web(service: BookingService, settings: Settings) -> None:
    import uvicorn

    from .web.app import create_app

    config = uvicorn.Config(create_app(service, settings.dashboard_token), host=settings.web_host,
                            port=settings.web_port, log_level="warning")
    await uvicorn.Server(config).serve()


async def _run_all(service: BookingService, settings: Settings) -> None:
    from .bot.app import run_bot

    await asyncio.gather(run_bot(service, settings), _serve_web(service, settings))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="termin_bot", description="Telegram-Terminbuchung für Salons")
    parser.add_argument("command", choices=["run", "bot", "web", "demo", "check"], nargs="?", default="run")
    parser.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = Settings.from_env()
    if args.port:
        settings.web_port = args.port

    if args.command == "check":
        salon = load_salon(settings.salon_file)
        print(f"✓ {salon.name}: {len(salon.services)} Leistungen, {len(salon.masters)} Mitarbeiter")
        for m in salon.masters:
            names = ", ".join(salon.service(s).name("de") for s in m.services) or "alle Leistungen"
            print(f"  {m.emoji} {m.name}: {names}")
        return

    if args.command == "demo":
        from .demo import fill

        service = make_service(settings, ":memory:")
        print(f"✓ {fill(service)} Demo-Termine erzeugt – Dashboard: http://{settings.web_host}:{settings.web_port}")
        settings.dashboard_token = ""
        asyncio.run(_serve_web(service, settings))
        return

    service = make_service(settings)
    if args.command == "bot":
        from .bot.app import run_bot

        asyncio.run(run_bot(service, settings))
    elif args.command == "web":
        asyncio.run(_serve_web(service, settings))
    else:
        asyncio.run(_run_all(service, settings))


if __name__ == "__main__":
    main()
