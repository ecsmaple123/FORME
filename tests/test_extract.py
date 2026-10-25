import re

import httpx
import pytest

from app.services import fetch
from app.services.extract import parse_product_html

from .conftest import FIXTURES, make_image


def parse(name, base="https://shop.example/products/x"):
    return parse_product_html((FIXTURES / name).read_bytes(), base)


def test_og_image_wins_and_jsonld_brand():
    found = parse("og_product.html", "https://www.example-store.com/p/123")
    assert found.image_source == "og"
    assert found.image_url == "https://cdn.example-store.com/img/merino-crew-navy.jpg?w=1200"
    assert found.title == "Merino crew-neck jumper"
    assert found.brand == "Arket"  # from JSON-LD, not og:site_name (that's the store)


def test_jsonld_graph_product_image():
    found = parse("jsonld_graph.html")
    assert found.image_source == "json-ld"
    assert found.image_url == "https://shop.example/media/trousers-front.jpg"
    assert found.title == "Wide-leg wool trousers"
    assert found.brand == "COS"


def test_largest_img_fallback_skips_logos_and_pixels():
    found = parse("img_only.html")
    assert found.image_source == "img"
    assert found.image_url == "https://shop.example/p/boots-1600.jpg"
    assert found.title == "Leather ankle boots"
    assert found.brand == "Dr. Martens"


def test_bot_wall_detected():
    found = parse("bot_wall.html")
    assert found.image_url is None and found.looks_blocked


@pytest.mark.parametrize("url", [
    "http://192.168.0.1/admin", "http://10.0.0.5/", "http://127.0.0.1:8484/",
    "http://[::1]/", "http://169.254.169.254/latest", "http://100.64.0.1/",
    "http://172.16.0.1/", "http://0.0.0.0/",
])
def test_ssrf_guard_blocks_private_addresses(url):
    with pytest.raises(fetch.UnsafeURL):
        fetch.check_url(url, resolver=lambda h, p: [h.strip("[]")])


def test_ssrf_guard_checks_resolved_address():
    with pytest.raises(fetch.UnsafeURL):  # a public-looking name that resolves to the LAN
        fetch.check_url("https://sneaky.example/", resolver=lambda h, p: ["192.168.0.129"])
    with pytest.raises(fetch.UnsafeURL):
        fetch.check_url("file:///etc/passwd")
    fetch.check_url("https://shop.example/", resolver=lambda h, p: ["93.184.215.14"])


def test_redirect_to_private_address_is_blocked(fake_web):
    fake_web["https://shop.example/go"] = httpx.Response(
        302, headers={"location": "http://192.168.0.1/"})
    with pytest.raises(fetch.UnsafeURL):
        fetch.fetch_page("https://shop.example/go")


def test_url_import_end_to_end(client, fake_web, settings):
    page = (FIXTURES / "jsonld_graph.html").read_bytes()
    fake_web["https://shop.example/trousers"] = httpx.Response(
        200, content=page, headers={"content-type": "text/html; charset=utf-8"})
    fake_web["https://shop.example/media/trousers-front.jpg"] = httpx.Response(
        200, content=make_image(garment=(50, 50, 50)), headers={"content-type": "image/jpeg"})

    r = client.post("/add/url", data={"url": "https://shop.example/trousers"})
    assert r.status_code == 200
    assert "https://shop.example/media/trousers-front.jpg" in r.text
    assert 'value="Wide-leg wool trousers"' in r.text and 'value="COS"' in r.text

    r = client.post("/add/image-url", data={
        "image_url": "https://shop.example/media/trousers-front.jpg",
        "source_url": "https://shop.example/trousers",
        "name": "Wide-leg wool trousers", "brand": "COS"})
    assert r.status_code == 200
    token = re.search(r'name="image_token" value="([0-9a-f]{32})"', r.text).group(1)
    assert (settings.images_dir / "orig" / f"{token}.jpg").is_file()  # stored locally
    assert 'value="https://shop.example/trousers"' in r.text


def test_blocked_store_shows_fallback(client, fake_web):
    fake_web["https://shop.example/blocked"] = httpx.Response(403, content=b"Forbidden")
    r = client.post("/add/url", data={"url": "https://shop.example/blocked"})
    assert r.status_code == 422
    assert "blocked the request (HTTP 403)" in r.text
    assert 'name="image_url"' in r.text and 'name="photo"' in r.text
    assert 'value="https://shop.example/blocked"' in r.text  # source URL kept


def test_bot_wall_page_shows_fallback(client, fake_web):
    fake_web["https://shop.example/wall"] = httpx.Response(
        200, content=(FIXTURES / "bot_wall.html").read_bytes(),
        headers={"content-type": "text/html"})
    r = client.post("/add/url", data={"url": "https://shop.example/wall"})
    assert r.status_code == 422 and "bot check" in r.text


def test_image_url_that_is_html(client, fake_web):
    fake_web["https://shop.example/notimage"] = httpx.Response(
        200, content=b"<html></html>", headers={"content-type": "text/html"})
    r = client.post("/add/image-url", data={"image_url": "https://shop.example/notimage"})
    assert r.status_code == 422 and "isn&#39;t an image" in r.text


def test_oversized_download_rejected(client, fake_web, monkeypatch):
    fake_web["https://shop.example/huge.jpg"] = httpx.Response(
        200, content=b"x" * 2048, headers={"content-type": "image/jpeg"})
    from app.services import library
    monkeypatch.setattr(library, "get_settings", lambda: _small_cap(library))
    r = client.post("/add/image-url", data={"image_url": "https://shop.example/huge.jpg"})
    assert r.status_code == 422 and "too large" in r.text


def _small_cap(library):
    from app.config import get_settings
    s = get_settings()
    return s.__class__(**{**s.__dict__, "max_upload_mb": 0})
