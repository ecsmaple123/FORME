from contextlib import asynccontextmanager
from pathlib import Path

import anyio.to_thread
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, func, select

from .config import get_settings
from .db import get_engine
from .models import Item
from .routes import add, categories, items
from .services.library import cleanup_staging

APP_DIR = Path(__file__).parent
THREADS = 8  # sync routes run in this pool; small to keep 32-bit address space low


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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    anyio.to_thread.current_default_thread_limiter().total_tokens = THREADS
    await anyio.to_thread.run_sync(cleanup_staging)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    settings.ensure_dirs()
    app = FastAPI(title="Wardrobe", lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    app.mount("/media", StaticFiles(directory=settings.images_dir), name="media")
    app.include_router(items.router)
    app.include_router(add.router)
    app.include_router(categories.router)

    @app.get("/healthz")
    def healthz():
        with Session(get_engine()) as session:
            count = session.exec(select(func.count()).select_from(Item)).one()
        return {"ok": True, "items": count}

    app.add_middleware(UploadLimit, max_bytes=settings.max_upload_bytes + 1024 * 1024)
    return app


app = create_app()
