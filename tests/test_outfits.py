"""Outfits and the Studio: saving boards, editing, deleting, and the 0007 migration."""
import json
import re
import sqlite3

from sqlmodel import Session

from app.db import get_engine
from app.models import Outfit
from app.services import outfits

from .conftest import make_image


def _item(client, name="Coat", garment=(29, 38, 69)):
    r = client.post("/add/photo", files={"photo": ("p.jpg", make_image(garment=garment), "image/jpeg")})
    token = re.search(r'name="image_token" value="([0-9a-f]{32})"', r.text).group(1)
    r = client.post("/items", data={"image_token": token, "photo_kind": "product", "name": name,
                                    "category_id": "1"}, follow_redirects=False)
    return int(r.headers["location"].rsplit("/", 1)[1])


def _save(client, board, **form):
    return client.post("/outfits", data={"layout": json.dumps(board), **form},
                       follow_redirects=False)


def _outfit(outfit_id):
    with Session(get_engine()) as s:
        return outfits.get_outfit(s, outfit_id)


def _studio_data(html):
    return json.loads(re.search(r'<script id="studio-data" type="application/json">(.*?)</script>',
                                html, re.S).group(1))


def test_empty_pages(client):
    assert "No outfits yet" in client.get("/outfits").text
    r = client.get("/studio")
    assert r.status_code == 200 and "Your closet is empty" in r.text
    assert _studio_data(r.text) == {"items": {}, "board": [], "outfit": None, "max": outfits.MAX_ITEMS}
    assert 'href="/outfits"' in client.get("/").text


def test_save_list_and_detail(client):
    coat, shoes = _item(client, "Coat"), _item(client, "Boots", (90, 60, 40))
    data = _studio_data(client.get("/studio").text)
    assert set(data["items"]) == {str(coat), str(shoes)}
    assert data["items"][str(coat)]["name"] == "Coat"

    r = _save(client, [{"item_id": coat, "x": 0.1, "y": 0.05, "w": 0.6},
                       {"item_id": shoes, "x": 0.3, "y": 0.7, "w": 0.3}], notes="Friday")
    assert r.status_code == 303
    outfit_id = int(re.search(r"/outfits/(\d+)\?saved=1", r.headers["location"]).group(1))
    o = _outfit(outfit_id)
    assert o.name == "Outfit 1" and o.notes == "Friday"
    assert [(link.item_id, link.position, link.w) for link in o.links] == [(coat, 0, 0.6), (shoes, 1, 0.3)]

    page = client.get("/outfits").text
    assert f'href="/outfits/{outfit_id}"' in page and "2 items" in page
    assert "left: 10.00%; top: 5.00%; width: 60.00%; z-index: 1" in page
    detail = client.get(f"/outfits/{outfit_id}?saved=1").text
    assert "Outfit saved" in detail and f'href="/studio?outfit={outfit_id}"' in detail
    assert f'href="/items/{coat}"' in detail and f'href="/items/{shoes}"' in detail


def test_edit_save_as_new_and_bad_boards(client):
    coat, shoes = _item(client, "Coat"), _item(client, "Boots")
    r = _save(client, [{"item_id": coat, "x": 0, "y": 0, "w": 0.5},
                       {"item_id": shoes, "x": 0.5, "y": 0.5, "w": 0.3}], name="Work")
    outfit_id = int(r.headers["location"].split("/")[2].split("?")[0])

    data = _studio_data(client.get(f"/studio?outfit={outfit_id}").text)
    assert data["outfit"] == outfit_id and [p["item_id"] for p in data["board"]] == [coat, shoes]

    # edit: shoes to the back, coat moved; the same rows are updated (no primary key clash)
    r = _save(client, [{"item_id": shoes, "x": 0.2, "y": 0.6, "w": 0.3},
                       {"item_id": coat, "x": 0.25, "y": 0.1, "w": 9}],
              name="Work", outfit_id=str(outfit_id))
    assert r.status_code == 303
    o = _outfit(outfit_id)
    assert [(link.item_id, link.x, link.w) for link in o.links] == [(shoes, 0.2, 0.3),
                                                                    (coat, 0.25, outfits.MAX_W)]
    # remove one item, then put it back
    _save(client, [{"item_id": coat, "x": 0, "y": 0, "w": 0.5}], name="Work", outfit_id=str(outfit_id))
    assert [link.item_id for link in _outfit(outfit_id).links] == [coat]
    _save(client, [{"item_id": coat, "x": 0, "y": 0, "w": 0.5},
                   {"item_id": shoes, "x": 0, "y": 0, "w": 0.5}], name="Work", outfit_id=str(outfit_id))
    assert len(_outfit(outfit_id).links) == 2

    r = _save(client, [{"item_id": coat, "x": 0, "y": 0, "w": 0.5}], name="Weekend",
              outfit_id=str(outfit_id), as_new="1")
    assert r.status_code == 303 and len(_outfit(outfit_id).links) == 2
    with Session(get_engine()) as s:
        assert s.get(Outfit, outfit_id + 1).name == "Weekend"

    r = _save(client, [])
    assert r.status_code == 422 and "at least one item" in r.text
    r = client.post("/outfits", data={"layout": "not json", "name": "Keep"})
    assert r.status_code == 422 and "be read. Please try again" in r.text and 'value="Keep"' in r.text
    r = _save(client, [{"item_id": coat, "x": "nan", "y": 0, "w": 0.5}])
    assert r.status_code == 422
    r = _save(client, [{"item_id": 999, "x": 0, "y": 0, "w": 0.5}])
    assert r.status_code == 422 and "no longer exist" in r.text
    # a failed save of an edited outfit stays in the edit
    r = _save(client, [], outfit_id=str(outfit_id))
    assert r.status_code == 422 and f'name="outfit_id" value="{outfit_id}"' in r.text
    assert client.get("/outfits/999").status_code == 404
    assert client.get("/studio?outfit=999").status_code == 404


def test_deleting_items_and_outfits(client):
    coat, shoes = _item(client, "Coat"), _item(client, "Boots")
    r = _save(client, [{"item_id": coat, "x": 0, "y": 0, "w": 0.5},
                       {"item_id": shoes, "x": 0, "y": 0.5, "w": 0.5}])
    outfit_id = int(r.headers["location"].split("/")[2].split("?")[0])
    client.post(f"/items/{shoes}/delete")
    assert [link.item_id for link in _outfit(outfit_id).links] == [coat]
    assert "1 item" in client.get("/outfits").text

    assert "Delete “Outfit 1”?" in client.get(f"/outfits/{outfit_id}/delete").text
    r = client.post(f"/outfits/{outfit_id}/delete", follow_redirects=False)
    assert r.headers["location"] == "/outfits?deleted=1"
    assert _outfit(outfit_id) is None
    assert client.get(f"/items/{coat}").status_code == 200  # the item stays


def test_studio_data_is_escaped(client):
    _item(client, "</script><script>alert(1)</script>")
    r = client.get("/studio")
    assert "</script><script>alert(1)" not in r.text
    assert list(_studio_data(r.text)["items"].values())[0]["name"].startswith("</script>")


def test_migration_0007(tmp_path, monkeypatch):
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
    command.upgrade(cfg, "0006")
    con = sqlite3.connect(str(get_settings().db_path))
    con.execute("INSERT INTO item (id, name, category_id, created_at, updated_at) "
                "VALUES (1, 'Coat', 1, '2026-10-24', '2026-10-24')")
    con.execute("INSERT INTO outfit (id, name, created_at) VALUES (1, 'Old', '2026-10-24 10:00:00')")
    con.execute("INSERT INTO outfit_item (outfit_id, item_id, position) VALUES (1, 1, 0)")
    con.commit()
    command.upgrade(cfg, "head")
    assert con.execute("SELECT x, y, w FROM outfit_item").fetchall() == [(0.0, 0.0, 0.4)]
    assert con.execute("SELECT updated_at FROM outfit").fetchone()[0].startswith("2026-10-24 10:00")
    command.downgrade(cfg, "0006")
    assert "x" not in [r[1] for r in con.execute("PRAGMA table_info(outfit_item)")]
    assert con.execute("SELECT count(*) FROM outfit_item").fetchone()[0] == 1
    con.close()
    reset_engine()
    get_settings.cache_clear()
