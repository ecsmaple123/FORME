"""The AI stylist: the Stylist page, likes/dislikes on its suggestions, saving them as outfits, and
its settings. Today's picks on the home page are in routes/home.py."""
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from ..db import get_session
from ..models import Suggestion
from ..services import ai, outfits, prefs, stylist, weather
from ..templating import templates
from .outfits import new_source

router = APIRouter()


def suggestion_or_404(session: Session, suggestion_id: int) -> Suggestion:
    s = session.get(Suggestion, suggestion_id)
    if s is None:
        raise HTTPException(404, "Suggestion not found")
    return s


def view(session: Session, s: Suggestion) -> SimpleNamespace:
    """A suggestion with its items and a starting board (for _board.html and the Studio)."""
    items = stylist.items_of(session, s)
    by_id = {i.id: i for i in items}
    board = outfits.auto_board(items) if items else []
    links = [SimpleNamespace(item=by_id[b["item_id"]], x=b["x"], y=b["y"], w=b["w"]) for b in board]
    return SimpleNamespace(s=s, items=items, board=board, outfit=SimpleNamespace(links=links))


def today_weather():
    """Today's weather at the saved location, or None (no location, or the forecast failed)."""
    p = prefs.get()
    if not p.has_place:
        return None
    try:
        return weather.current(p.latitude, p.longitude, p.units)
    except weather.WeatherError:
        return None


def _page(request: Request, session: Session, *, error: str = "", asked: str = "",
          status_code: int = 200):
    return templates.TemplateResponse(request, "stylist.html", {
        "available": stylist.available(), "model": ai.model(), "error": error, "asked": asked,
        "suggestions": [view(session, s) for s in stylist.recent(session)],
        "counts": stylist.counts(session), "has_place": prefs.get().has_place,
    }, status_code=status_code)


@router.get("/stylist", response_class=HTMLResponse)
def stylist_page(request: Request, session: Session = Depends(get_session)):
    return _page(request, session)


@router.post("/stylist", response_class=HTMLResponse)
def ask(request: Request, occasion: str = Form(""), use_weather: str = Form(""),
        session: Session = Depends(get_session)):
    htmx = bool(request.headers.get("HX-Request"))
    try:
        found = stylist.suggest(session, occasion, today_weather() if use_weather else None)
    except (stylist.AIUnavailable, stylist.AIError) as exc:
        if htmx:  # htmx only swaps 2xx answers
            return templates.TemplateResponse(request, "_stylist_error.html", {"error": str(exc)})
        return _page(request, session, error=str(exc), asked=occasion, status_code=422)
    if htmx:
        return templates.TemplateResponse(request, "_suggestions.html", {
            "suggestions": [view(session, s) for s in found], "fresh": True})
    return RedirectResponse("/stylist", status_code=303)


@router.post("/suggestions/{suggestion_id}/verdict", response_class=HTMLResponse)
def verdict(request: Request, suggestion_id: int, verdict: str = Form(""), note: str = Form(""),
            where: str = Form("stylist"), session: Session = Depends(get_session)):
    """Like / dislike (with an optional note) / clear. Answers with the updated card or picks."""
    s = suggestion_or_404(session, suggestion_id)
    stylist.set_verdict(session, s, verdict, note)
    if not request.headers.get("HX-Request"):
        return RedirectResponse("/" if where == "picks" else "/stylist", status_code=303)
    if where == "picks":
        from .home import render_ai_picks  # home imports this module
        return render_ai_picks(request, session, s)
    if s.verdict == "dislike":  # the card goes away; room for a reason and an undo
        return templates.TemplateResponse(request, "_dismissed.html", {"s": s})
    return templates.TemplateResponse(request, "_suggestion.html", {"sug": view(session, s)})


@router.post("/suggestions/{suggestion_id}/save")
def save_as_outfit(request: Request, suggestion_id: int, session: Session = Depends(get_session)):
    s = suggestion_or_404(session, suggestion_id)
    v = view(session, s)
    if not v.items:
        return RedirectResponse("/stylist", status_code=303)
    placed = [outfits.Placed(b["item_id"], b["x"], b["y"], b["w"]) for b in v.board]
    outfit = outfits.save_outfit(session, None, s.title, s.reason, placed,
                                 source=new_source(request, "ai"))
    s.outfit_id = outfit.id
    session.add(s)
    session.commit()
    return RedirectResponse(f"/outfits/{outfit.id}?saved=1", status_code=303)


@router.post("/stylist/notes")
def add_note(request: Request, text: str = Form(""), session: Session = Depends(get_session)):
    saved = stylist.add_note(session, text) is not None
    if not request.headers.get("HX-Request"):
        return RedirectResponse("/stylist#notes", status_code=303)
    return templates.TemplateResponse(request, "_stylist_notes.html", {"saved": saved})


@router.post("/settings/stylist")
def save_settings(style: str = Form(""), stylist_photos: str = Form("off")):
    prefs.save({"style": style, "stylist_photos": stylist_photos})
    return RedirectResponse("/settings?saved=1#stylist", status_code=303)


@router.post("/stylist/forget")
def forget(session: Session = Depends(get_session)):
    stylist.forget(session)
    return RedirectResponse("/settings?forgot=1#stylist", status_code=303)
