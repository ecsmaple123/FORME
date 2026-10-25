from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from ..db import get_session
from ..services import library, prefs, weather
from ..templating import templates

router = APIRouter()


def render_settings(request: Request, session: Session, *, find: str = "", places=None,
                    error: str = "", saved: bool = False, status_code: int = 200):
    return templates.TemplateResponse(request, "settings.html", {
        "p": prefs.get(), "THEMES": prefs.THEMES, "UNITS": prefs.UNITS, "find": find,
        "places": places, "error": error, "saved": saved,
        "categories": library.list_categories(session),
        "counts": library.category_counts(session),
    }, status_code=status_code)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, find: str = "", saved: str = "",
                  session: Session = Depends(get_session)):
    """`find` searches for a weather location; the results are listed on the page to pick from."""
    if find.strip():
        try:
            return render_settings(request, session, find=find, places=weather.search_places(find))
        except weather.WeatherError as exc:
            return render_settings(request, session, find=find, error=str(exc), status_code=422)
    return render_settings(request, session, saved=bool(saved))


@router.post("/settings")
def save_settings(request: Request, name: str = Form(""), theme: str = Form("system"),
                  units: str = Form("c"), session: Session = Depends(get_session)):
    try:
        prefs.save({"name": name, "theme": theme, "units": units})
    except prefs.PrefsError as exc:
        return render_settings(request, session, error=str(exc), status_code=422)
    return RedirectResponse("/settings?saved=1", status_code=303)


@router.post("/settings/location")
def save_location(request: Request, place: str = Form(""), latitude: str = Form(""),
                  longitude: str = Form(""), timezone: str = Form(""),
                  session: Session = Depends(get_session)):
    """Save a picked search result, or clear the location (empty `place`)."""
    try:
        prefs.save({"place": place, "latitude": latitude, "longitude": longitude,
                    "timezone": timezone})
    except prefs.PrefsError as exc:
        return render_settings(request, session, error=str(exc), status_code=422)
    return RedirectResponse("/settings?saved=1", status_code=303)
