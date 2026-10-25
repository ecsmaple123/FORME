"""Weather for the home page, from Open-Meteo (free, no API key, no account).

Only two fixed hosts are called: geocoding-api.open-meteo.com (the Settings location search) and
api.open-meteo.com (the forecast). Forecasts are cached in memory for 30 minutes per place, and
failures for 5 minutes, so a slow or offline API never slows down every page load.
"""
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 5.0
CACHE_SECONDS = 30 * 60
FAILURE_CACHE_SECONDS = 5 * 60

# WMO weather code -> (label, icon). Icons are drawn in templates/_icons.html.
CODES = {
    0: ("Clear sky", "clear"), 1: ("Mainly clear", "partly"), 2: ("Partly cloudy", "partly"),
    3: ("Overcast", "cloudy"), 45: ("Fog", "fog"), 48: ("Freezing fog", "fog"),
    51: ("Light drizzle", "drizzle"), 53: ("Drizzle", "drizzle"), 55: ("Heavy drizzle", "drizzle"),
    56: ("Freezing drizzle", "drizzle"), 57: ("Freezing drizzle", "drizzle"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"), 80: ("Rain showers", "rain"), 81: ("Rain showers", "rain"),
    82: ("Heavy showers", "rain"), 85: ("Snow showers", "snow"), 86: ("Snow showers", "snow"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm, hail", "storm"),
    99: ("Thunderstorm, hail", "storm"),
}
NIGHT_ICONS = {"clear": "clear-night", "partly": "partly-night"}


class WeatherError(Exception):
    """Shown to the user (short)."""


@dataclass
class Place:
    label: str
    latitude: float
    longitude: float
    timezone: str


@dataclass
class Weather:
    temp: float
    feels_like: float
    code: int
    is_day: bool
    high: float
    low: float
    rain_chance: Optional[int]
    wind: float
    units: str  # "c" | "f"

    @property
    def label(self) -> str:
        return CODES.get(self.code, ("Unknown", "cloudy"))[0]

    @property
    def icon(self) -> str:
        icon = CODES.get(self.code, ("", "cloudy"))[1]
        return icon if self.is_day else NIGHT_ICONS.get(icon, icon)

    @property
    def wind_unit(self) -> str:
        return "mph" if self.units == "f" else "km/h"

    def celsius(self, value: float) -> float:
        return (value - 32) * 5 / 9 if self.units == "f" else value

    @property
    def hint(self) -> str:
        """A one-line "what to wear" hint (rules for now; the AI stylist can replace it later)."""
        feels = self.celsius(self.feels_like)
        if feels < 0:
            text = "Bundle up: heavy coat, scarf and gloves."
        elif feels < 8:
            text = "Coat weather. Layer a knit underneath."
        elif feels < 14:
            text = "A light jacket or a warm knit."
        elif feels < 20:
            text = "A sweater or an overshirt is enough."
        elif feels < 26:
            text = "T-shirt weather."
        else:
            text = "Hot: keep it light and breathable."
        if self.icon in ("rain", "storm", "drizzle") or (self.rain_chance or 0) >= 60:
            text += " Bring something for the rain."
        elif self.icon == "snow":
            text += " Wear boots that can take snow."
        return text


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False,
                        headers={"User-Agent": "FORME wardrobe (self-hosted)"})


def search_places(name: str) -> List[Place]:
    name = " ".join((name or "").split())[:80]
    if len(name) < 2:
        raise WeatherError("Type at least two letters of a town or city.")
    try:
        with _client() as client:
            resp = client.get(GEOCODE_URL, params={"name": name, "count": 6, "language": "en",
                                                   "format": "json"})
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        raise WeatherError("The location search isn't reachable right now. Try again later.")
    places = []
    for r in data.get("results") or []:
        try:
            parts = [r.get("name"), r.get("admin1"), r.get("country")]
            label = ", ".join(dict.fromkeys(p for p in parts if p))  # drop repeats like "Monaco, Monaco"
            places.append(Place(label=label, latitude=float(r["latitude"]),
                                longitude=float(r["longitude"]), timezone=r.get("timezone") or ""))
        except (KeyError, TypeError, ValueError):
            continue
    return places


_cache: Dict[Tuple, Tuple[float, object]] = {}
_lock = threading.Lock()


def current(latitude: str, longitude: str, units: str = "c") -> Weather:
    """Current conditions + today's range. Raises WeatherError (cached briefly) on failure."""
    key = (latitude, longitude, units)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
    if hit and hit[0] > now:
        if isinstance(hit[1], WeatherError):
            raise hit[1]
        return hit[1]
    try:
        weather, ttl = _fetch(latitude, longitude, units), CACHE_SECONDS
    except WeatherError as exc:
        weather, ttl = exc, FAILURE_CACHE_SECONDS
    with _lock:
        _cache[key] = (now + ttl, weather)
    if isinstance(weather, WeatherError):
        raise weather
    return weather


def _fetch(latitude: str, longitude: str, units: str) -> Weather:
    params = {
        "latitude": latitude, "longitude": longitude, "timezone": "auto", "forecast_days": 1,
        "current": "temperature_2m,apparent_temperature,weather_code,is_day,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    }
    if units == "f":
        params.update(temperature_unit="fahrenheit", wind_speed_unit="mph")
    try:
        with _client() as client:
            resp = client.get(FORECAST_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        cur, day = data["current"], data["daily"]
        rain = (day.get("precipitation_probability_max") or [None])[0]
        return Weather(
            temp=float(cur["temperature_2m"]), feels_like=float(cur["apparent_temperature"]),
            code=int(cur["weather_code"]), is_day=bool(cur["is_day"]),
            high=float(day["temperature_2m_max"][0]), low=float(day["temperature_2m_min"][0]),
            rain_chance=int(rain) if rain is not None else None,
            wind=float(cur["wind_speed_10m"]), units=units,
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        raise WeatherError("Weather is unavailable right now.")


def clear_cache() -> None:
    with _lock:
        _cache.clear()
