"""Kalenderdateien (iCalendar, RFC 5545) – funktionieren mit Google, Apple und Outlook."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from .db import Appointment
from .salon import Salon


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _utc(salon: Salon, local: datetime) -> str:
    return local.replace(tzinfo=salon.tz).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str) -> str:
    # Zeilen dürfen höchstens 75 Bytes lang sein
    out, current = [], b""
    for ch in line:
        enc = ch.encode()
        if len(current) + len(enc) > 73:
            out.append(current.decode())
            current = b" "
        current += enc
    out.append(current.decode())
    return "\r\n".join(out)


def event(salon: Salon, app: Appointment, title: str, description: str = "") -> list[str]:
    return [
        "BEGIN:VEVENT",
        f"UID:termin-{app.id}@termin-bot",
        f"DTSTAMP:{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
        f"DTSTART:{_utc(salon, app.start)}",
        f"DTEND:{_utc(salon, app.end)}",
        f"SUMMARY:{_escape(title)}",
        f"LOCATION:{_escape(salon.address)}",
        f"DESCRIPTION:{_escape(description)}",
        "STATUS:CONFIRMED",
        "BEGIN:VALARM",
        "TRIGGER:-PT2H",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_escape(title)}",
        "END:VALARM",
        "END:VEVENT",
    ]


def calendar(salon: Salon, events: Iterable[list[str]]) -> bytes:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Termin-Bot//DE", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_escape(salon.name)}"]
    for ev in events:
        lines += ev
    lines.append("END:VCALENDAR")
    return ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode()
