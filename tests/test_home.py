"""Home page (greeting, weather, picks), settings (name, theme, units, location) and dark mode."""
import re
from datetime import date

import httpx
import pytest

from app.services import featured, prefs, weather

from .conftest import make_image

FORECAST = {
    "current": {"temperature_2m": 11.6, "apparent_temperature": 9.2, "weather_code": 61,
                "is_day": 1, "wind_speed_10m": 14.4},
    "daily": {"temperature_2m_max": [13.1], "temperature_2m_min": [4.4],
              "precipitation_probability_max": [70]},
}
PLACES = {"results": [
    {"name": "Toronto", "admin1": "Ontario", "country": "Canada", "latitude": 43.70643,
     "longitude": -79.39864, "timezone": "America/Toronto"},
    {"name": "Monaco", "admin1": "Monaco", "country": "Monaco", "latitude": 43.73,
     "longitude": 7.42, "timezone": "Europe/Monaco"},
]}


@pytest.fixture
def meteo(monkeypatch):
    """Fake Open-Meteo. Records requests; `meteo["fail"] = True` makes it return 503."""
    state = {"requests": [], "fail": False, "forecast": FORECAST}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        if state["fail"]:
            return httpx.Response(503)
        if request.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json=PLACES)
        return httpx.Response(200, json=state["forecast"])

    monkeypatch.setattr(weather, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    weather.clear_cache()
    yield state
    weather.clear_cache()


def _add_item(client, name="Coat"):
    r = client.post("/add/photo", files=[("photo", ("p.jpg", make_image(), "image/jpeg"))])
    token = re.search(r'name="image_token" value="([0-9a-f]{32})"', r.text).group(1)
    r = client.post("/items", data={"image_token": token, "photo_kind": "product", "name": name,
                                    "category_id": "4"}, follow_redirects=False)
    return int(r.headers["location"].rsplit("/", 1)[1])


def _set_place(client):
    return client.post("/settings/location", data={
        "place": "Toronto, Ontario, Canada", "latitude": "43.70643", "longitude": "-79.39864",
        "timezone": "America/Toronto"}, follow_redirects=False)


def test_empty_home_welcomes_and_asks_for_location(client):
    r = client.get("/")
    assert r.status_code == 200
    assert re.search(r"Good (morning|afternoon|evening)|Hello", r.text)
    assert "Add your first item" in r.text and "Set location" in r.text
    assert "Today's picks" not in r.text


def test_home_with_items_shows_picks_and_recent(client):
    ids = [_add_item(client, f"Item {n}") for n in range(6)]
    r = client.get("/")
    assert "6 pieces in your closet" in r.text
    assert "Today's picks" in r.text and "Recently added" in r.text
    picks = re.findall(r'class="pick">\s*<a href="/items/(\d+)"', r.text)
    assert len(picks) == featured.COUNT and set(map(int, picks)) <= set(ids)
    # the same picks all day; shuffle returns just the section
    again = re.findall(r'class="pick">\s*<a href="/items/(\d+)"', client.get("/").text)
    assert again == picks
    s = client.get("/picks?shuffle=1")
    assert s.text.lstrip().startswith('<div id="picks">') and "<html" not in s.text


def test_picks_prefer_cutouts():
    class Photo:
        def __init__(self, cut):
            self.cutout_shown = "x" if cut else None

    class Item:
        def __init__(self, n, cut):
            self.id, self.cover = n, Photo(cut)

    class FakeSession:
        def exec(self, _stmt):
            class R:
                def all(self_inner):
                    return [Item(n, n % 2 == 0) for n in range(8)]
            return R()

    picks = featured.pick(FakeSession(), date(2026, 10, 25))
    assert [i.id % 2 for i in picks.items] == [0, 0, 0, 0]
    assert [i.id for i in picks.items] == [i.id for i in featured.pick(FakeSession(), date(2026, 10, 25)).items]


def test_name_appears_in_greeting(client):
    client.post("/settings", data={"name": "  Forest  ", "theme": "system", "units": "c"})
    r = client.get("/")
    assert '<span class="name">Forest</span>' in r.text


def test_dark_mode_setting(client):
    assert 'data-theme="system"' in client.get("/").text
    r = client.post("/settings", data={"name": "", "theme": "dark", "units": "c"}, follow_redirects=False)
    assert r.status_code == 303
    for page in ("/", "/closet", "/settings", "/add"):
        assert 'data-theme="dark"' in client.get(page).text
    r = client.post("/settings", data={"theme": "neon", "units": "c"})
    assert r.status_code == 422 and "Pick a theme" in r.text


def test_location_search_and_save(client, meteo):
    r = client.get("/settings", params={"find": "toronto"})
    assert "Toronto, Ontario, Canada" in r.text
    assert "Monaco, Monaco" not in r.text and ">Monaco<" not in r.text  # repeated parts dropped
    assert 'value="43.70643"' in r.text
    assert meteo["requests"][0].url.params["name"] == "toronto"
    r = _set_place(client)
    assert r.status_code == 303
    p = prefs.get()
    assert p.place == "Toronto, Ontario, Canada" and p.latitude == "43.7064" and p.timezone == "America/Toronto"
    assert "Remove location" in client.get("/settings").text
    client.post("/settings/location", data={"place": ""})
    assert not prefs.get().has_place


def test_location_rejects_bad_coordinates(client):
    r = client.post("/settings/location", data={"place": "Nowhere", "latitude": "123",
                                                "longitude": "0", "timezone": "Mars/Base"})
    assert r.status_code == 422 and "out of range" in r.text
    r = client.post("/settings/location", data={"place": "X", "latitude": "nan", "longitude": "0"})
    assert r.status_code == 422
    r = client.post("/settings/location", data={"place": "Somewhere", "latitude": "10",
                                                "longitude": "20", "timezone": "Mars/Base"},
                    follow_redirects=False)
    assert r.status_code == 303 and prefs.get().timezone == ""  # unknown zone dropped


def test_search_too_short_and_unreachable(client, meteo):
    r = client.get("/settings", params={"find": "x"})
    assert r.status_code == 422 and "two letters" in r.text
    meteo["fail"] = True
    r = client.get("/settings", params={"find": "Paris"})
    assert r.status_code == 422 and "search isn&#39;t reachable" in r.text


def test_weather_card(client, meteo):
    _set_place(client)
    home = client.get("/")
    assert 'hx-get="/weather"' in home.text
    r = client.get("/weather")
    assert "12°" in r.text and "Light rain" in r.text and "Feels 9°" in r.text
    assert "13° / 4°" in r.text and "70%" in r.text and "14 km/h" in r.text
    assert "Bring something for the rain" in r.text and "light jacket" in r.text
    assert 'class="weather-card wx-rain"' in r.text and "<svg" in r.text
    client.get("/weather")
    assert len(meteo["requests"]) == 1  # cached


def test_weather_in_fahrenheit(client, meteo):
    _set_place(client)
    client.post("/settings", data={"theme": "system", "units": "f"})
    meteo["forecast"] = {**FORECAST, "current": {**FORECAST["current"], "temperature_2m": 52.9,
                                                 "apparent_temperature": 48.6, "is_day": 0,
                                                 "weather_code": 0}}
    r = client.get("/weather")
    params = meteo["requests"][-1].url.params
    assert params["temperature_unit"] == "fahrenheit" and params["wind_speed_unit"] == "mph"
    assert "53°" in r.text and "mph" in r.text and "wx-clear-night" in r.text
    assert "A light jacket or a warm knit" in r.text  # 48.6 °F is 9.2 °C


def test_weather_failure_is_graceful_and_cached(client, meteo):
    _set_place(client)
    meteo["fail"] = True
    r = client.get("/weather")
    assert r.status_code == 200 and "unavailable" in r.text
    client.get("/weather")
    assert len(meteo["requests"]) == 1  # failure cached briefly, no retry storm


def test_browse_is_now_closet(client):
    _add_item(client)
    r = client.get("/closet")
    assert 'id="filters"' in r.text and 'action="/closet"' in r.text and "<h1" in r.text
    r = client.get("/browse?q=coat&sort=old", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/closet?q=coat&sort=old"
    item_id = _add_item(client, "Second")
    r = client.post(f"/items/{item_id}/delete", follow_redirects=False)
    assert r.headers["location"] == "/closet?deleted=1"
