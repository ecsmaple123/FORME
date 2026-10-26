import io
import re

from PIL import Image
from sqlmodel import Session, select

from app.db import get_engine
from app.models import Item, Tag
from app.services.images import paths

from .conftest import make_image


def _upload(client, data=None, filename="shirt.jpg", **form):
    data = data if data is not None else make_image()
    r = client.post("/add/photo", files={"photo": (filename, data, "image/jpeg")}, data=form)
    token = re.search(r'name="image_token" value="([0-9a-f]{32})"', r.text)
    return r, token.group(1) if token else None


def _create(client, name="Navy oxford shirt", category_id="1", **extra):
    r, token = _upload(client)
    assert r.status_code == 200 and token
    prefilled = {k: re.search(rf'name="{k}" value="([^"]*)"', r.text).group(1)
                 for k in ("color_hex", "color_name")}  # what the browser sends back
    form = {"image_token": token, "name": name, "category_id": category_id, **prefilled,
            "brand": "Uniqlo", "size": "M", "seasons": ["spring", "autumn"],
            "tags": "Work, cotton, work", "notes": "Iron on low", **extra}
    r = client.post("/items", data=form, follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rsplit("/", 1)[1])


def _item(item_id):
    with Session(get_engine()) as s:
        item = s.get(Item, item_id)
        if item:
            _ = item.tags, item.colors, item.photos
        return item


def test_categories_seeded(client):
    r = client.get("/settings")
    for name in ["Tops", "Bottoms", "Dresses/One-pieces", "Outerwear", "Shoes",
                 "Accessories", "Bags", "Activewear", "Underwear/Sleepwear"]:
        assert name in r.text


def test_upload_prefills_color_and_makes_files(client, settings):
    r, token = _upload(client)
    assert r.status_code == 200
    assert 'value="Navy"' in r.text  # dominant color named, white background ignored
    p = paths(settings.images_dir, token, "jpg")
    assert all(f.is_file() for f in p.values())
    with Image.open(p["thumb"]) as t:
        assert max(t.size) <= 400 and t.format == "WEBP"


def test_add_edit_delete(client, settings):
    item_id = _create(client)
    item = _item(item_id)
    assert item.name == "Navy oxford shirt" and item.brand == "Uniqlo"
    assert item.seasons == "spring,autumn"
    assert sorted(t.name for t in item.tags) == ["cotton", "work"]
    assert item.color_name == "Navy" and item.color_hex.startswith("#")
    assert 1 <= len(item.colors) <= 5 and item.colors[0].rank == 0
    assert item.created_at is not None

    r = client.get(f"/items/{item_id}")
    assert "Navy oxford shirt" in r.text and "Iron on low" in r.text

    r = client.post(f"/items/{item_id}/edit", data={
        "name": "Oxford shirt", "category_id": "1", "color_hex": "#FFFFFF", "color_name": "",
        "tags": "office", "seasons": ["summer"]}, follow_redirects=False)
    assert r.status_code == 303
    item = _item(item_id)
    assert item.name == "Oxford shirt" and item.color_hex == "#ffffff"
    assert item.color_name == "White" and item.seasons == "summer" and item.brand == ""
    assert [t.name for t in item.tags] == ["office"]
    with Session(get_engine()) as s:  # tags no longer used are cleaned up
        assert sorted(t.name for t in s.exec(select(Tag)).all()) == ["office"]

    r = client.get(f"/items/{item_id}/delete")
    assert "Yes, delete it" in r.text
    assert _item(item_id) is not None  # the confirm page alone deletes nothing
    files = paths(settings.images_dir, item.cover.image_file, item.cover.image_ext)
    r = client.post(f"/items/{item_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert _item(item_id) is None
    assert not any(f.exists() for f in files.values())
    assert client.get(f"/items/{item_id}").status_code == 404


def test_closet_search_filter_sort(client):
    a = _create(client, name="Blue jeans", category_id="2", tags="denim")
    b = _create(client, name="Anorak", category_id="4", brand="Arket", tags="rain")
    c = _create(client, name="Bomber", category_id="4", fabric="Suede")
    hx = {"HX-Request": "true"}

    def ids(**params):
        r = client.get("/closet", params=params, headers=hx)
        return [int(x) for x in re.findall(r'href="/items/(\d+)"', r.text)]

    # grouped by category (Bottoms before Outerwear), sorted within each group
    assert ids() == [a, c, b]                    # newest first
    assert ids(sort="old") == [a, b, c]
    assert ids(sort="name") == [a, b, c]
    assert ids(q="jeans") == [a]                 # name
    assert ids(q="ARKET") == [b]                 # brand, case-insensitive
    assert ids(q="suede") == [c]                 # fabric
    assert ids(q="denim") == [a]                 # tag
    assert ids(q="100%") == []                   # LIKE wildcards are escaped
    assert ids(category="4") == [c, b]
    grid = client.get("/closet", headers=hx).text
    assert re.findall(r'class="group-title"[^>]*>([^<]+)<', grid) == ["Bottoms ", "Outerwear "]
    assert "group-title" not in client.get("/closet", params={"category": "4"}, headers=hx).text
    # the category order is the user's: move Outerwear above Bottoms (Dresses is between them)
    for _ in range(2):
        client.post("/categories/4/move", data={"direction": "up"})
    assert ids() == [c, b, a]
    full = client.get("/closet")
    assert 'id="grid"' in full.text and "Outerwear" in full.text


def test_validation_errors(client):
    r, token = _upload(client)
    r = client.post("/items", data={"image_token": token, "name": " ", "category_id": "999",
                                    "color_hex": "blue", "source_url": "javascript:alert(1)"})
    assert r.status_code == 422
    assert "Give the item a name" in r.text and "Pick a category" in r.text
    assert "hex color" in r.text and "must start with http" in r.text


def test_expired_or_forged_token(client):
    r = client.post("/items", data={"image_token": "../../etc/passwd", "name": "x",
                                    "category_id": "1"})
    assert r.status_code == 422 and "expired" in r.text


def test_rejects_non_image(client):
    r, token = _upload(client, data=b"not an image at all", filename="x.jpg")
    assert r.status_code == 422 and token is None
    assert "isn&#39;t an image" in r.text


def test_large_photo_original_is_capped(client, settings):
    r, token = _upload(client, data=make_image(size=(4000, 3000)))
    assert token
    with Image.open(paths(settings.images_dir, token, "jpg")["orig"]) as im:
        assert max(im.size) == 3000


def test_transparent_png(client, settings):
    data = make_image(size=(800, 800), fmt="PNG", mode="RGBA", garment=(198, 42, 42),
                      background=(0, 0, 0))
    r = client.post("/add/photo", files={"photo": ("bag.png", data, "image/png")})
    assert r.status_code == 200 and 'value="Red"' in r.text


def test_category_crud(client):
    item_id = _create(client, category_id="1")
    r = client.post("/categories/1/delete")
    assert r.status_code == 422 and "still has 1 item" in r.text
    r = client.post("/categories", data={"name": "tops"})
    assert r.status_code == 422 and "already a category" in r.text and 'id="categories"' in r.text
    r = client.post("/categories", data={"name": "Swimwear"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/settings#categories"
    names = re.findall(r'aria-label="Name of ([^"]+)"', client.get("/settings").text)
    assert names[-1] == "Swimwear"               # new categories go last
    r = client.post("/categories/1", data={"name": "T-shirts & tops"}, follow_redirects=False)
    assert r.status_code == 303
    assert "T-shirts &amp; tops" in client.get(f"/items/{item_id}").text
    # moving: up from the top and down from the bottom are no-ops
    client.post("/categories/2/move", data={"direction": "up"})
    client.post("/categories/2/move", data={"direction": "up"})
    names = re.findall(r'aria-label="Name of ([^"]+)"', client.get("/settings").text)
    assert names[:2] == ["Bottoms", "T-shirts &amp; tops"]
    # the old page and its nav link are gone
    r = client.get("/categories", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/settings#categories"
    assert 'href="/categories"' not in client.get("/").text


def test_backup_and_restore(client, settings):
    from app import ops

    item_id = _create(client, name="Keep me")
    archive = ops.backup()
    assert archive.is_file() and archive.with_name(archive.name + ".sha256").is_file()
    client.post(f"/items/{item_id}/delete")
    assert _item(item_id) is None

    ops.restore(str(archive))
    item = _item(item_id)
    assert item is not None and item.name == "Keep me"
    p = paths(settings.images_dir, item.cover.image_file, item.cover.image_ext)
    assert all(f.is_file() for f in p.values())  # display + thumb rebuilt from the original
    assert list(settings.data_dir.parent.glob("data.before-restore-*"))


def test_backup_keeps_newest(settings, monkeypatch):
    from app import ops

    monkeypatch.setattr(ops, "get_settings", lambda: settings.__class__(
        **{**settings.__dict__, "backup_keep": 2}))
    made = []
    for i in range(3):
        monkeypatch.setattr(ops, "datetime", _FixedClock(i))
        made.append(ops.backup())
    assert ops.list_backups() == made[1:]
    assert not made[0].with_name(made[0].name + ".sha256").exists()


class _FixedClock:
    def __init__(self, n):
        from datetime import datetime
        self._now = datetime(2026, 10, 24, 12, 0, n)

    def now(self):
        return self._now


def test_exif_rotation_applied(client, settings):
    im = Image.open(io.BytesIO(make_image(size=(1500, 1000))))
    exif = im.getexif()
    exif[0x0112] = 6  # camera held upright: stored landscape, shown portrait
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif)
    r, token = _upload(client, data=buf.getvalue())
    with Image.open(paths(settings.images_dir, token, "jpg")["display"]) as d:
        assert d.height > d.width


def test_big_png_rejected_with_clear_message(client):
    data = make_image(size=(4000, 3100), fmt="PNG")
    r, token = _upload(client, data=data, filename="huge.png")
    assert r.status_code == 422 and token is None
    assert "over 8.5 megapixels" in r.text


def test_big_png_under_cap_is_kept_as_is(client, settings):
    r, token = _upload(client, data=make_image(size=(2900, 2900), fmt="PNG"), filename="b.png")
    assert token
    p = paths(settings.images_dir, token, "png")
    with Image.open(p["orig"]) as im:
        assert im.format == "PNG" and im.size == (2900, 2900)
    with Image.open(p["display"]) as im:
        assert max(im.size) == 1500


def test_cleanup_removes_orphans_only(client, settings):
    from app.services.library import cleanup_staging

    keep_id = _create(client)
    _, staged = _upload(client)
    orphan = settings.images_dir / "orig" / ("f" * 32 + ".png")
    orphan.write_bytes(b"x")
    cleanup_staging(max_age=-1)
    assert not orphan.exists()
    assert not (settings.staging_dir / f"{staged}.json").exists()  # staged + old: removed
    item = _item(keep_id)
    assert all(f.exists() for f in paths(settings.images_dir, item.cover.image_file, item.cover.image_ext).values())


def test_truncated_jpeg_is_a_clear_error(client):
    data = make_image()[:5000]
    r, token = _upload(client, data=data)
    assert r.status_code == 422 and token is None and "may be damaged" in r.text


def test_hex_without_hash(client):
    item = _item(_create(client, color_hex=" C62A2A ", color_name=""))  # phone keyboards: no #
    assert item.color_hex == "#c62a2a" and item.color_name == "Red"
