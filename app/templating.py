from pathlib import Path

from fastapi.templating import Jinja2Templates

from .models import MAX_PHOTOS, PHOTO_KINDS, SEASONS, Item
from .services import prefs
from .services.library import MAX_PER_REQUEST, SORTS

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def media_url(obj, kind: str = "thumb", plain: bool = False) -> str:
    """URL of a photo's file; an Item means its cover photo.

    Display and thumbnail use the cutout (background removed) when there is one and it's switched
    on, unless plain=True. "orig" is always the photo as uploaded.
    """
    photo = obj.cover if isinstance(obj, Item) else obj
    if photo is None:
        return "/static/no-photo.svg"
    cutout = None if plain or kind == "orig" else photo.cutout_shown
    if cutout:
        return f"/media/cutout/{cutout}.webp" if kind == "display" else f"/media/cutout/{cutout}.thumb.webp"
    ext = {"thumb": "webp", "display": "jpg", "orig": photo.image_ext}[kind]
    return f"/media/{kind}/{photo.image_file}.{ext}"


def staged_url(staged, kind: str = "display") -> str:
    ext = {"thumb": "webp", "display": "jpg"}[kind]
    return f"/media/{kind}/{staged.token}.{ext}"


templates.env.globals.update(
    media_url=media_url, staged_url=staged_url, SEASONS=SEASONS, SORTS=SORTS,
    PHOTO_KINDS=PHOTO_KINDS, MAX_PHOTOS=MAX_PHOTOS, MAX_PER_REQUEST=MAX_PER_REQUEST,
    prefs=prefs.get,
)
templates.env.filters["date"] = lambda d: d.strftime("%-d %b %Y") if d else ""
templates.env.filters["deg"] = lambda v: f"{round(v):d}°"
