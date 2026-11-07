"""Erzeugt Screenshots und ein Demo-GIF des Chat-Ablaufs für die README.

Die Texte und Buttons kommen direkt aus dem echten Bot-Code (termin_bot.bot.ui und den
Übersetzungen) – die Bilder zeigen also genau das, was Kunden in Telegram sehen.

    python scripts/render_demo.py            # benötigt: pip install playwright pillow
"""

from __future__ import annotations

import html
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from termin_bot.booking import BookingService  # noqa: E402
from termin_bot.bot import ui  # noqa: E402
from termin_bot.db import Database  # noqa: E402
from termin_bot.i18n import t  # noqa: E402
from termin_bot.salon import load_salon  # noqa: E402
from termin_bot.slots import free_slots  # noqa: E402

DOCS = ROOT / "docs"
NOW = datetime(2026, 11, 9, 18, 40)

CSS = """
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.38 -apple-system, "Segoe UI", Roboto, "Noto Color Emoji", sans-serif; background: #0e1621; }
.phone { width: 390px; height: 780px; display: flex; flex-direction: column; overflow: hidden;
  background: #b5c99a url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><circle cx="10" cy="10" r="2" fill="%23a3b88a"/><circle cx="50" cy="40" r="2.5" fill="%23a3b88a"/><circle cx="25" cy="65" r="1.8" fill="%23a3b88a"/></svg>'); }
.bar { background: #517da2; color: #fff; padding: 12px 14px; display: flex; gap: 10px; align-items: center; }
.ava { width: 38px; height: 38px; border-radius: 50%; background: linear-gradient(135deg, #8f75ff, #5a3be0); display: grid; place-items: center; font-size: 20px; }
.bar b { display: block; font-size: 16px; } .bar small { opacity: .8; }
.chat { flex: 1; padding: 10px 10px 14px; display: flex; flex-direction: column; justify-content: flex-end; gap: 6px; overflow: hidden; }
.msg { max-width: 86%; padding: 7px 10px 6px; border-radius: 14px; background: #fff; box-shadow: 0 1px 1px rgba(0,0,0,.12); white-space: pre-wrap; word-wrap: break-word; }
.msg.me { align-self: flex-end; background: #effdde; border-bottom-right-radius: 4px; }
.msg.bot { align-self: flex-start; border-bottom-left-radius: 4px; }
.msg.big { background: none; box-shadow: none; font-size: 64px; padding: 0 4px; line-height: 1.1; }
.msg .time { float: right; font-size: 11px; color: #8ea2b0; margin: 6px 0 -2px 8px; }
.msg.doc { display: flex; gap: 10px; align-items: center; }
.doc i { width: 42px; height: 42px; border-radius: 50%; background: #4fae4e; color: #fff; display: grid; place-items: center; font-style: normal; font-size: 20px; }
.kb { align-self: flex-start; width: 86%; display: grid; gap: 4px; margin-top: -2px; }
.kb .row { display: flex; gap: 4px; }
.kb button { flex: 1; border: 0; border-radius: 9px; padding: 9px 4px; font: 500 13.5px -apple-system, "Segoe UI", Roboto, "Noto Color Emoji", sans-serif; color: #fff; background: rgba(60, 90, 70, .55); backdrop-filter: blur(4px); }
.kb button.hl { outline: 3px solid #ffd166; }
.reply { background: #fff; padding: 8px; display: grid; gap: 6px; }
.reply button { border: 0; border-radius: 8px; padding: 10px; background: #e8eef3; font: 500 14px sans-serif; color: #2b5278; }
.input { background: #fff; padding: 12px 14px; color: #9aa5ad; border-top: 1px solid #e5e5e5; }
"""


def _clean(text: str) -> str:
    # Telegram-HTML (<b>, <i>, <code>) übernehmen, Rest escapen
    safe = html.escape(text)
    return re.sub(r"&lt;(/?)(b|i|code)&gt;", r"<\1\2>", safe)


class Chat:
    def __init__(self):
        self.items: list[str] = []

    def me(self, text: str) -> None:
        self.items.append(f'<div class="msg me">{_clean(text)}<span class="time">18:4{len(self.items) % 10} ✓✓</span></div>')

    def bot(self, text: str, markup=None, highlight: str | None = None) -> None:
        cls = "msg bot big" if len(text) <= 2 else "msg bot"
        time = "" if "big" in cls else f'<span class="time">18:4{len(self.items) % 10}</span>'
        self.items.append(f'<div class="{cls}">{_clean(text)}{time}</div>')
        if markup is not None and getattr(markup, "inline_keyboard", None):
            rows = []
            for row in markup.inline_keyboard:
                cells = "".join(
                    f'<button class="{"hl" if highlight and b.text == highlight else ""}">{html.escape(b.text)}</button>'
                    for b in row)
                rows.append(f'<div class="row">{cells}</div>')
            self.items.append(f'<div class="kb">{"".join(rows)}</div>')

    def doc(self, name: str, caption: str) -> None:
        self.items.append(f'<div class="msg bot doc"><i>📎</i><div><b>{name}</b><br><small>{_clean(caption)}</small></div></div>')

    def page(self, title: str, reply: list[str] | None = None, keep: int = 6) -> str:
        reply_html = ""
        if reply:
            reply_html = '<div class="reply">' + "".join(f"<button>{html.escape(r)}</button>" for r in reply) + "</div>"
        body = "".join(self.items[-keep:])
        return (f"<!doctype html><meta charset='utf-8'><style>{CSS}</style><div class='phone'>"
                f"<div class='bar'><div class='ava'>💈</div><div><b>{title}</b><small>Bot</small></div></div>"
                f"<div class='chat'>{body}</div>{reply_html}<div class='input'>Nachricht</div></div>")


def build_frames() -> list[tuple[str, str]]:
    salon = load_salon(ROOT / "salon.example.yaml")
    service = BookingService(salon, Database(":memory:"), clock=lambda: NOW)
    customer = service.db.upsert_customer(4242, "Anna", "de", "+49 151 23456789")
    lang = "de"
    frames: list[tuple[str, str]] = []
    chat = Chat()

    def snap(name: str, **kw):
        frames.append((name, chat.page(salon.name, **kw)))

    chat.me("/start")
    chat.bot("💈")
    chat.bot(t(lang, "welcome", name="Anna", salon=salon.name))
    chat.bot(t(lang, "menu_title"), ui.main_menu(lang), highlight=t(lang, "menu_book"))
    snap("01_start")

    chat = Chat()
    chat.bot(ui.step(lang, 1, t(lang, "choose_service")), ui.service_menu(lang, salon),
             highlight=f"💇‍♀️ {salon.service('damenschnitt').name(lang)} · 45 €")
    snap("02_leistung")

    chat = Chat()
    chat.bot(ui.step(lang, 2, t(lang, "choose_master")), ui.master_menu(lang, salon, "damenschnitt"),
             highlight="👩‍🎨 Lena")
    snap("03_mitarbeiter")

    chat = Chat()
    day_markup = ui.day_menu(lang, service, "damenschnitt", "lena")
    target = next(b.text for row in day_markup.inline_keyboard for b in row if "Mi, 11." in b.text)
    chat.bot(ui.step(lang, 3, t(lang, "choose_day")), day_markup, highlight=target)
    snap("04_tag")

    day = datetime(2026, 11, 11).date()
    slots = free_slots(salon, service.db, "damenschnitt", day, NOW, "lena")
    chat = Chat()
    chat.bot(ui.step(lang, 4, t(lang, "choose_time", day=ui.fmt_day(lang, day))),
             ui.time_menu(lang, slots[::2][:16], "damenschnitt", "lena", day), highlight="10:00")
    snap("05_uhrzeit")

    start = datetime(2026, 11, 11, 10, 0)
    chat = Chat()
    details = ui.summary(lang, salon, "damenschnitt", "lena", start, start.replace(hour=11))
    cb = ui.Tm(sid="damenschnitt", mid="lena", day="20261111", hm="1000")
    chat.bot(f"{t(lang, 'confirm_title')}\n\n{details}", ui.confirm_menu(lang, cb), highlight=t(lang, "confirm_yes"))
    snap("06_bestaetigen")

    app = service.book(customer.id, "damenschnitt", start, "lena")
    chat = Chat()
    chat.bot("🎉")
    chat.bot(t(lang, "booked", summary=ui.app_summary(lang, salon, app), address=salon.address))
    chat.doc("termin.ics", t(lang, "add_to_calendar"))
    snap("07_gebucht")

    chat = Chat()
    chat.bot(t(lang, "reminder_24", summary=ui.app_summary(lang, salon, app), address=salon.address))
    chat.bot(t(lang, "review_ask", salon=salon.name), ui.rating_menu(app.id), highlight="⭐⭐⭐⭐⭐")
    snap("08_erinnerung")

    chat = Chat()
    text, markup = ui.my_appointments(lang, salon, service.upcoming(customer.id))
    chat.bot(text, markup)
    snap("09_meine_termine")

    # Russisch – gleicher Ablauf, andere Sprache
    chat = Chat()
    chat.bot(t("ru", "welcome", name="Олена", salon=salon.name))
    chat.bot(ui.step("ru", 1, t("ru", "choose_service")), ui.service_menu("ru", salon))
    snap("10_russisch")

    # Inhaberansicht
    for i, (sid, mid, hour) in enumerate([("herrenschnitt", "murat", 9), ("bart", "murat", 10),
                                          ("farbe", "lena", 14), ("augenbrauen", "lena", 17)]):
        guest = service.db.upsert_customer(900 + i, ["Mehmet Y.", "Lukas B.", "Sophie M.", "Irina T."][i])
        service.book(guest.id, sid, datetime(2026, 11, 11, hour, 0), mid)
    names = {r["id"]: r["name"] for r in service.db.query("SELECT id, name FROM customers")}
    chat = Chat()
    text, markup = ui.admin_day(service, day, names)
    chat.bot(text, markup)
    snap("11_inhaber")
    return frames


def main() -> None:
    from PIL import Image
    from playwright.sync_api import sync_playwright

    DOCS.mkdir(exist_ok=True)
    frames = build_frames()
    shots = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 780}, device_scale_factor=2)
        for name, markup in frames:
            page.set_content(markup)
            page.wait_for_timeout(150)
            path = DOCS / f"chat_{name}.png"
            page.screenshot(path=str(path))
            shots.append(path)
        browser.close()

    flow = [s for s in shots if not s.name.startswith(("chat_10", "chat_11"))]
    images = [Image.open(s).convert("RGB").resize((390, 780), Image.LANCZOS) for s in flow]
    images[0].save(DOCS / "demo.gif", save_all=True, append_images=images[1:], duration=1700, loop=0, optimize=True)

    # Übersicht: drei Screens nebeneinander für die README
    for out, names in {"booking.png": ["02_leistung", "04_tag", "07_gebucht"],
                       "extras.png": ["08_erinnerung", "10_russisch", "11_inhaber"]}.items():
        picks = [Image.open(DOCS / f"chat_{n}.png") for n in names]
        w, h = picks[0].size
        sheet = Image.new("RGB", (w * 3 + 80, h + 40), "#f6f4fb")
        for i, img in enumerate(picks):
            sheet.paste(img, (20 + i * (w + 20), 20))
        sheet.save(DOCS / out, optimize=True)
    print(f"{len(shots)} Screens, demo.gif, booking.png und extras.png in {DOCS}")


if __name__ == "__main__":
    main()
