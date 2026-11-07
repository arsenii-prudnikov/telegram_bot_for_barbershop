"""Salon-Konfiguration: Leistungen, Mitarbeiter, Öffnungszeiten.

Alles, was ein Salon anpassen muss, steht in einer YAML-Datei (siehe ``salon.example.yaml``).
So kann derselbe Bot ohne Programmierung für jeden Friseur, Barbershop oder Kosmetikstudio
eingesetzt werden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

WEEKDAYS = ["mo", "di", "mi", "do", "fr", "sa", "so"]


@dataclass(frozen=True)
class TimeRange:
    start: time
    end: time

    @classmethod
    def parse(cls, text: str) -> TimeRange:
        a, b = (part.strip() for part in text.split("-"))
        start, end = time.fromisoformat(a), time.fromisoformat(b)
        if end <= start:
            raise ValueError(f"Ungültiger Zeitraum: {text}")
        return cls(start, end)

    def __str__(self) -> str:
        return f"{self.start:%H:%M}–{self.end:%H:%M}"


@dataclass(frozen=True)
class Service:
    id: str
    names: dict[str, str]
    duration: int  # Minuten
    price: float
    emoji: str = "✂️"

    def name(self, lang: str) -> str:
        return self.names.get(lang) or self.names.get("de") or next(iter(self.names.values()))


@dataclass(frozen=True)
class Master:
    id: str
    name: str
    services: tuple[str, ...]  # IDs der Leistungen
    hours: dict[int, tuple[TimeRange, ...]] | None = None  # eigene Arbeitszeiten (optional)
    emoji: str = "👤"

    def offers(self, service_id: str) -> bool:
        return not self.services or service_id in self.services


@dataclass
class Salon:
    name: str
    address: str
    phone: str
    timezone: str
    hours: dict[int, tuple[TimeRange, ...]]  # Wochentag (0 = Montag) -> Zeiträume
    services: list[Service]
    masters: list[Master]
    closed_days: set[date] = field(default_factory=set)
    slot_step: int = 15
    buffer: int = 0
    min_lead_minutes: int = 120
    horizon_days: int = 21
    cancel_hours: int = 3
    currency: str = "€"
    maps_url: str = ""

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def service(self, service_id: str) -> Service:
        for s in self.services:
            if s.id == service_id:
                return s
        raise KeyError(service_id)

    def master(self, master_id: str) -> Master:
        for m in self.masters:
            if m.id == master_id:
                return m
        raise KeyError(master_id)

    def masters_for(self, service_id: str) -> list[Master]:
        return [m for m in self.masters if m.offers(service_id)]

    def working_ranges(self, master: Master, day: date) -> tuple[TimeRange, ...]:
        if day in self.closed_days:
            return ()
        salon = self.hours.get(day.weekday(), ())
        if master.hours is None:
            return salon
        own = master.hours.get(day.weekday(), ())
        # Mitarbeiter arbeitet nur innerhalb der Öffnungszeiten
        result = []
        for a in own:
            for b in salon:
                start, end = max(a.start, b.start), min(a.end, b.end)
                if start < end:
                    result.append(TimeRange(start, end))
        return tuple(result)

    def format_price(self, value: float) -> str:
        text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if text.endswith(",00"):
            text = text[:-3]
        return f"{text} {self.currency}"


def _parse_hours(raw: dict | None) -> dict[int, tuple[TimeRange, ...]]:
    hours: dict[int, tuple[TimeRange, ...]] = {}
    for key, value in (raw or {}).items():
        day = WEEKDAYS.index(str(key).lower()[:2])
        if not value or str(value).lower() in {"zu", "geschlossen", "closed"}:
            hours[day] = ()
            continue
        parts = value if isinstance(value, list) else str(value).split(",")
        hours[day] = tuple(TimeRange.parse(p) for p in parts)
    return hours


def load_salon(path: str | Path) -> Salon:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    services = [
        Service(
            id=s["id"],
            names=s["name"] if isinstance(s["name"], dict) else {"de": s["name"]},
            duration=int(s["dauer"]),
            price=float(s["preis"]),
            emoji=s.get("emoji", "✂️"),
        )
        for s in data["leistungen"]
    ]
    service_ids = {s.id for s in services}
    masters = []
    for m in data["team"]:
        offered = tuple(m.get("leistungen") or ())
        unknown = set(offered) - service_ids
        if unknown:
            raise ValueError(f"Unbekannte Leistung bei {m['name']}: {', '.join(sorted(unknown))}")
        masters.append(
            Master(
                id=m["id"],
                name=m["name"],
                services=offered,
                hours=_parse_hours(m["arbeitszeiten"]) if m.get("arbeitszeiten") else None,
                emoji=m.get("emoji", "👤"),
            )
        )
    s = data["salon"]
    return Salon(
        name=s["name"],
        address=s.get("adresse", ""),
        phone=s.get("telefon", ""),
        timezone=s.get("zeitzone", "Europe/Berlin"),
        maps_url=s.get("karte", ""),
        hours=_parse_hours(data["oeffnungszeiten"]),
        services=services,
        masters=masters,
        closed_days={date.fromisoformat(str(d)) for d in data.get("geschlossen", []) or []},
        slot_step=int(data.get("regeln", {}).get("raster_minuten", 15)),
        buffer=int(data.get("regeln", {}).get("puffer_minuten", 0)),
        min_lead_minutes=int(data.get("regeln", {}).get("vorlauf_minuten", 120)),
        horizon_days=int(data.get("regeln", {}).get("buchbar_tage", 21)),
        cancel_hours=int(data.get("regeln", {}).get("storno_stunden", 3)),
        currency=s.get("waehrung", "€"),
    )
