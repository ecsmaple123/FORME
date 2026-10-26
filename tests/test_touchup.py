"""Touch-ups: a hand-edited mask and white balance rebuild the cutout."""
import io

from PIL import Image

from app import ops
from app.services import images

from .test_cutouts import NAVY, _batch, _create, _photos


def _png(im):
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _mask(settings, photo):
    with Image.open(images.mask_path(settings.images_dir, photo.image_file)) as m:
        return m.convert("L")


def _post(client, item_id, photo, mask_png, white_balance=""):
    return client.post(f"/items/{item_id}/photos/{photo.id}/touchup",
                       files={"mask": ("mask.png", mask_png, "image/png")},
                       data={"white_balance": white_balance})


def _cutout(settings, photo):
    with Image.open(images.cutout_paths(settings.images_dir, photo.cutout_file)["display"]) as im:
        return im.convert("RGBA")


def test_erasing_part_rebuilds_the_cutout(client, settings):
    item_id = _create(client)
    _batch()
    (photo,), _ = _photos(item_id)
    r = client.get(f"/items/{item_id}")
    assert f"/items/{item_id}/photos/{photo.id}/touchup" in r.text
    r = client.get(f"/items/{item_id}/photos/{photo.id}/touchup")
    assert r.status_code == 200 and "/static/touchup.js" in r.text
    assert f"/media/mask/{photo.image_file}.png" in r.text
    before = _cutout(settings, photo).size
    mask = _mask(settings, photo)
    box = mask.getbbox()
    mask.paste(0, (box[0], box[1], box[2], (box[1] + box[3]) // 2))   # erase the top half
    r = _post(client, item_id, photo, _png(mask))
    assert r.status_code == 200 and r.json()["url"] == f"/items/{item_id}?photo={photo.id}"
    old_files = images.cutout_paths(settings.images_dir, photo.cutout_file)
    (photo,), _ = _photos(item_id)
    assert photo.touched_up and photo.cutout_status == "done"
    assert not old_files["display"].exists()
    after = _cutout(settings, photo).size
    assert after[1] < before[1] * 0.7 and after[0] <= before[0]
    assert _mask(settings, photo).getbbox()[1] > box[1]   # the edited mask is stored
    assert ops.requeue_cutouts(everything=True) == 0       # hand edits are never redone


def test_white_balance_changes_colors(client, settings):
    item_id = _create(client)
    _batch()
    (photo,), item = _photos(item_id)
    assert item.color_name == "Navy"
    r = _post(client, item_id, photo, _png(_mask(settings, photo)), "2.000,1.000,0.500")
    assert r.status_code == 200
    (photo,), item = _photos(item_id)
    assert photo.white_balance == "2.000,1.000,0.500"
    cut = _cutout(settings, photo)
    r_, g_, b_, a_ = cut.getpixel((cut.width // 2, cut.height // 2))
    assert a_ == 255 and r_ > NAVY[0] * 1.6 and b_ < NAVY[2] * 0.7
    assert item.color_hex == item.colors[0].hex != "#1d2645"   # automatic color follows


def test_bad_touchups_are_refused(client, settings):
    item_id = _create(client)
    _batch()
    (photo,), _ = _photos(item_id)
    mask = _mask(settings, photo)
    r = _post(client, item_id, photo, _png(Image.new("L", (10, 10), 255)))
    assert r.status_code == 422 and "match the photo" in r.json()["error"]
    r = _post(client, item_id, photo, _png(Image.new("L", mask.size, 0)))
    assert r.status_code == 422 and "Nothing of the item" in r.json()["error"]
    r = _post(client, item_id, photo, _png(mask), "9,9,9")
    assert r.status_code == 422 and "lighting" in r.json()["error"]
    r = _post(client, item_id, photo, b"not a png")
    assert r.status_code == 422
    assert not _photos(item_id)[0][0].touched_up


def test_older_photo_without_original_is_promoted(client, settings):
    item_id = _create(client)
    _batch()
    (photo,), _ = _photos(item_id)
    images.delete_files(settings.images_dir, photo.image_file, photo.image_ext)  # cut out before 0010
    cut = _cutout(settings, photo)
    r = client.get(f"/items/{item_id}/photos/{photo.id}/touchup")
    assert r.status_code == 200
    (photo,), _ = _photos(item_id)
    display = images.paths(settings.images_dir, photo.image_file)["display"]
    with Image.open(display) as d:
        assert d.size == cut.size
    assert _mask(settings, photo).size == cut.size
    r = _post(client, item_id, photo, _png(_mask(settings, photo)))
    assert r.status_code == 200


def test_fit_pictures_and_pending_photos_cannot_be_touched_up(client):
    fit_id = _create(client, kind="fit")
    (fit,), _ = _photos(fit_id)
    r = client.get(f"/items/{fit_id}/photos/{fit.id}/touchup")
    assert r.status_code == 409 and "keep their background" in r.text
    item_id = _create(client)
    (photo,), _ = _photos(item_id)
    r = client.get(f"/items/{item_id}/photos/{photo.id}/touchup")
    assert r.status_code == 409 and "still being removed" in r.text


def test_no_subject_photo_can_be_drawn_by_hand(client, settings):
    item_id = _create(client)
    _batch(lambda rgb: Image.new("L", rgb.size, 0))
    (photo,), _ = _photos(item_id)
    assert photo.cutout_status == "none"
    assert client.get(f"/items/{item_id}/photos/{photo.id}/touchup").status_code == 200
    mask = Image.new("L", _mask(settings, photo).size, 0)
    mask.paste(255, (100, 100, 400, 600))
    assert _post(client, item_id, photo, _png(mask)).status_code == 200
    (photo,), _ = _photos(item_id)
    assert photo.cutout_status == "done" and _cutout(settings, photo).size[0] < 400
