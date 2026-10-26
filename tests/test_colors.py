from PIL import Image

from app.services import colors, images
from app.services.library import recolor_all
from tests.test_items import _create, _item

NAVY = (29, 38, 69)


def _garment(*parts):
    """A cutout (RGBA): vertical bands of the given colors on a transparent canvas."""
    im = Image.new("RGBA", (90, 90), (0, 0, 0, 0))
    width = 70 // len(parts)
    for n, rgb in enumerate(parts):
        im.paste(rgb + (255,), (10 + n * width, 10, 10 + (n + 1) * width, 80))
    return im


def test_shadows_do_not_darken_the_color():
    shade = tuple(int(v * 0.45) for v in NAVY)
    found = images.dominant_colors(_garment(NAVY, NAVY, shade))
    main = colors.hex_to_rgb(found[0].hex)
    assert found[0].share > 0.9                               # lit and shaded parts are one color
    assert colors.color_distance(main, NAVY) < 12             # and it reads as the lit navy
    assert colors.nearest_color_name(found[0].hex) == "Navy"


def test_two_colors_stay_two():
    found = images.dominant_colors(_garment((17, 17, 17), (240, 240, 240)))
    assert len(found) == 2 and {colors.nearest_color_name(c.hex) for c in found} == {"Black", "White"}


def test_dark_shades_have_names():
    assert colors.nearest_color_name("#1a212c") == "Dark Navy"
    assert colors.nearest_color_name("#494234") == "Dark Olive"


def test_recolor_all_keeps_edited_colors(client):
    auto_id = _create(client)
    edited_id = _create(client, name="Painted")
    r = client.post(f"/items/{edited_id}/edit", data={"name": "Painted", "category_id": "1",
                                                     "color_hex": "#00aa00", "color_name": "Grass"})
    assert r.status_code in (200, 303)
    recolor_all()
    auto, edited = _item(auto_id), _item(edited_id)
    assert auto.color_hex == auto.colors[0].hex and auto.color_name == "Navy"
    assert (edited.color_hex, edited.color_name) == ("#00aa00", "Grass")


def test_pick_from_photo_on_the_form(client):
    item_id = _create(client)
    r = client.get(f"/items/{item_id}/edit")
    assert "id=\"color-from-photo\"" in r.text and "/static/colorpick.js" in r.text
    assert "id=\"form-photo\"" in r.text
