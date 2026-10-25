"""Background removal: the worker's bookkeeping, display switching, cleanup and the 0003 migration.

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


def _create(client, colors=(NAVY,)):
    r = client.post("/add/photo", files=[("photo", ("p.jpg", make_image(garment=c), "image/jpeg"))
                                         for c in colors])
    tokens = re.findall(r'name="image_token" value="([0-9a-f]{32})"', r.text)
    r = client.post("/items", data={"image_token": tokens, "photo_kind": ["product"] * len(tokens),
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

    r = client.get(f"/items/{item_id}")
    assert f"/media/cutout/{photo.cutout_file}.webp" in r.text and "Show with background" in r.text
    assert client.get(f"/media/cutout/{photo.cutout_file}.thumb.webp").status_code == 200
    grid = client.get("/closet", headers={"HX-Request": "true"})
    assert f"/media/cutout/{photo.cutout_file}.thumb.webp" in grid.text
    # colors now come from the garment only
    from app.services.colors import nearest_color_name
    assert nearest_color_name(item.colors[0].hex) == "navy" and item.colors[0].share > 0.8
    assert not any(nearest_color_name(c.hex) == "white" for c in item.colors)

    r = client.get(f"/items/{item_id}/photos/{photo.id}/cutout")
    assert r.headers.get("HX-Refresh") == "true"


def test_switch_back_to_original(client):
    item_id = _create(client)
    _batch()
    (photo,), _ = _photos(item_id)
    client.post(f"/items/{item_id}/photos/{photo.id}/cutout", data={"show": "0"})
    (photo,), _ = _photos(item_id)
    assert not photo.show_cutout and photo.cutout_shown is None
    r = client.get(f"/items/{item_id}")
    assert f"/media/display/{photo.image_file}.jpg" in r.text and "Remove background" in r.text
    client.post(f"/items/{item_id}/photos/{photo.id}/cutout", data={"show": "1"})
    assert _photos(item_id)[0][0].cutout_shown


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


def test_redo_replaces_old_cutout(client, settings):
    item_id = _create(client)
    _batch()
    (photo,), _ = _photos(item_id)
    old = images.cutout_paths(settings.images_dir, photo.cutout_file)
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


def test_requeue_and_rebuild(client, settings):
    item_id = _create(client)
    _batch(lambda rgb: Image.new("L", rgb.size, 0))
    assert ops.requeue_cutouts() == 1
    _batch()
    (photo,), _ = _photos(item_id)
    assert "1 done" in ops.cutout_summary()
    # after a restore the cutout files are gone: rebuild queues the photo again
    images.delete_files(settings.images_dir, "", "", cutout=photo.cutout_file)
    ops.rebuild_images()
    assert _photos(item_id)[0][0].cutout_status == "pending"
    assert ops.requeue_cutouts(everything=True) == 1


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
    assert con.execute("SELECT cutout_status, show_cutout FROM item_photo").fetchall() == [("pending", 1)]
    command.downgrade(cfg, "0002")
    assert "cutout_status" not in [r[1] for r in con.execute("PRAGMA table_info(item_photo)")]
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
