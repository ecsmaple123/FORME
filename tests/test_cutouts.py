"""Background removal: the worker's bookkeeping, fit pictures, cleanup and the 0003/0006 migrations.

The model itself needs OpenCV + system libraries; a Pillow-only fake segmenter stands in for it
(the real one is exercised by test_real_model_cuts_out_garment when available).
"""
import re
import sqlite3

import pytest
from PIL import Image
from sqlmodel import Session

from app import ops, worker
from app.db import get_engine
from app.models import Item, ItemPhoto
from app.services import images

from .conftest import make_image

NAVY, RED = (29, 38, 69), (198, 42, 42)


def fake_segment(rgb: Image.Image) -> Image.Image:
    """Everything that isn't (near) white is the subject."""
    return rgb.convert("L").point(lambda v: 255 if v < 240 else 0)


def _create(client, colors=(NAVY,), kind="product"):
    r = client.post("/add/photo", files=[("photo", ("p.jpg", make_image(garment=c), "image/jpeg"))
                                         for c in colors])
    tokens = re.findall(r'name="image_token" value="([0-9a-f]{32})"', r.text)
    r = client.post("/items", data={"image_token": tokens, "photo_kind": [kind] * len(tokens),
                                    "name": "Coat", "category_id": "1"}, follow_redirects=False)
    return int(r.headers["location"].rsplit("/", 1)[1])


def _photos(item_id):
    with Session(get_engine()) as s:
        item = s.get(Item, item_id)
        _ = item.colors
        return list(item.photos), item


def _batch(segment=fake_segment):
    return worker.run_batch(lambda: segment)


def test_new_photo_is_cut_out_and_shown(client, settings):
    item_id = _create(client)
    (photo,), _ = _photos(item_id)
    assert photo.cutout_status == "pending" and photo.cutout_shown is None
    r = client.get(f"/items/{item_id}")
    assert "Removing background" in r.text and 'hx-trigger="every 4s"' in r.text

    assert _batch() == 0
    (photo,), item = _photos(item_id)
    assert photo.cutout_status == "done" and photo.cutout_shown == photo.cutout_file
    files = images.cutout_paths(settings.images_dir, photo.cutout_file)
    with Image.open(files["display"]) as cut:
        # cropped to the garment block (600x900 of 1200x1500) plus a 3% margin, with transparency
        assert cut.mode == "RGBA" and cut.size[0] < 700 and cut.size[1] < 1000
        assert cut.getpixel((0, 0))[3] == 0 and cut.getpixel((cut.width // 2, cut.height // 2))[3] == 255
    assert files["thumb"].is_file()
    # the photo with its background is not kept
    assert not any(f.exists() for f in images.paths(settings.images_dir, photo.image_file,
                                                     photo.image_ext).values())

    r = client.get(f"/items/{item_id}")
    assert f'href="/media/cutout/{photo.cutout_file}.webp"' in r.text
    assert "/media/orig/" not in r.text and "/media/display/" not in r.text
    assert "Show with background" not in r.text and "Remove background" not in r.text
    assert client.get(f"/media/cutout/{photo.cutout_file}.thumb.webp").status_code == 200
    grid = client.get("/closet", headers={"HX-Request": "true"})
    assert f"/media/cutout/{photo.cutout_file}.thumb.webp" in grid.text
    # colors now come from the garment only
    from app.services.colors import nearest_color_name
    assert nearest_color_name(item.colors[0].hex) == "Navy" and item.colors[0].share > 0.8
    assert not any(nearest_color_name(c.hex) == "White" for c in item.colors)

    r = client.get(f"/items/{item_id}/photos/{photo.id}/cutout")
    assert r.headers.get("HX-Refresh") == "true"


def test_item_color_follows_cover_until_edited(client):
    from app.services.colors import nearest_color_name

    r = client.post("/add/photo", files=[("photo", ("p.jpg", make_image(garment=c), "image/jpeg"))
                                         for c in (NAVY, RED)])
    assert "swatch" not in r.text
    tokens = re.findall(r'name="image_token" value="([0-9a-f]{32})"', r.text)
    prefilled = {k: re.search(rf'name="{k}" value="([^"]*)"', r.text).group(1)
                 for k in ("color_hex", "color_name")}
    r = client.post("/items", data={"image_token": tokens, "photo_kind": ["product"] * 2,
                                    "name": "Coat", "category_id": "1", **prefilled},
                    follow_redirects=False)
    item_id = int(r.headers["location"].rsplit("/", 1)[1])
    _batch()
    photos, item = _photos(item_id)
    assert item.color_hex == item.colors[0].hex and item.color_name == "Navy"  # from the cutout
    assert "swatch" not in client.get(f"/items/{item_id}").text
    client.post(f"/items/{item_id}/photos/{photos[1].id}/cover")
    assert nearest_color_name(_photos(item_id)[1].color_hex) == "Red"  # still automatic

    client.post(f"/items/{item_id}/edit", data={"name": "Coat", "category_id": "1",
                                                 "color_hex": "#00aa00", "color_name": ""})
    client.post(f"/items/{item_id}/photos/{photos[0].id}/cover")
    _, item = _photos(item_id)
    assert item.color_hex == "#00aa00" and nearest_color_name(item.colors[0].hex) == "Navy"


def test_fit_picture_keeps_background(client, settings):
    item_id = _create(client, kind="fit")
    (photo,), _ = _photos(item_id)
    assert photo.kind == "fit" and photo.cutout_status == "skip"
    assert not worker.has_pending(settings.db_path)
    assert _batch() == 0
    (photo,), _ = _photos(item_id)
    assert photo.cutout_status == "skip" and photo.cutout_shown is None
    assert all(f.exists() for f in images.paths(settings.images_dir, photo.image_file,
                                                 photo.image_ext).values())
    r = client.get(f"/items/{item_id}")
    assert f"/media/display/{photo.image_file}.jpg" in r.text and "Fit picture" in r.text
    assert "Removing background" not in r.text

    # added to an existing item: a fit picture is skipped, an item photo is queued
    client.post(f"/items/{item_id}/photos", files=[("photo", ("p.jpg", make_image(), "image/jpeg"))],
                data={"kind": "product"})
    assert [p.cutout_status for p in _photos(item_id)[0]] == ["skip", "pending"]


def test_cleanup_drops_backgrounds_of_cut_out_photos(client, settings):
    """Photos cut out before the worker deleted originals lose them at the next cleanup."""
    item_id = _create(client)
    (photo,), _ = _photos(item_id)
    files = images.paths(settings.images_dir, photo.image_file, photo.image_ext)
    keep = {k: f.read_bytes() for k, f in files.items()}
    _batch()
    for k, f in files.items():
        f.write_bytes(keep[k])  # as if cut out by the old worker
    from app.services.library import cleanup_staging
    cleanup_staging()
    assert not any(f.exists() for f in files.values())
    (photo,), _ = _photos(item_id)
    assert images.cutout_paths(settings.images_dir, photo.cutout_file)["display"].is_file()


def test_no_subject_and_failure_then_retry(client):
    first, second = _create(client), _create(client, (RED,))
    calls = []

    def flaky(rgb):
        calls.append(1)
        if len(calls) == 1:
            return Image.new("L", rgb.size, 0)  # nothing found
        raise RuntimeError("model crashed")

    assert _batch(flaky) == 0  # a failing photo doesn't stop the batch
    assert _photos(first)[0][0].cutout_status == "none"
    (photo,), _ = _photos(second)
    assert photo.cutout_status == "failed"
    r = client.get(f"/items/{second}")
    assert "Background removal failed" in r.text and "Try again" in r.text

    client.post(f"/items/{second}/photos/{photo.id}/cutout/retry")
    assert _photos(second)[0][0].cutout_status == "pending"
    _batch()
    assert _photos(second)[0][0].cutout_status == "done"


def _keep_original(settings, photo):
    """Bytes of a photo's files, to put back after the worker deleted them."""
    return {f: f.read_bytes() for f in images.paths(settings.images_dir, photo.image_file,
                                                     photo.image_ext).values()}


def test_redo_replaces_old_cutout(client, settings):
    item_id = _create(client)
    (photo,), _ = _photos(item_id)
    kept = _keep_original(settings, photo)
    _batch()
    (photo,), _ = _photos(item_id)
    old = images.cutout_paths(settings.images_dir, photo.cutout_file)
    assert ops.requeue_cutouts(everything=True) == 0  # the original is gone: nothing to redo from
    for f, data in kept.items():
        f.write_bytes(data)
    assert ops.requeue_cutouts(everything=True) == 1
    assert _batch() == 0
    (photo,), _ = _photos(item_id)
    assert photo.cutout_status == "done" and not old["display"].exists() and not old["thumb"].exists()
    assert images.cutout_paths(settings.images_dir, photo.cutout_file)["display"].is_file()


def test_whole_frame_subject_is_none(client):
    item_id = _create(client)
    _batch(lambda rgb: Image.new("L", rgb.size, 255))  # e.g. a fabric close-up
    assert _photos(item_id)[0][0].cutout_status == "none"


def test_deleting_removes_cutout_files(client, settings):
    item_id = _create(client, (NAVY, RED))
    _batch()
    photos, _ = _photos(item_id)
    cut_files = [f for p in photos for f in images.cutout_paths(settings.images_dir, p.cutout_file).values()]
    assert all(f.is_file() for f in cut_files)
    client.post(f"/items/{item_id}/photos/{photos[1].id}/delete")
    assert not any(f.exists() for f in cut_files[2:]) and all(f.exists() for f in cut_files[:2])
    client.post(f"/items/{item_id}/delete")
    assert not any(f.exists() for f in cut_files)


def test_photo_deleted_while_processing(client, settings):
    item_id = _create(client)
    (photo,), _ = _photos(item_id)

    def delete_meanwhile(rgb):
        client.post(f"/items/{item_id}/delete")
        return fake_segment(rgb)

    assert worker.process_photo(photo.id, delete_meanwhile) is None
    assert list((settings.images_dir / "cutout").iterdir()) == []


def test_unavailable_model_leaves_photos_pending(client):
    item_id = _create(client)

    def missing():
        raise ImportError("libcblas.so.3: cannot open shared object file")

    assert worker.run_batch(missing) == worker.EXIT_UNAVAILABLE
    assert _photos(item_id)[0][0].cutout_status == "pending"
    assert worker.has_pending(get_engine().url.database)


def test_requeue_and_rebuild(client, settings, capsys):
    item_id = _create(client)
    (photo,), _ = _photos(item_id)
    kept = _keep_original(settings, photo)
    _batch(lambda rgb: Image.new("L", rgb.size, 0))
    assert ops.requeue_cutouts() == 1
    _batch()
    (photo,), _ = _photos(item_id)
    assert "1 done" in ops.cutout_summary()
    # cutout files gone (an old backup) but the original back: rebuild queues the photo again
    images.delete_files(settings.images_dir, "", "", cutout=photo.cutout_file)
    for f, data in kept.items():
        f.write_bytes(data)
    ops.rebuild_images()
    assert _photos(item_id)[0][0].cutout_status == "pending"
    # with neither the original nor the cutout there is nothing to rebuild from
    _batch()
    (photo,), _ = _photos(item_id)
    images.delete_files(settings.images_dir, "", "", cutout=photo.cutout_file)
    capsys.readouterr()
    ops.rebuild_images()
    assert _photos(item_id)[0][0].cutout_status == "done"
    assert "neither its original nor a cutout" in capsys.readouterr().out


def test_backup_keeps_cutouts(client, settings, capsys):
    """After the background is removed the cutout is the only copy, so backups must hold it."""
    item_id = _create(client)
    fit_id = _create(client, (RED,), kind="fit")
    _batch()
    (photo,), _ = _photos(item_id)
    archive = ops.backup()
    client.post(f"/items/{item_id}/delete")
    client.post(f"/items/{fit_id}/delete")
    ops.restore(str(archive))
    (photo,), _ = _photos(item_id)
    assert photo.cutout_status == "done"
    assert images.cutout_paths(settings.images_dir, photo.cutout_file)["display"].is_file()
    (fit,), _ = _photos(fit_id)
    assert all(f.is_file() for f in images.paths(settings.images_dir, fit.image_file,
                                                 fit.image_ext).values())
    assert "warning" not in capsys.readouterr().out


def test_cleanup_keeps_cutouts_in_use(client, settings):
    item_id = _create(client)
    _batch()
    (photo,), _ = _photos(item_id)
    stray = settings.images_dir / "cutout" / ("0" * 32 + ".thumb.webp")
    stray.write_bytes(b"x")
    from app.services import library
    library.cleanup_staging(max_age=-1)
    assert not stray.exists()
    assert images.cutout_paths(settings.images_dir, photo.cutout_file)["thumb"].is_file()


def test_migration_0003_queues_existing_photos(tmp_path, monkeypatch):
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
    command.upgrade(cfg, "0002")
    db = str(get_settings().db_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO item (id, name, category_id, created_at, updated_at) "
                "VALUES (3, 'Jumper', 1, '2026-10-24', '2026-10-24')")
    con.execute("INSERT INTO item_photo (item_id, position, kind, image_file, image_ext, created_at) "
                "VALUES (3, 0, 'product', 'abc', 'jpg', '2026-10-24')")
    con.commit()
    command.upgrade(cfg, "head")
    assert con.execute("SELECT cutout_status FROM item_photo").fetchall() == [("pending",)]
    command.downgrade(cfg, "0002")
    assert "cutout_status" not in [r[1] for r in con.execute("PRAGMA table_info(item_photo)")]
    con.close()
    reset_engine()
    get_settings.cache_clear()


def test_migration_0006_fit_pictures(tmp_path, monkeypatch):
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
    command.upgrade(cfg, "0005")
    con = sqlite3.connect(str(get_settings().db_path))
    con.execute("INSERT INTO item (id, name, category_id, created_at, updated_at) "
                "VALUES (3, 'Jumper', 1, '2026-10-24', '2026-10-24')")
    for pos, kind, status in ((0, "product", "done"), (1, "real", "done"), (2, "detail", "none"),
                              (3, "other", "pending")):
        con.execute("INSERT INTO item_photo (item_id, position, kind, image_file, image_ext, "
                    "cutout_status, cutout_file, show_cutout, created_at) "
                    "VALUES (3, ?, ?, 'abc', 'jpg', ?, 'cut', 0, '2026-10-24')", (pos, kind, status))
    con.commit()
    command.upgrade(cfg, "head")
    rows = con.execute("SELECT kind, cutout_status, cutout_file FROM item_photo ORDER BY position")
    assert rows.fetchall() == [("product", "done", "cut"), ("fit", "skip", None),
                               ("product", "none", "cut"), ("product", "pending", "cut")]
    assert "show_cutout" not in [r[1] for r in con.execute("PRAGMA table_info(item_photo)")]
    command.downgrade(cfg, "0005")
    assert con.execute("SELECT kind, cutout_status FROM item_photo WHERE position = 1").fetchone()         == ("real", "none")
    con.close()
    reset_engine()
    get_settings.cache_clear()


def test_real_model_cuts_out_garment():
    """Needs OpenCV, its system libraries and models/u2netp.onnx (skipped otherwise)."""
    cutout = pytest.importorskip("app.services.cutout", exc_type=ImportError)
    if not cutout.MODEL_PATH.is_file():
        pytest.skip("model not downloaded")
    import io
    rgb = Image.open(io.BytesIO(make_image(size=(600, 750)))).convert("RGB")
    seg = cutout.Segmenter()
    alpha = seg(rgb)
    box = images.subject_box(alpha)
    assert box is not None
    # the garment block is x 150-450, y 150-600
    assert abs(box[0] - 150) < 40 and abs(box[2] - 450) < 40
    assert alpha.getpixel((300, 375)) == 255 and alpha.getpixel((20, 20)) == 0
    # the fused (sharp) output, not a coarse side output: the raw edge rises within a few pixels
    import numpy as np
    raw = seg.predict(np.asarray(rgb))
    row = raw[375]
    assert row[130] < 0.2 and row[170] > 0.8, (row[130], row[170])


def test_webp_served_as_image(client):
    item_id = _create(client)
    _batch()
    (photo,), _ = _photos(item_id)
    r = client.get(f"/media/cutout/{photo.cutout_file}.thumb.webp")
    assert r.headers["content-type"] == "image/webp"
