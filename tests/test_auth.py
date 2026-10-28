"""Outside access: the password gate, logging in, wrong-password limits, Settings, the tunnel."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.routes.auth import safe_next
from app.services import auth

PASSWORD = "correct horse"


@pytest.fixture
def outside(settings):
    """A visitor through the tunnel: cloudflared connects from the Pi and adds Cf-* headers."""
    with TestClient(create_app(), base_url="https://testserver", client=(settings.host, 41000),
                    headers={"cf-connecting-ip": "203.0.113.9", "cf-ray": "abc",
                             "x-forwarded-proto": "https"}) as c:
        yield c


def _set_password(client, password=PASSWORD):
    return client.post("/settings/password", data={"password": password, "confirm": password},
                       follow_redirects=False)


def _login(c, password=PASSWORD, next_url="/"):
    return c.post("/login", data={"password": password, "next": next_url}, follow_redirects=False)


def test_home_needs_no_login(client):
    assert client.get("/").status_code == 200
    r = client.get("/login?next=/closet", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/closet"
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert client.get("/healthz").json() == {"ok": True, "items": 0}


def test_outside_is_closed_until_a_password_is_set(client, outside):
    r = outside.get("/closet?sort=new", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2Fcloset%3Fsort%3Dnew"
    assert "isn't open outside" in outside.get("/login").text
    assert _login(outside).status_code == 403
    for path in ("/media/cutout/x.webp", "/settings", "/stylist"):
        assert outside.get(path, follow_redirects=False).status_code == 303
    assert outside.post("/items", data={}, follow_redirects=False).status_code == 303
    r = outside.post("/stylist", headers={"HX-Request": "true"})
    assert r.status_code == 401 and r.headers["HX-Redirect"] == "/login"
    assert outside.get("/static/style.css").status_code == 200
    assert outside.get("/healthz").json() == {"ok": True}  # no item count


def test_set_password_at_home(client):
    r = client.post("/settings/password", data={"password": "short", "confirm": "short"})
    assert r.status_code == 422 and "at least 8" in r.text
    r = client.post("/settings/password", data={"password": PASSWORD, "confirm": "something else"})
    assert "passwords don&#39;t match" in r.text
    assert "No password yet" in client.get("/settings").text
    r = _set_password(client)
    assert r.status_code == 303 and r.headers["location"] == "/settings?access=1#access"
    page = client.get("/settings?access=1").text
    assert "Change password" in page and "Remove password" in page and "Current password" not in page
    assert auth.has_password() and auth.check_password(PASSWORD) and not auth.check_password("nope")


def test_login_from_outside(client, outside):
    _set_password(client)
    r = _login(outside, "wrong password")
    assert r.status_code == 401 and "password isn&#39;t right" in r.text
    r = _login(outside, next_url="/closet")
    assert r.status_code == 303 and r.headers["location"] == "/closet"
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "samesite=lax" in cookie.lower()
    assert outside.get("/closet").status_code == 200
    assert outside.get("/healthz").json() == {"ok": True}
    page = outside.get("/settings").text
    assert "Log out" in page and "View only" in page and "Change password" not in page
    r = outside.post("/logout", follow_redirects=False)
    assert r.headers["location"] == "/login"
    assert outside.get("/closet", follow_redirects=False).status_code == 303


def test_wrong_passwords_are_limited(client, outside):
    _set_password(client)
    for _ in range(auth.PER_ADDRESS):
        assert _login(outside, "wrong password").status_code == 401
    r = _login(outside)
    assert r.status_code == 429 and "Wait 15 minutes" in r.text
    # another address still can, until the overall limit
    with TestClient(create_app(), client=("198.51.100.7", 1)) as other:
        assert _login(other).status_code == 303


def test_tunnel_and_the_pi_itself_never_count_as_home(settings):
    assert auth.is_home("192.168.0.50", {})
    assert not auth.is_home("192.168.0.50", {"cf-connecting-ip": "203.0.113.9"})
    assert not auth.is_home(settings.host, {})
    assert not auth.is_home("127.0.0.1", {})
    assert not auth.is_home("172.16.5.2", {})  # e.g. VPN visitors: they log in like anyone outside
    assert not auth.is_home("testclient", {})
    assert auth.on_the_pi(settings.host, {}) and not auth.on_the_pi(settings.host, {"cf-ray": "x"})


def test_changing_the_password_logs_everyone_out(client, outside):
    _set_password(client)
    _login(outside)
    assert outside.get("/closet").status_code == 200
    _set_password(client, "a brand new one")
    assert outside.get("/closet", follow_redirects=False).status_code == 303


def test_only_home_can_change_or_remove_the_password(client, outside):
    _set_password(client)
    _login(outside)
    r = outside.post("/settings/password", data={"password": "new password 1",
                                                 "confirm": "new password 1"})
    assert r.status_code == 403 and auth.check_password(PASSWORD)
    assert outside.post("/settings/password/remove").status_code == 403
    assert auth.has_password()
    client.post("/settings/password/remove")
    assert not auth.has_password()
    assert outside.get("/closet", follow_redirects=False).status_code == 303


def test_safe_next():
    assert safe_next("/closet?x=1") == "/closet?x=1"
    for bad in ("//evil.example", "https://evil.example", "/\\evil.example", "closet", ""):
        assert safe_next(bad) == "/"


def test_cli_password(settings, monkeypatch, capsys):
    from app.__main__ import main

    assert main(["app", "password"]) == 1
    answers = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert main(["app", "password", "set"]) == 0 and auth.check_password(PASSWORD)
    assert main(["app", "password", "remove"]) == 1 and not auth.has_password()
    assert "not set" in capsys.readouterr().out
