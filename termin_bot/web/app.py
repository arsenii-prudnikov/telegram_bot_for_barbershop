"""Web-Dashboard für den Salon: Tagesplan, Kennzahlen, Kalender-Abo."""

from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ..booking import BookingError, BookingService
from ..i18n import fmt_day
from ..ics import calendar, event

HERE = Path(__file__).parent


class BlockIn(BaseModel):
    start: datetime
    end: datetime
    master_id: str | None = None
    reason: str = ""


def create_app(service: BookingService, token: str = "") -> FastAPI:
    app = FastAPI(title="Termin-Bot Dashboard", docs_url="/api/docs")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    salon = service.salon

    def auth(request: Request, t: str | None = Query(default=None)) -> None:
        if not token:
            return  # lokal ohne Passwort
        given = t or request.cookies.get("token") or request.headers.get("x-token", "")
        if not secrets.compare_digest(given, token):
            raise HTTPException(status_code=401, detail="Zugang nur mit gültigem Token")

    def serialize(a) -> dict:
        s, m = salon.service(a.service_id), salon.master(a.master_id)
        customer = service.db.get_customer(a.customer_id)
        return {
            "id": a.id, "start": a.start.isoformat(), "end": a.end.isoformat(),
            "service": s.name("de"), "emoji": s.emoji, "master_id": m.id, "master": m.name,
            "customer": customer.name if customer else "?", "phone": customer.phone if customer else None,
            "price": a.price, "status": a.status,
        }

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "salon": salon.name}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, _: None = Depends(auth)):
        response = templates.TemplateResponse(request, "dashboard.html", {"salon": salon})
        if token and request.query_params.get("t"):
            response.set_cookie("token", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 90)
        return response

    @app.get("/api/day")
    def day_view(d: date | None = None, _: None = Depends(auth)) -> dict:
        day = d or service.now().date()
        ranges = {m.id: [[f"{r.start:%H:%M}", f"{r.end:%H:%M}"] for r in salon.working_ranges(m, day)]
                  for m in salon.masters}
        blocks = [
            {"start": b.start.isoformat(), "end": b.end.isoformat(), "master_id": b.master_id, "reason": b.reason}
            for b in service.db.blocks_between(datetime.combine(day, datetime.min.time()),
                                               datetime.combine(day + timedelta(days=1), datetime.min.time()))
        ]
        return {
            "date": day.isoformat(), "label": fmt_day("de", day),
            "masters": [{"id": m.id, "name": m.name, "emoji": m.emoji, "hours": ranges[m.id]} for m in salon.masters],
            "appointments": [serialize(a) for a in service.agenda(day)],
            "blocks": blocks,
        }

    @app.get("/api/stats")
    def stats(days: int = 30, _: None = Depends(auth)) -> dict:
        today = service.now().date()
        s = service.stats(today - timedelta(days=days - 1), today)
        week = service.stats(today, today + timedelta(days=6))
        series = []
        for offset in range(13, -1, -1):
            day = today - timedelta(days=offset)
            apps = [a for a in service.agenda(day) if a.status in ("booked", "done")]
            series.append({"date": day.isoformat(), "label": f"{day:%d.%m.}", "revenue": sum(a.price for a in apps),
                           "count": len(apps)})
        return {
            "period_days": days, "appointments": s.appointments, "revenue": s.revenue, "cancelled": s.cancelled,
            "no_shows": s.no_shows, "new_customers": s.new_customers, "rating": s.rating, "reviews": s.reviews,
            "utilization": s.utilization,
            "top_services": [{"name": salon.service(k).name("de"), "emoji": salon.service(k).emoji, "count": n}
                             for k, n in s.top_services],
            "team": [{"name": salon.master(k).name, "count": n} for k, n in s.per_master],
            "next7": {"appointments": week.appointments, "revenue": week.revenue, "utilization": week.utilization},
            "series": series,
        }

    @app.post("/api/appointments/{appointment_id}/cancel")
    def cancel(appointment_id: int, _: None = Depends(auth)) -> dict:
        try:
            service.cancel(appointment_id)
        except BookingError as err:
            raise HTTPException(404, err.key) from err
        return {"ok": True}

    @app.post("/api/appointments/{appointment_id}/noshow")
    def noshow(appointment_id: int, _: None = Depends(auth)) -> dict:
        if not service.db.get_appointment(appointment_id):
            raise HTTPException(404, "not_found")
        service.mark_no_show(appointment_id)
        return {"ok": True}

    @app.post("/api/blocks")
    def add_block(block: BlockIn, _: None = Depends(auth)) -> dict:
        try:
            block_id = service.block(block.start, block.end, block.master_id, block.reason)
        except BookingError as err:
            raise HTTPException(400, err.key) from err
        return {"id": block_id}

    @app.get("/kalender.ics")
    def feed(_: None = Depends(auth)) -> Response:
        """Kalender-Abo für das Handy des Inhabers (alle kommenden Termine)."""
        now = service.now()
        apps = service.db.appointments_between(now - timedelta(days=7), now + timedelta(days=90))
        events = []
        for a in apps:
            customer = service.db.get_customer(a.customer_id)
            title = f"{salon.service(a.service_id).name('de')} – {customer.name if customer else '?'}"
            events.append(event(salon, a, title, f"{salon.master(a.master_id).name}"
                                + (f" · {customer.phone}" if customer and customer.phone else "")))
        return Response(calendar(salon, events), media_type="text/calendar; charset=utf-8")

    return app
