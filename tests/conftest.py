import io
import ipaddress
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageDraw

FIXTURES = Path(__file__).parent / "fixtures"
HOME_ADDRESS = "192.168.0.50"


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """A fresh, migrated database and image folder per test."""
    monkeypatch.setenv("WARDROBE_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("WARDROBE_BACKUPS", str(tmp_path / "backups"))
    monkeypatch.setenv("GEMINI_API_KEY", "")  # never the real key from .env: no test calls Gemini
    from app.config import get_settings
    from app.db import migrate, reset_engine

    from app.services import auth

    get_settings.cache_clear()
    reset_engine()
    migrate()
    auth._failures.clear()
    yield get_settings()
    reset_engine()
    get_settings.cache_clear()


@pytest.fixture
def client(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(), client=(HOME_ADDRESS, 50000)) as c:  # at home: no login
        yield c


def make_image(size=(1200, 1500), fmt="JPEG", garment=(29, 38, 69), background=(255, 255, 255),
               mode="RGB") -> bytes:
    """A product-shot-like image: a garment-colored block on a plain background."""
    im = Image.new(mode, size, background if mode == "RGB" else background + (0,))
    w, h = size
    ImageDraw.Draw(im).rectangle([w // 4, h // 5, w * 3 // 4, h * 4 // 5],
                                 fill=garment if mode == "RGB" else garment + (255,))
    buf = io.BytesIO()
    im.save(buf, fmt)
    return buf.getvalue()


def public_resolver(host, port):
    """Pretend every hostname is public; IP literals resolve to themselves."""
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        return ["93.184.215.14"]


@pytest.fixture
def fake_web(monkeypatch):
    """Route outbound HTTP to a dict of {url: httpx.Response}; no real network in tests."""
    from app.services import fetch

    routes = {}

    def handler(request: httpx.Request) -> httpx.Response:
        resp = routes.get(str(request.url))
        return resp if resp is not None else httpx.Response(404)

    monkeypatch.setattr(fetch, "_system_resolver", public_resolver)
    monkeypatch.setattr(fetch, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=False))
    return routes
