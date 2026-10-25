from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..services import prefs, weather
from ..templating import templates

router = APIRouter()


def _page(request: Request, *, find: str = "", places=None, error: str = "", saved: bool = False,
          status_code: int = 200):
    return templates.TemplateResponse(request, "settings.html", {
        "p": prefs.get(), "THEMES": prefs.THEMES, "UNITS": prefs.UNITS, "find": find,
        "places": places, "error": error, "saved": saved,
    }, status_code=status_code)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, find: str = "", saved: str = ""):
    """`find` searches for a weather location; the results are listed on the page to pick from."""
    if find.strip():
        try:
            return _page(request, find=find, places=weather.search_places(find))
        except weather.WeatherError as exc:
            return _page(request, find=find, error=str(exc), status_code=422)
    return _page(request, saved=bool(saved))


@router.post("/settings")
def save_settings(request: Request, name: str = Form(""), theme: str = Form("system"),
                  units: str = Form("c")):
    try:
        prefs.save({"name": name, "theme": theme, "units": units})
    except prefs.PrefsError as exc:
        return _page(request, error=str(exc), status_code=422)
    return RedirectResponse("/settings?saved=1", status_code=303)


@router.post("/settings/location")
def save_location(request: Request, place: str = Form(""), latitude: str = Form(""),
                  longitude: str = Form(""), timezone: str = Form("")):
    """Save a picked search result, or clear the location (empty `place`)."""
    try:
        prefs.save({"place": place, "latitude": latitude, "longitude": longitude,
                    "timezone": timezone})
    except prefs.PrefsError as exc:
        return _page(request, error=str(exc), status_code=422)
    return RedirectResponse("/settings?saved=1", status_code=303)
