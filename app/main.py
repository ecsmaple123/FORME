import mimetypes
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

import anyio.to_thread
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, func, select

from .config import get_settings
from .db import get_engine
from .models import Item
from .routes import (add, auth as auth_routes, categories, home, items, outfits,
                     settings as settings_routes, stylist)
from .services import auth
from .services.library import cleanup_staging

APP_DIR = Path(__file__).parent
THREADS = 8  # sync routes run in this pool; small to keep 32-bit address space low
mimetypes.add_type("image/webp", ".webp")  # Python 3.9's table lacks it (served as text/plain)


class UploadLimit:
    """Reject request bodies over the upload cap before they're parsed (pure ASGI)."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST":
            length = dict(scope["headers"]).get(b"content-length", b"0")
            if length.isdigit() and int(length) > self.max_bytes:
                resp = JSONResponse({"detail": "Upload too large"}, status_code=413)
                return await resp(scope, receive, send)
        return await self.app(scope, receive, send)


class LoginRequired:
    """Outside the home network every request needs the password (see services/auth.py), except
    the login page and the static files it uses. Sets request.state.home for the templates.

    Visitors from outside are guests: they can look at everything and make outfits (Studio, the
    stylist), but not change the closet, the categories, the settings or the stylist's memory."""

    OPEN = ("/login", "/static/", "/healthz")
    GUEST_POST = re.compile(r"^/(login|logout|outfits|outfits/\d+/delete|stylist"
                            r"|suggestions/\d+/save)$")
    GUEST_NO_GET = re.compile(r"^/(add(/.*)?|items/\d+/(edit|delete)"
                              r"|items/\d+/photos/\d+/(touchup|delete))$")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        home = auth.is_home(request.client.host if request.client else "", request.headers)
        scope.setdefault("state", {})["home"] = home
        if not (home or scope["path"].startswith(self.OPEN)
                or auth.signed_in(request.cookies.get(auth.COOKIE))):
            target = "/login"
            if request.method in ("GET", "HEAD") and scope["path"] != "/":
                target += "?" + urlencode({"next": request.url.path + (
                    "?" + request.url.query if request.url.query else "")})
            if request.headers.get("HX-Request"):  # htmx follows this header, not a redirect
                resp = Response(status_code=401, headers={"HX-Redirect": target})
            else:
                resp = RedirectResponse(target, status_code=303)
            return await resp(scope, receive, self._tagged(send))
        if not home and not self.guest_may(request.method, scope["path"]):
            from .templating import templates
            if request.headers.get("HX-Request"):
                resp = Response("View only from outside your home network.", status_code=403)
            else:
                resp = templates.TemplateResponse(request, "view_only.html", {}, status_code=403)
            return await resp(scope, receive, self._tagged(send))
        return await self.app(scope, receive, self._tagged(send))

    @classmethod
    def guest_may(cls, method: str, path: str) -> bool:
        if method in ("GET", "HEAD"):
            return not cls.GUEST_NO_GET.match(path)
        return method == "POST" and bool(cls.GUEST_POST.match(path))

    @staticmethod
    def _tagged(send):
        async def wrapped(message):
            if message["type"] == "http.response.start":  # keep the site out of search engines
                message.setdefault("headers", []).append((b"x-robots-tag", b"noindex, nofollow"))
            await send(message)
        return wrapped


@asynccontextmanager
async def lifespan(_app: FastAPI):
    anyio.to_thread.current_default_thread_limiter().total_tokens = THREADS
    await anyio.to_thread.run_sync(cleanup_staging)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    settings.ensure_dirs()
    app = FastAPI(title="FORME", lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    app.mount("/media", StaticFiles(directory=settings.images_dir), name="media")
    app.include_router(home.router)
    app.include_router(items.router)
    app.include_router(add.router)
    app.include_router(categories.router)
    app.include_router(settings_routes.router)
    app.include_router(outfits.router)
    app.include_router(stylist.router)
    app.include_router(auth_routes.router)

    @app.get("/healthz")
    def healthz(request: Request):
        """Open to all (wardrobe.sh checks it from the Pi); the item count only at home or on the Pi."""
        if not (request.state.home or auth.on_the_pi(request.client.host, request.headers)):
            return {"ok": True}
        with Session(get_engine()) as session:
            count = session.exec(select(func.count()).select_from(Item)).one()
        return {"ok": True, "items": count}

    # Per file the cap is max_upload_bytes (checked while saving); per request allow a few files.
    # Starlette spools uploads over 1 MB to disk, so this doesn't cost RAM.
    app.add_middleware(UploadLimit, max_bytes=settings.max_upload_bytes * 3 + 1024 * 1024)
    app.add_middleware(LoginRequired)  # added last = runs first, before uploads are read
    return app


app = create_app()
