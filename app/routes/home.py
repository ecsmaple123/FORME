from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, func, select

from ..db import get_session
from ..models import Item, Suggestion
from ..services import featured, prefs, stylist, weather
from ..templating import templates
from .stylist import today_weather, view

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
        # With the stylist set up, the picks load after the page (the first ones of the day take
        # a few seconds); without it they're random and come with the page.
        "picks": None if stylist.available() else featured.pick(session, now.date()),
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


def render_ai_picks(request: Request, session: Session, s: Suggestion, error: str = ""):
    v = view(session, s)
    return templates.TemplateResponse(request, "_picks.html", {
        "picks": featured.Picks(items=v.items, reason=s.reason), "sug": v, "error": error,
    })


def _random_picks(request: Request, session: Session, shuffle: bool = False, error: str = ""):
    picks = featured.pick(session, _now().date(), shuffle=shuffle)
    if error:
        picks.reason = error + " Here are random picks instead."
    return templates.TemplateResponse(request, "_picks.html", {"picks": picks, "error": error})


@router.get("/picks", response_class=HTMLResponse)
def picks(request: Request, shuffle: bool = False, session: Session = Depends(get_session)):
    """Today's picks: the stylist's outfit of the day (made once, then kept), or random items."""
    if not stylist.available():
        return _random_picks(request, session, shuffle)
    try:
        return render_ai_picks(request, session, stylist.daily(session, _now().date(), today_weather()))
    except stylist.AIError as exc:
        return _random_picks(request, session, error=str(exc))


@router.post("/picks/again", response_class=HTMLResponse)
def picks_again(request: Request, session: Session = Depends(get_session)):
    """Ask the stylist for a different outfit of the day; on failure keep the current one."""
    day = _now().date()
    try:
        return render_ai_picks(request, session, stylist.daily(session, day, today_weather(), again=True))
    except (stylist.AIUnavailable, stylist.AIError) as exc:
        current = session.exec(select(Suggestion).where(
            Suggestion.source == "daily", Suggestion.day == day.isoformat(),
            Suggestion.replaced == False).order_by(Suggestion.id.desc())).first()  # noqa: E712
        if current is None:
            return _random_picks(request, session, error=str(exc))
        return render_ai_picks(request, session, current, error=str(exc))
