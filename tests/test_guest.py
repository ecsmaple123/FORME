"""Visitors from outside (logged in with the shared password) are guests: they can look at
everything and make outfits, but not change the closet, the categories or the settings."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from .test_auth import PASSWORD, _login, _set_password
from .test_outfits import _item, _outfit, _save, _studio_data


@pytest.fixture
def guest(client, settings):
    _set_password(client)
    with TestClient(create_app(), base_url="https://testserver", client=(settings.host, 41000),
                    headers={"cf-connecting-ip": "203.0.113.9", "cf-ray": "abc",
                             "x-forwarded-proto": "https"}) as c:
        assert _login(c).status_code == 303
        yield c


def test_guests_can_look_but_not_change_the_closet(client, guest):
    coat = _item(client)
    for path in ("/", "/closet", f"/items/{coat}", "/outfits", "/studio", "/stylist", "/settings"):
        assert guest.get(path).status_code == 200, path
    page = guest.get(f"/items/{coat}").text
    assert "View only" in page and 'href="/add"' not in page
    assert f"/items/{coat}/edit" not in page and "+ Add photos" not in page
    settings_page = guest.get("/settings").text
    assert "Log out" in settings_page and "Categories" not in settings_page

    for path in ("/add", "/add/bookmark", f"/items/{coat}/edit", f"/items/{coat}/delete",
                 f"/items/{coat}/photos/1/touchup", f"/items/{coat}/photos/1/delete"):
        r = guest.get(path)
        assert r.status_code == 403 and "View only" in r.text, path
    for path in ("/items", "/add/photo", f"/items/{coat}/edit", f"/items/{coat}/delete",
                 f"/items/{coat}/photos", "/categories", "/categories/1/delete", "/settings",
                 "/settings/location", "/settings/stylist", "/stylist/forget", "/stylist/notes",
                 "/suggestions/1/verdict", "/picks/again"):
        assert guest.post(path, data={"name": "x"}).status_code == 403, path
    r = guest.post("/stylist/notes", headers={"HX-Request": "true"})
    assert r.status_code == 403 and "View only" in r.text
    assert client.get(f"/items/{coat}").text.count("Coat") and client.get("/add").status_code == 200


def test_guests_make_their_own_outfits(client, guest):
    coat = _item(client)
    board = [{"item_id": coat, "x": 0.1, "y": 0.1, "w": 0.5}]
    home_id = int(_save(client, board, name="Mine").headers["location"].split("/")[2].split("?")[0])

    r = _save(guest, board, name="Theirs")
    guest_id = int(r.headers["location"].split("/")[2].split("?")[0])
    assert _outfit(guest_id).source == "guest"  # the stylist doesn't learn it as the owner's taste

    # the owner's outfit: a guest can open it in the Studio but only saves a copy, and can't delete it
    page = guest.get(f"/outfits/{home_id}").text
    assert "Copy in Studio" in page and f"/outfits/{home_id}/delete" not in page
    assert "Save as a new outfit" in guest.get(f"/studio?outfit={home_id}").text
    r = _save(guest, board, name="Changed", outfit_id=str(home_id))
    assert _outfit(home_id).name == "Mine" and f"/outfits/{home_id}?" not in r.headers["location"]
    assert guest.get(f"/outfits/{home_id}/delete").status_code == 403
    assert guest.post(f"/outfits/{home_id}/delete").status_code == 403 and _outfit(home_id)

    # their own outfit: edit and delete as usual
    assert _studio_data(guest.get(f"/studio?outfit={guest_id}").text)["outfit"] == guest_id
    _save(guest, board, name="Theirs 2", outfit_id=str(guest_id))
    assert _outfit(guest_id).name == "Theirs 2"
    assert guest.post(f"/outfits/{guest_id}/delete", follow_redirects=False).status_code == 303
    assert _outfit(guest_id) is None

    # at home everything can be changed, guests' outfits too
    gid = int(_save(guest, board).headers["location"].split("/")[2].split("?")[0])
    assert "Edit in Studio" in client.get(f"/outfits/{gid}").text
    client.post(f"/outfits/{gid}/delete")
    assert _outfit(gid) is None
