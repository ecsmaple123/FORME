"""Floor patches: trousers laid flat on a floor, where the model keeps the floor between the legs."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from app.services import cutout  # noqa: E402

KHAKI, DARK_BROWN, NAVY, WHITE_BAG = (177, 152, 124), (63, 51, 50), (26, 33, 44), (205, 205, 200)


def _scene(item, floor, seed=0):
    """Trousers (waist + two legs with a widening gap) on a textured floor, and a model output
    that wrongly covers the gap too."""
    rng = np.random.default_rng(seed)
    h, w = 600, 450
    img = np.clip(np.array(floor, float) + rng.normal(0, 12, (h, w, 3)), 0, 255)
    ys, xs = np.mgrid[0:h, 0:w]
    half_gap = np.clip((ys - 200) * 0.18, 0, None)
    trousers = (xs >= 110) & (xs <= 340) & (ys >= 60) & (ys <= 540)
    gap = trousers & (ys > 200) & (np.abs(xs - 225) < half_gap)
    legs = trousers & ~gap
    img[legs] = np.clip(np.array(item, float) + rng.normal(0, 8, (legs.sum(), 3)), 0, 255)
    mask = np.where(trousers, 0.97, 0.02).astype(np.float32)
    return img.astype(np.uint8), mask, gap, legs


def _inside(region):
    return cv2.erode(region.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)


@pytest.mark.parametrize("item, floor", [(KHAKI, DARK_BROWN), (NAVY, WHITE_BAG)])
def test_floor_between_the_legs_is_removed(item, floor):
    rgb, mask, gap, legs = _scene(item, floor)
    a = cutout.refine(rgb, mask)
    assert a[_inside(gap)].mean() < 0.1
    assert a[_inside(legs)].mean() > 0.95


def test_item_the_color_of_the_floor_is_left_alone():
    rgb, mask, gap, legs = _scene(KHAKI, (170, 148, 126))
    a = cutout.refine(rgb, mask)
    assert a[_inside(legs)].mean() > 0.95


def test_small_floor_colored_details_stay():
    rgb, mask, gap, legs = _scene(KHAKI, DARK_BROWN)
    rgb[300:310, 140:150] = DARK_BROWN            # a small dark label on the leg
    mask[:] = np.where(legs | gap, 0.97, 0.02)
    a = cutout.refine(rgb, mask)
    assert a[302:308, 142:148].mean() > 0.9
