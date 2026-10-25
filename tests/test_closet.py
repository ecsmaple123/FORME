"""Fabric (field, name splitting, migration 0005), the item cards, and new categories from the item form."""
import re
import sqlite3

from sqlmodel import Session, select

from app.db import get_engine
from app.models import Category, Item
from app.services.fabric import split_name

from .conftest import make_image


def _staged(client, **form):
    r = client.post("/add/photo", files={"photo": ("p.jpg", make_image(), "image/jpeg")}, data=form)
    return r, re.search(r'name="image_token" value="([0-9a-f]{32})"', r.text).group(1)


def _save(client, token, **form):
    data = {"image_token": token, "photo_kind": "product", "name": "Coat", "category_id": "4", **form}
    return client.post("/items", data=data, follow_redirects=False)


def _categories():
    with Session(get_engine()) as s:
        return [(c.name, c.sort_order) for c in s.exec(select(Category).order_by(Category.sort_order))]


def test_split_name():
    assert split_name("Cashmere Quarter Zip") == ("Quarter Zip", "Cashmere")
    assert split_name("Cashmere Corduroy Peacoat") == ("Peacoat", "Cashmere Corduroy")
    assert split_name("Cotton Silk Baseball Jacket") == ("Baseball Jacket", "Cotton Silk")
    assert split_name("Light Green Cashmere Quarter Zip") == ("Light Green Quarter Zip", "Cashmere")
    assert split_name("Wool-Silk Scarf") == ("Scarf", "Wool-Silk")
    assert split_name("Suede Boots") == ("Boots", "Suede")
    assert split_name("Field Jacket") == ("Field Jacket", "")      # nothing to split
    assert split_name("Oxford Shirt") == ("Oxford Shirt", "")      # garment words stay
    assert split_name("Cashmere") == ("Cashmere", "")              # never empties a name
    assert split_name("") == ("", "")


def test_fabric_saved_shown_and_on_cards(client):
    _r, token = _staged(client)
    r = _save(client, token, name="Overcoat", fabric="  Cashmere   wool ", brand="Loro Piana")
    item_id = int(r.headers["location"].rsplit("/", 1)[1])
    detail = client.get(f"/items/{item_id}").text
    assert "<dt>Fabric</dt><dd>Cashmere wool</dd>" in detail
    grid = client.get("/closet", headers={"HX-Request": "true"}).text
    assert '<div class="muted card-fabric">Cashmere wool</div>' in grid
    assert "Loro Piana" not in grid                                 # no brand on cards
    home = client.get("/").text
    assert "Cashmere wool" in home and "Loro Piana" not in home
    edit = client.get(f"/items/{item_id}/edit").text
    assert 'name="fabric" value="Cashmere wool"' in edit and '<option value="Cashmere wool">' in edit


def test_import_splits_fabric_out_of_the_name(client):
    r, _token = _staged(client, name="Cashmere Corduroy Peacoat", brand="Brunello Cucinelli")
    assert 'name="name" value="Peacoat"' in r.text
    assert 'name="fabric" value="Cashmere Corduroy"' in r.text


def test_new_category_while_adding(client):
    r, token = _staged(client)
    assert "+ New category…" in r.text
    before = _categories()
    r = _save(client, token, category_id="new", new_category="  Knit   wear ")
    assert r.status_code == 303
    item_id = int(r.headers["location"].rsplit("/", 1)[1])
    assert _categories()[-1] == ("Knit wear", before[-1][1] + 10)  # added last
    assert "Knit wear" in client.get(f"/items/{item_id}").text
    # typing an existing name (any case) reuses it
    _r, token = _staged(client)
    _save(client, token, category_id="new", new_category="OUTERWEAR")
    assert len(_categories()) == len(before) + 1


def test_new_category_not_created_when_the_form_has_errors(client):
    _r, token = _staged(client)
    before = _categories()
    r = _save(client, token, name=" ", category_id="new", new_category="Swimwear")
    assert r.status_code == 422 and "Give the item a name" in r.text
    assert 'name="new_category" value="Swimwear"' in r.text and '<option value="new" selected>' in r.text
    assert _categories() == before
    # a typed name without choosing "+ New category…" is ignored
    r = _save(client, token, category_id="5", new_category="Ignored")
    assert r.status_code == 303 and _categories() == before
    with Session(get_engine()) as s:
        assert s.exec(select(Item)).one().category_id == 5


def test_new_category_needs_a_name(client):
    _r, token = _staged(client)
    r = _save(client, token, category_id="new", new_category="  ")
    assert r.status_code == 422 and "Pick a category" in r.text


def test_migration_0005_moves_fabric_out_of_names(tmp_path, monkeypatch):
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
    command.upgrade(cfg, "0004")
    con = sqlite3.connect(str(get_settings().db_path))
    for i, name in enumerate(["Cashmere Quarter Zip", "Field Jacket", "Cotton Silk Baseball Jacket"]):
        con.execute("INSERT INTO item (id, name, category_id, created_at, updated_at) "
                    "VALUES (?, ?, 1, '2026-10-25', '2026-10-25')", (i + 1, name))
    con.commit()
    command.upgrade(cfg, "head")
    rows = con.execute("SELECT name, fabric FROM item ORDER BY id").fetchall()
    assert rows == [("Quarter Zip", "Cashmere"), ("Field Jacket", ""), ("Baseball Jacket", "Cotton Silk")]
    command.downgrade(cfg, "0004")
    assert [r[0] for r in con.execute("SELECT name FROM item ORDER BY id")] == [
        "Cashmere Quarter Zip", "Field Jacket", "Cotton Silk Baseball Jacket"]
    con.close()
    reset_engine()
    get_settings.cache_clear()
