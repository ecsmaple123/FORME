"""Multiple photos per item, the bookmark endpoint, and the 0001 -> 0002 migration."""
import re
import sqlite3
from urllib.parse import unquote

import httpx
from sqlmodel import Session

from app.db import get_engine
from app.models import Item
from app.services.images import paths

from .conftest import make_image

NAVY, RED, GREEN = (29, 38, 69), (198, 42, 42), (60, 154, 75)


def _jpeg(color):
    return ("p.jpg", make_image(garment=color), "image/jpeg")


def _tokens(html):
    return re.findall(r'name="image_token" value="([0-9a-f]{32})"', html)


def _item(item_id):
    with Session(get_engine()) as s:
        item = s.get(Item, item_id)
        if item:
            _ = item.photos, item.colors, item.tags
        return item


def _create_with(client, colors, kinds=None):
    r = client.post("/add/photo", files=[("photo", _jpeg(c)) for c in colors],
                    data={"photo_kind": "real"})
    assert r.status_code == 200, r.text
    tokens = _tokens(r.text)
    assert len(tokens) == len(colors)
    r = client.post("/items", data={
        "image_token": tokens, "photo_kind": kinds or ["real"] * len(tokens),
        "name": "Shirt", "category_id": "1"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rsplit("/", 1)[1])


def test_create_with_several_photos_and_kinds(client):
    item_id = _create_with(client, [NAVY, RED], kinds=["product", "real"])
    item = _item(item_id)
    assert [(p.position, p.kind) for p in item.photos] == [(0, "product"), (1, "real")]
    assert item.cover.id == item.photos[0].id
    # colors come from the cover (navy), not the second photo
    from app.services.colors import nearest_color_name
    assert nearest_color_name(item.colors[0].hex) == "navy"
    r = client.get("/browse", headers={"HX-Request": "true"})
    assert 'class="count-badge"' in r.text


def test_add_photo_set_cover_change_kind_delete(client, settings):
    item_id = _create_with(client, [NAVY])
    r = client.post(f"/items/{item_id}/photos", files=[("photo", _jpeg(RED))],
                    data={"kind": "detail"}, follow_redirects=False)
    assert r.status_code == 303
    item = _item(item_id)
    first, second = item.photos
    assert second.kind == "detail" and second.position == 1

    r = client.get(f"/items/{item_id}?photo={second.id}")
    assert "Make cover" in r.text and "Delete photo" in r.text

    client.post(f"/items/{item_id}/photos/{second.id}/cover")
    item = _item(item_id)
    assert item.cover.id == second.id and [p.position for p in item.photos] == [0, 1]
    from app.services.colors import nearest_color_name
    assert nearest_color_name(item.colors[0].hex) == "red"  # recolored from the new cover

    client.post(f"/items/{item_id}/photos/{first.id}/kind", data={"kind": "other"})
    client.post(f"/items/{item_id}/photos/{first.id}/kind", data={"kind": "bogus"})
    assert next(p for p in _item(item_id).photos if p.id == first.id).kind == "other"

    r = client.get(f"/items/{item_id}/photos/{second.id}/delete")
    assert "It's the cover" in r.text and len(_item(item_id).photos) == 2  # confirm only
    files = paths(settings.images_dir, second.image_file, second.image_ext)
    r = client.post(f"/items/{item_id}/photos/{second.id}/delete", follow_redirects=False)
    assert r.status_code == 303
    item = _item(item_id)
    assert [p.id for p in item.photos] == [first.id] and item.photos[0].position == 0
    assert nearest_color_name(item.colors[0].hex) == "navy"
    assert not any(f.exists() for f in files.values())

    r = client.post(f"/items/{item_id}/photos/{first.id}/delete")
    assert r.status_code == 422 and "only photo" in r.text


def test_photo_limit_and_empty_add(client, monkeypatch):
    item_id = _create_with(client, [NAVY])
    r = client.post(f"/items/{item_id}/photos", data={"kind": "real"})
    assert r.status_code == 422 and "Choose a photo" in r.text
    import app.services.library as library
    monkeypatch.setattr(library, "MAX_PHOTOS", 2)
    r = client.post(f"/items/{item_id}/photos",
                    files=[("photo", _jpeg(RED)), ("photo", _jpeg(GREEN))])
    assert r.status_code == 422 and "at most 2 photos" in r.text


def test_partial_failure_keeps_good_photos(client):
    r = client.post("/add/photo", files=[("photo", _jpeg(NAVY)),
                                         ("photo", ("bad.jpg", b"nope", "image/jpeg"))])
    assert r.status_code == 200
    assert len(_tokens(r.text)) == 1 and "Skipped: Photo 2" in r.text


def test_delete_item_removes_all_photo_files(client, settings):
    item_id = _create_with(client, [NAVY, RED, GREEN])
    files = [f for p in _item(item_id).photos
             for f in paths(settings.images_dir, p.image_file, p.image_ext).values()]
    assert len(files) == 9 and all(f.exists() for f in files)
    client.post(f"/items/{item_id}/delete")
    assert not any(f.exists() for f in files)


# ---------- bookmark ----------

def test_add_page_has_bookmarklet(client):
    r = client.get("/add")
    m = re.search(r'class="button primary bookmarklet" href="(javascript:[^"]+)"', r.text)
    assert m
    code = unquote(m.group(1))
    assert 'var APP = "http://testserver";' in code and '"/add/bookmark?"' in code


def test_bookmark_preview_lists_candidates(client):
    r = client.get("/add/bookmark", params=[
        ("url", "https://ca.store.example/p/jumper.html"), ("title", "Treccia jumper"),
        ("brand", "Loro Piana"),
        ("img", "https://media.store.example/a.jpg"), ("img", "https://media.store.example/b.jpg"),
        ("img", "javascript:alert(1)"), ("img", "https://media.store.example/a.jpg"),
        ("img", "data:image/png;base64,xx")])
    assert r.status_code == 200
    assert "Pick the photos to keep" in r.text
    assert r.text.count('name="image_url" value="https://media.store.example/') == 2
    assert "javascript:alert" not in r.text and "data:image" not in r.text
    assert 'value="Treccia jumper"' in r.text and 'value="Loro Piana"' in r.text
    assert 'name="source_url" value="https://ca.store.example/p/jumper.html"' in r.text


def test_bookmark_without_images_falls_back(client):
    r = client.get("/add/bookmark", params={"url": "https://store.example/x", "title": "X"})
    assert r.status_code == 422 and "found no product images" in r.text
    assert 'name="photo"' in r.text


def test_bookmark_rejects_non_http_page_url(client):
    r = client.get("/add/bookmark", params=[("url", "javascript:alert(1)"),
                                            ("img", "https://media.store.example/a.jpg")])
    assert "javascript:alert" not in r.text


def test_multi_image_import_creates_product_photos(client, fake_web):
    for name, color in (("a", NAVY), ("b", RED)):
        fake_web[f"https://media.store.example/{name}.jpg"] = httpx.Response(
            200, content=make_image(garment=color), headers={"content-type": "image/jpeg"})
    r = client.post("/add/image-url", data={
        "image_url": ["https://media.store.example/a.jpg", "https://media.store.example/b.jpg"],
        "source_url": "https://ca.store.example/p/jumper.html", "name": "Jumper",
        "brand": "Loro Piana"})
    assert r.status_code == 200
    tokens = _tokens(r.text)
    assert len(tokens) == 2 and r.text.count('<option value="product" selected>') == 2
    r = client.post("/items", data={"image_token": tokens, "photo_kind": ["product", "product"],
                                    "name": "Jumper", "category_id": "1",
                                    "source_url": "https://ca.store.example/p/jumper.html"},
                    follow_redirects=False)
    item = _item(int(r.headers["location"].rsplit("/", 1)[1]))
    assert [p.kind for p in item.photos] == ["product", "product"]


# ---------- migration ----------

def test_migration_moves_existing_photo_and_keeps_children(tmp_path, monkeypatch):
    """A database at schema 0001 with an item, tags and colors upgrades without losing rows."""
    monkeypatch.setenv("WARDROBE_DATA", str(tmp_path / "data"))
    from alembic import command
    from alembic.config import Config

    from app.config import PROJECT_DIR, get_settings
    from app.db import reset_engine

    get_settings.cache_clear()
    reset_engine()
    get_settings().ensure_dirs()
    cfg = Config(str(PROJECT_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_DIR / "migrations"))
    command.upgrade(cfg, "0001")

    db = str(get_settings().db_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO item (id, name, category_id, image_file, image_ext, image_sha256, "
                "width, height, created_at, updated_at) VALUES "
                "(7, 'Old coat', 4, 'abc', 'png', 'ff', 10, 20, '2026-10-01', '2026-10-01')")
    con.execute("INSERT INTO tag (id, name) VALUES (1, 'wool')")
    con.execute("INSERT INTO item_tag VALUES (7, 1)")
    con.execute("INSERT INTO item_color (item_id, rank, hex, share, lab_l, lab_a, lab_b, hue) "
                "VALUES (7, 0, '#111111', 1, 5, 0, 0, 0)")
    con.commit()
    con.close()

    command.upgrade(cfg, "head")
    con = sqlite3.connect(db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(item)")]
    assert "image_file" not in cols
    assert con.execute("SELECT item_id, position, kind, image_file, image_ext, width, height "
                       "FROM item_photo").fetchall() == [(7, 0, "product", "abc", "png", 10, 20)]
    assert con.execute("SELECT count(*) FROM item_tag").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM item_color").fetchone()[0] == 1
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []

    command.downgrade(cfg, "0001")
    assert con.execute("SELECT image_file, image_ext FROM item WHERE id = 7").fetchone() == ("abc", "png")
    con.close()
    reset_engine()
    get_settings.cache_clear()
