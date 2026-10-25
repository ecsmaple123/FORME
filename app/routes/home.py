from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, func, select

from ..db import get_session
from ..models import Item
from ..services import featured, prefs, weather
from ..templating import templates

router = APIRouter()


def _now():
    return datetime.now(prefs.get().tz)  # the weather location's time zone, else the Pi's


@router.get("/", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(get_session)):
    now = _now()
    p = prefs.get()
    return templates.TemplateResponse(request, "home.html", {
        "now": now, "greeting": featured.welcome(now), "name": p.name, "has_place": p.has_place,
        "count": session.exec(select(func.count()).select_from(Item)).one(),
        "picks": featured.pick(session, now.date()),
        "recent": featured.recent(session),
    })


@router.get("/weather", response_class=HTMLResponse)
def weather_card(request: Request):
    """Loaded by the home page after it renders, so a slow forecast never delays the page."""
    p = prefs.get()
    ctx = {"place": p.place, "has_place": p.has_place, "wx": None, "error": ""}
    if p.has_place:
        try:
            ctx["wx"] = weather.current(p.latitude, p.longitude, p.units)
        except weather.WeatherError as exc:
            ctx["error"] = str(exc)
    return templates.TemplateResponse(request, "_weather.html", ctx)


@router.get("/picks", response_class=HTMLResponse)
def picks(request: Request, shuffle: bool = False, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "_picks.html", {
        "picks": featured.pick(session, _now().date(), shuffle=shuffle),
    })
