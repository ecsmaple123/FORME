"""User preferences (the Settings page): name, theme, weather location and units, and the
stylist's "My style" text and photo switch.

Stored as strings in the `setting` table. Every page needs them (theme, greeting), so they're
cached in memory and the cache is dropped when they're saved. The cache is tied to the engine,
so tests with a fresh database never see stale values.
"""
import math
from dataclasses import dataclass, fields
from typing import Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlmodel import Session, select

from ..db import get_engine
from ..models import Setting

THEMES = {"system": "System", "light": "Light", "dark": "Dark"}
UNITS = {"c": "°C", "f": "°F"}


@dataclass
class Prefs:
    name: str = ""
    theme: str = "system"
    units: str = "c"
    place: str = ""       # label shown to the user, e.g. "Toronto, Ontario, Canada"
    latitude: str = ""
    longitude: str = ""
    timezone: str = ""    # IANA name of the place, used for the greeting and the date
    style: str = ""       # "My style", in the user's words, for the AI stylist
    stylist_photos: str = "on"  # "on": the stylist also sees the cutout photos of items

    @property
    def send_photos(self) -> bool:
        return self.stylist_photos != "off"

    @property
    def has_place(self) -> bool:
        return bool(self.place and self.latitude and self.longitude)

    @property
    def tz(self) -> Optional[ZoneInfo]:
        try:
            return ZoneInfo(self.timezone) if self.timezone else None
        except (ZoneInfoNotFoundError, ValueError):
            return None


_cache: Dict[str, object] = {}  # {"engine": the engine the values came from, "prefs": Prefs}


def get() -> Prefs:
    engine = get_engine()
    if _cache.get("engine") is not engine:  # first use, saved, or a new database (tests, restore)
        with Session(engine) as session:
            rows = {s.key: s.value for s in session.exec(select(Setting)).all()}
        known = {f.name for f in fields(Prefs)}
        _cache.update(engine=engine, prefs=Prefs(**{k: v for k, v in rows.items() if k in known}))
    return _cache["prefs"]


class PrefsError(ValueError):
    """Shown to the user."""


def _clean(values: Dict[str, str]) -> Dict[str, str]:
    out = {}
    if "name" in values:
        out["name"] = " ".join(values["name"].split())[:40]
    if "theme" in values:
        if values["theme"] not in THEMES:
            raise PrefsError("Pick a theme.")
        out["theme"] = values["theme"]
    if "units" in values:
        if values["units"] not in UNITS:
            raise PrefsError("Pick °C or °F.")
        out["units"] = values["units"]
    if "style" in values:
        lines = [" ".join(line.split()) for line in values["style"].splitlines()]
        out["style"] = "\n".join(line for line in lines if line)[:1000]
    if "stylist_photos" in values:
        out["stylist_photos"] = "on" if values["stylist_photos"] == "on" else "off"
    if "place" in values:
        if not values["place"]:  # clearing the location
            out.update(place="", latitude="", longitude="", timezone="")
        else:
            try:
                lat, lon = float(values["latitude"]), float(values["longitude"])
            except (KeyError, ValueError):
                raise PrefsError("That location is missing its coordinates.")
            if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                raise PrefsError("That location's coordinates are out of range.")
            tz = values.get("timezone", "")
            try:
                ZoneInfo(tz)
            except (ZoneInfoNotFoundError, ValueError):
                tz = ""
            out.update(place=" ".join(values["place"].split())[:120], latitude=f"{lat:.4f}",
                       longitude=f"{lon:.4f}", timezone=tz)
    return out


def save(values: Dict[str, str]) -> Prefs:
    """Validate and store some preferences; raises PrefsError with a message for the user."""
    cleaned = _clean(values)
    with Session(get_engine()) as session:
        for key, value in cleaned.items():
            row = session.get(Setting, key) or Setting(key=key)
            row.value = value
            session.add(row)
        session.commit()
    _cache.clear()
    return get()

