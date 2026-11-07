"""Übersetzungen (Deutsch, Russisch, Ukrainisch, Englisch, Türkisch)."""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import yaml

from .salon import Salon

LOCALE_DIR = Path(__file__).parent / "locales"
LANGUAGES = ["de", "ru", "uk", "en", "tr"]
DEFAULT = "de"


@lru_cache
def _load(lang: str) -> dict:
    return yaml.safe_load((LOCALE_DIR / f"{lang}.yaml").read_text(encoding="utf-8"))


def detect(code: str | None) -> str:
    """Telegram liefert z. B. 'de', 'ru' oder 'en-US'."""
    short = (code or "").split("-")[0].lower()
    return short if short in LANGUAGES else DEFAULT


def t(lang: str, key: str, **kwargs) -> str:
    table = _load(lang if lang in LANGUAGES else DEFAULT)
    text = table.get(key, _load(DEFAULT).get(key, key))
    return text.format(**kwargs) if kwargs else text


def raw(lang: str, key: str):
    return _load(lang if lang in LANGUAGES else DEFAULT)[key]


def fmt_day(lang: str, day: date | datetime) -> str:
    return t(
        lang,
        "date_format",
        weekday=raw(lang, "weekdays")[day.weekday()],
        day=day.day,
        month=raw(lang, "months")[day.month - 1],
    )


def summary(lang: str, salon: Salon, service_id: str, master_id: str, start: datetime, end: datetime) -> str:
    service = salon.service(service_id)
    master = salon.master(master_id)
    return t(
        lang,
        "summary",
        emoji=service.emoji,
        service=service.name(lang),
        master=f"{master.emoji} {master.name}",
        day=fmt_day(lang, start),
        start=f"{start:%H:%M}",
        end=f"{end:%H:%M}",
        price=salon.format_price(service.price),
    )


def opening_hours(lang: str, salon: Salon) -> str:
    lines = []
    names = raw(lang, "weekdays")
    for day in range(7):
        ranges = salon.hours.get(day, ())
        value = ", ".join(str(r) for r in ranges) if ranges else t(lang, "closed")
        lines.append(f"{names[day]}: {value}")
    return "\n".join(lines)
