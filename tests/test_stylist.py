"""The AI stylist with a fake Gemini: requests, privacy, memory, daily picks, errors, saving."""
import json
import re
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from sqlmodel import Session, select

from app import worker
from app.db import get_engine
from app.models import Outfit, Suggestion
from app.services import ai, outfits, prefs

from .conftest import make_image
from .test_cutouts import fake_segment

NAVY, RED, GREEN = (29, 38, 69), (198, 42, 42), (60, 154, 75)


@pytest.fixture
def gemini(settings, monkeypatch):
    """A fake Gemini: records each request and answers with state.reply (a dict or a function)."""
    from app.config import get_settings

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    get_settings.cache_clear()
    state = SimpleNamespace(calls=[], reply={"outfits": []}, status=200, raw=None)

    def handler(request):
        body = json.loads(request.content)
        state.calls.append(SimpleNamespace(url=str(request.url), key=request.headers.get("x-goog-api-key"),
                                           body=body, text=_text(body), images=_images(body)))
        if state.status != 200:
            return httpx.Response(state.status, json={"error": {"message": "nope"}})
        if state.raw is not None:
            return httpx.Response(200, json=state.raw)
        reply = state.reply(body) if callable(state.reply) else state.reply
        return httpx.Response(200, json={"candidates": [
            {"content": {"parts": [{"text": json.dumps(reply)}]}, "finishReason": "STOP"}]})

    monkeypatch.setattr(ai, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    yield state
    get_settings.cache_clear()


def _text(body):
    return "\n".join(p["text"] for p in body["contents"][0]["parts"] if "text" in p)


def _images(body):
    return [p["inlineData"] for p in body["contents"][0]["parts"] if "inlineData" in p]


def _item(client, name, garment=NAVY, kind="product", category="1"):
    r = client.post("/add/photo", files={"photo": ("p.jpg", make_image(garment=garment), "image/jpeg")},
                    data={"photo_kind": kind})
    token = re.search(r'name="image_token" value="([0-9a-f]{32})"', r.text).group(1)
    r = client.post("/items", data={"image_token": token, "photo_kind": kind, "name": name,
                                    "category_id": category}, follow_redirects=False)
    return int(r.headers["location"].rsplit("/", 1)[1])


def _closet(client):
    ids = SimpleNamespace(coat=_item(client, "Peacoat", NAVY, category="4"),
                          shirt=_item(client, "Oxford shirt", RED),
                          fit=_item(client, "Linen trousers", GREEN, kind="fit", category="2"))
    worker.run_batch(lambda: fake_segment)  # cutouts for the item photos (not the fit picture)
    return ids


def _ask(client, occasion="dinner", **extra):
    return client.post("/stylist", data={"occasion": occasion, **extra}, headers={"HX-Request": "true"})


def _suggestions():
    with Session(get_engine()) as s:
        return list(s.exec(select(Suggestion).order_by(Suggestion.id)).all())


def test_without_a_key_everything_still_works(client):
    _item(client, "Peacoat")
    r = client.get("/stylist")
    assert "Set up your stylist" in r.text and "aistudio.google.com/apikey" in r.text
    home = client.get("/").text
    assert 'hx-get="/picks"' not in home and len(re.findall(r'class="pick">', home)) == 1
    assert "Not set up yet" in client.get("/settings").text
    r = _ask(client)
    assert "GEMINI_API_KEY" in r.text and _suggestions() == []


def test_suggest_sends_closet_and_keeps_private_things_out(client, gemini):
    ids = _closet(client)
    prefs.save({"name": "Forest", "style": "Quiet and tailored.\n  No logos. ",
                "place": "Toronto, Ontario, Canada", "latitude": "43.7", "longitude": "-79.4",
                "timezone": "America/Toronto"})
    gemini.reply = {"outfits": [
        {"title": "Navy dinner", "item_ids": [ids.coat, ids.shirt, ids.coat, 999], "reason": "Navy and red."},
        {"title": "Ghost", "item_ids": [999], "reason": "No such items."},
        {"title": "Relaxed", "item_ids": [ids.shirt, ids.fit], "reason": "Easy."},
    ]}
    r = _ask(client, "dinner with friends")
    assert r.status_code == 200 and r.text.count('class="card suggestion fresh"') == 2
    call = gemini.calls[0]
    assert call.key == "test-key" and "/models/gemini-3.5-flash:generateContent" in call.url
    assert call.body["generationConfig"]["responseMimeType"] == "application/json"
    assert "outfits" in call.body["generationConfig"]["responseSchema"]["properties"]
    assert "only the clothes in their closet" in call.body["systemInstruction"]["parts"][0]["text"]
    text = call.text
    assert "They ask: dinner with friends" in text and "Quiet and tailored.\nNo logos." in text
    assert f"#{ids.coat} Peacoat" in text and f"#{ids.fit} Linen trousers" in text
    # private: no name, no place, no fit picture; cutout photos of item photos only
    assert "Forest" not in text and "Toronto" not in text and "43.7" not in text
    assert len(call.images) == 2 and all(i["mimeType"] == "image/webp" for i in call.images)
    assert f"Photo of item #{ids.fit}" not in text

    stored = _suggestions()
    assert [(s.title, s.ids, s.source, s.request) for s in stored] == [
        ("Navy dinner", [ids.coat, ids.shirt], "stylist", "dinner with friends"),
        ("Relaxed", [ids.shirt, ids.fit], "stylist", "dinner with friends")]
    page = client.get("/stylist").text
    assert "Navy dinner" in page and "Navy and red." in page

    prefs.save({"stylist_photos": "off"})
    _ask(client)
    assert gemini.calls[-1].images == [] and "Photo of item" not in gemini.calls[-1].text


def test_likes_dislikes_and_saved_outfits_are_remembered(client, gemini):
    ids = _closet(client)
    gemini.reply = {"outfits": [{"title": "Navy dinner", "item_ids": [ids.coat, ids.shirt], "reason": "A."},
                                {"title": "Loud", "item_ids": [ids.shirt, ids.fit], "reason": "B."}]}
    _ask(client)
    liked, disliked = _suggestions()
    r = client.post(f"/suggestions/{liked.id}/verdict", data={"verdict": "like"}, headers={"HX-Request": "true"})
    assert 'aria-pressed="true"' in r.text and "Tell the stylist" in r.text
    client.post(f"/suggestions/{disliked.id}/verdict",
                data={"verdict": "dislike", "note": "too   much red"}, headers={"HX-Request": "true"})
    outfits.save_outfit(Session(get_engine()), None, "My Sunday", "",
                        [outfits.Placed(ids.coat, 0, 0, 0.5)])
    _ask(client)
    text = gemini.calls[-1].text
    assert f"Outfits they LIKED:\n- Navy dinner: Peacoat (#{ids.coat}), Oxford shirt (#{ids.shirt})" in text
    assert 'Outfits they DISLIKED:\n- Loud: Oxford shirt' in text and 'their note: "too much red"' in text
    assert f"saved themselves:\n- My Sunday: Peacoat (#{ids.coat})" in text

    # clicking the chosen button again clears it; forgetting clears everything
    client.post(f"/suggestions/{liked.id}/verdict", data={"verdict": ""})
    assert _suggestions()[0].verdict == ""
    assert "1 disliked" in client.get("/settings").text
    r = client.post("/stylist/forget", follow_redirects=False)
    assert r.headers["location"] == "/settings?forgot=1#stylist"
    assert all(s.verdict == "" and s.note == "" for s in _suggestions())
    assert "forgot your likes" in client.get("/settings?forgot=1").text


def test_errors_are_explained(client, gemini):
    _closet(client)
    gemini.status = 429
    assert "free Gemini limit is used up" in _ask(client).text
    gemini.status = 403
    assert "refused the API key" in _ask(client).text
    gemini.status = 500
    r = client.post("/stylist", data={"occasion": "x"})  # without htmx: the page, with the error
    assert r.status_code == 422 and "having trouble" in r.text and 'value="x"' in r.text
    gemini.status = 200
    gemini.raw = {"promptFeedback": {"blockReason": "SAFETY"}}
    assert "gave no answer (SAFETY)" in _ask(client).text
    gemini.raw = {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
    assert "couldn" in _ask(client).text
    gemini.raw = None
    gemini.reply = {"outfits": [{"title": "Nope", "item_ids": [999], "reason": ""}]}
    assert "didn" in _ask(client).text and _suggestions() == []


def test_daily_picks_are_made_once_a_day(client, gemini):
    ids = _closet(client)
    gemini.reply = {"outfits": [{"title": "Easy Sunday", "item_ids": [ids.shirt, ids.fit], "reason": "Relaxed."}]}
    assert 'hx-get="/picks"' in client.get("/").text  # loaded after the page
    r = client.get("/picks")
    assert "Easy Sunday" in r.text and "Relaxed." in r.text and "Ask again" in r.text
    assert len(re.findall(r'class="pick">', r.text)) == 2
    assert "Pick their outfit for today" in gemini.calls[0].text
    assert "Easy Sunday" in client.get("/picks").text and len(gemini.calls) == 1  # kept all day

    gemini.reply = {"outfits": [{"title": "Sharp", "item_ids": [ids.coat, ids.shirt], "reason": "Crisp."}]}
    r = client.post("/picks/again")
    assert "Sharp" in r.text and "Recent picks of the day" in gemini.calls[1].text
    daily = [s for s in _suggestions() if s.source == "daily"]
    assert [(s.title, s.replaced) for s in daily] == [("Easy Sunday", True), ("Sharp", False)]

    r = client.post(f"/suggestions/{daily[1].id}/verdict", data={"verdict": "like", "where": "picks"},
                    headers={"HX-Request": "true"})
    assert r.text.lstrip().startswith('<div id="picks">') and 'aria-pressed="true"' in r.text

    gemini.status = 429  # asking again fails: today's outfit stays, with the reason
    r = client.post("/picks/again")
    assert "Sharp" in r.text and "limit is used up" in r.text


def test_daily_picks_fall_back_to_random(client, gemini):
    _closet(client)
    gemini.status = 503
    r = client.get("/picks")
    assert "having trouble" in r.text and "random picks instead" in r.text
    assert len(re.findall(r'class="pick">', r.text)) == 3


def test_save_suggestion_and_open_in_studio(client, gemini):
    ids = _closet(client)
    gemini.reply = {"outfits": [{"title": "Navy dinner", "item_ids": [ids.coat, ids.shirt, ids.fit],
                                 "reason": "Navy and red."}]}
    _ask(client)
    (s,) = _suggestions()
    data = json.loads(re.search(r'<script id="studio-data" type="application/json">(.*?)</script>',
                                client.get(f"/studio?suggestion={s.id}").text, re.S).group(1))
    assert [p["item_id"] for p in data["board"]] == [ids.coat, ids.shirt, ids.fit]
    r = client.post(f"/suggestions/{s.id}/save", follow_redirects=False)
    outfit_id = int(re.search(r"/outfits/(\d+)", r.headers["location"]).group(1))
    with Session(get_engine()) as session:
        o = outfits.get_outfit(session, outfit_id)
        assert (o.name, o.notes, o.source, len(o.links)) == ("Navy dinner", "Navy and red.", "ai", 3)
    assert "Saved ✓" in client.get("/stylist").text
    # outfits the stylist made don't count as the user's own picks
    _ask(client)
    assert "saved themselves" not in gemini.calls[-1].text
    client.post(f"/outfits/{outfit_id}/delete")
    assert _suggestions()[0].outfit_id is None


def test_settings_save_style_and_photo_switch(client):
    r = client.post("/settings/stylist", data={"style": "  Navy,\n\n earth tones  "}, follow_redirects=False)
    assert r.headers["location"] == "/settings?saved=1#stylist"
    p = prefs.get()
    assert p.style == "Navy,\nearth tones" and not p.send_photos
    client.post("/settings/stylist", data={"style": "", "stylist_photos": "on"})
    assert prefs.get().send_photos and prefs.get().style == ""


def test_auto_board_fits_the_board():
    for n in range(1, 9):
        items = [SimpleNamespace(id=i) for i in range(n)]
        board = outfits.auto_board(items)
        assert [b["item_id"] for b in board] == list(range(n))
        for b in board:
            assert 0 <= b["x"] and b["x"] + b["w"] <= 1.0 and 0 <= b["y"] < 1
            assert b["y"] + b["w"] * 0.94 <= 1.0 + 1e-6


def test_migration_0008(tmp_path, monkeypatch):
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
    command.upgrade(cfg, "head")
    con = sqlite3.connect(str(get_settings().db_path))
    con.execute("INSERT INTO suggestion (created_at, title, item_ids) VALUES ('2026-10-25', 'A', '1,2')")
    con.commit()
    assert con.execute("SELECT source, verdict, replaced FROM suggestion").fetchone() == ("stylist", "", 0)
    command.downgrade(cfg, "0007")
    assert con.execute("SELECT name FROM sqlite_master WHERE name = 'suggestion'").fetchone() is None
    con.close()
    reset_engine()
    get_settings.cache_clear()


def test_notes_are_saved_not_shown_and_remembered(client, gemini):
    ids = _closet(client)
    gemini.reply = {"outfits": [{"title": "A", "item_ids": [ids.coat], "reason": "."}]}
    assert "Tell your stylist" in client.get("/stylist").text
    r = client.post("/stylist/notes", data={"text": "  no   shorts, ever "}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and 'id="notes"' in r.text and "Saved." in r.text
    assert "no shorts" not in r.text  # notes are never listed
    client.post("/stylist/notes", data={"text": "more earth tones"}, headers={"HX-Request": "true"})
    r = client.post("/stylist/notes", data={"text": "   "}, headers={"HX-Request": "true"})
    assert "Saved." not in r.text  # empty: ignored
    r = client.post("/stylist/notes", data={"text": "x"}, follow_redirects=False)
    assert r.headers["location"] == "/stylist#notes"
    assert "earth tones" not in client.get("/stylist").text
    _ask(client)
    text = gemini.calls[-1].text
    assert 'told you directly (newest first; follow these):\n- "x"\n- "more earth tones"\n- "no shorts, ever"' in text
    client.post("/stylist/forget")  # forgetting likes keeps the notes
    _ask(client)
    assert "more earth tones" in gemini.calls[-1].text


def test_migration_0009(tmp_path, monkeypatch):
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
    command.upgrade(cfg, "head")
    con = sqlite3.connect(str(get_settings().db_path))
    con.execute("INSERT INTO stylist_note (created_at, text) VALUES ('2026-10-25', 'no shorts')")
    con.commit()
    command.downgrade(cfg, "0008")
    assert con.execute("SELECT name FROM sqlite_master WHERE name = 'stylist_note'").fetchone() is None
    assert con.execute("SELECT name FROM sqlite_master WHERE name = 'suggestion'").fetchone()
    con.close()
    reset_engine()
    get_settings.cache_clear()


def test_dislike_removes_the_card_with_optional_feedback_and_undo(client, gemini):
    ids = _closet(client)
    gemini.reply = {"outfits": [{"title": "Keep me", "item_ids": [ids.coat], "reason": "."},
                                {"title": "Too loud", "item_ids": [ids.shirt], "reason": "."}]}
    _ask(client)
    keep, loud = _suggestions()
    hx = {"HX-Request": "true"}
    r = client.post(f"/suggestions/{loud.id}/verdict", data={"verdict": "dislike"}, headers=hx)
    assert "Removed:" in r.text and "Too loud" in r.text and "What didn" in r.text and "Undo" in r.text
    page = client.get("/stylist").text
    assert "Keep me" in page and "Too loud" not in page

    r = client.post(f"/suggestions/{loud.id}/verdict", data={"verdict": "dislike", "note": "too red"}, headers=hx)
    assert "keep that in mind" in r.text and "What didn" not in r.text
    assert _suggestions()[1].note == "too red"

    r = client.post(f"/suggestions/{loud.id}/verdict", data={"verdict": ""}, headers=hx)  # undo
    assert "Save as outfit" in r.text and "Removed:" not in r.text
    assert "Too loud" in client.get("/stylist").text and _suggestions()[1].note == ""

    # a like keeps the card in place
    r = client.post(f"/suggestions/{keep.id}/verdict", data={"verdict": "like"}, headers=hx)
    assert "Save as outfit" in r.text
