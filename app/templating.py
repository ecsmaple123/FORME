from pathlib import Path

from fastapi.templating import Jinja2Templates

from .models import SEASONS
from .services.library import SORTS

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def media_url(item, kind: str = "thumb") -> str:
    ext = {"thumb": "webp", "display": "jpg", "orig": item.image_ext}[kind]
    return f"/media/{kind}/{item.image_file}.{ext}"


def staged_url(staged, kind: str = "display") -> str:
    ext = {"thumb": "webp", "display": "jpg"}[kind]
    return f"/media/{kind}/{staged.token}.{ext}"


templates.env.globals.update(media_url=media_url, staged_url=staged_url, SEASONS=SEASONS,
                             SORTS=SORTS)
templates.env.filters["date"] = lambda d: d.strftime("%-d %b %Y") if d else ""
