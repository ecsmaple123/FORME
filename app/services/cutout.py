"""Background removal: a subject mask for a photo, from the U^2-Net-p model (models/u2netp.onnx,
Apache-2.0, distributed by the rembg project) run with OpenCV's DNN module.

Only the cutout batch process imports this (python -m app cutout-batch): numpy + OpenCV + the model
need ~285 MB while it runs, which the web app must not carry. armhf OpenCV has no NEON build, so
one photo takes ~10 s on the Pi 4.

The model sees the photo at 320x320. The mask is then refined at full size:
  1. guided filter: snaps the soft, low-res mask to the real edges in the photo
  2. contrast curve: mostly solid or clear, so no haze/halo of the old background
  3. backdrop cleanup (product shots with an even backdrop only): where the model is unsure,
     pixels of the backdrop's color become clear, e.g. the gap between a sleeve and the body
  4. hole filling: unsure areas enclosed by the subject (e.g. a coat's shiny lining) become solid;
     real gaps (mask ~0, or backdrop-colored) stay transparent
  4b. floor patches (photos on a floor, bed or table, i.e. no even backdrop): large areas the model
     kept that are clearly the floor's colors rather than the item's are removed, e.g. the floor
     between the legs of trousers laid flat
  5. a 1-3 px trim of the edge, which removes the last light fringe, and removal of tiny specks
"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ..config import PROJECT_DIR

MODEL_PATH = PROJECT_DIR / "models" / "u2netp.onnx"
SIZE = 320
MEAN = np.array((0.485, 0.456, 0.406), np.float32)
STD = np.array((0.229, 0.224, 0.225), np.float32)


def _guided_filter(guide: np.ndarray, src: np.ndarray, radius: int, eps: float) -> np.ndarray:
    """He et al.'s guided filter with a grayscale guide; both float32 in [0, 1]."""
    def box(x):
        return cv2.boxFilter(x, -1, (radius, radius))

    mean_i, mean_p = box(guide), box(src)
    a = (box(guide * src) - mean_i * mean_p) / (box(guide * guide) - mean_i * mean_i + eps)
    b = mean_p - a * mean_i
    return box(a) * guide + box(b)


def _curve(a: np.ndarray, low: float, high: float) -> np.ndarray:
    return np.clip((a - low) / (high - low), 0, 1)


def backdrop_color(rgb: np.ndarray):
    """The plain backdrop of a product shot (median border color), or None if the border isn't
    one even color (a real photo, a busy background)."""
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]).astype(np.float32)
    med = np.median(border, axis=0)
    even = np.linalg.norm(border - med, axis=1) < BACKDROP_TOLERANCE
    return med if even.mean() > 0.6 else None


BACKDROP_TOLERANCE = 12   # border pixels this close to the median count as backdrop
BACKDROP_CLEAR = 14       # unsure pixels closer than this to the backdrop color become clear...
BACKDROP_KEEP = 30        # ...and from this distance on they're kept (soft in between)
CONFIDENT = 0.9           # model output above this is always kept (e.g. white soles on white)
MIN_PART = 0.002          # solid specks smaller than this share of the photo are dropped


FLOOR_SIDE = 400          # floor patches are found on a copy this size (memory, speed)
FLOOR_BAND = 0.04         # the border band (share of the shorter side) that shows the floor
FLOOR_COLORS = 4          # color clusters for the floor and for the item each
FLOOR_MARGIN = 12.0       # Lab distance a pixel must be closer to the floor than to the item
FLOOR_MIN_PATCH = 0.004   # floor-colored areas smaller than this share of the photo stay (shading)
FLOOR_MAX_SHARE = 0.35    # if more of the item than this looks like floor, the colors are too alike


def _clusters(lab: np.ndarray, k: int) -> np.ndarray:
    data = lab[np.random.default_rng(0).permutation(len(lab))[:8000]].astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _c, _l, centers = cv2.kmeans(data, min(k, len(data)), None, criteria, 2, cv2.KMEANS_PP_CENTERS)
    return centers


def _nearest(lab: np.ndarray, centers: np.ndarray) -> np.ndarray:
    return np.min(np.linalg.norm(lab[:, None, :] - centers[None, :, :], axis=2), axis=1)


def floor_patches(rgb: np.ndarray, a: np.ndarray) -> np.ndarray:
    """Full-size bool mask of large kept areas that have the floor's colors, not the item's."""
    h, w = a.shape
    scale = min(1.0, FLOOR_SIDE / max(h, w))
    sw, sh = max(1, round(w * scale)), max(1, round(h * scale))
    lab = cv2.cvtColor(cv2.resize(rgb, (sw, sh), interpolation=cv2.INTER_AREA),
                       cv2.COLOR_RGB2LAB).astype(np.float32)
    small = cv2.resize(a, (sw, sh), interpolation=cv2.INTER_AREA)
    nothing = np.zeros((h, w), bool)
    band = max(2, int(min(sw, sh) * FLOOR_BAND))
    edge = np.zeros((sh, sw), bool)
    edge[:band], edge[-band:], edge[:, :band], edge[:, -band:] = True, True, True, True
    floor = lab[edge & (small < 0.1)]
    kept = small > 0.5
    core = cv2.erode(kept.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    if len(floor) < 200 or core.sum() < 200:
        return nothing
    floor_c, item_c = _clusters(floor, FLOOR_COLORS), _clusters(lab[core], FLOOR_COLORS)
    # what the model kept includes the patches themselves: the item's own colors are the ones
    # unlike any floor color (none left = the item is the floor's color, so leave it alone)
    apart = _nearest(item_c, floor_c)
    item_c, apart = item_c[apart > 2 * FLOOR_MARGIN], apart[apart > 2 * FLOOR_MARGIN]
    # an item color only somewhat unlike the floor (lit olive on a grey-brown floor) means the two
    # can't be told apart reliably: removing patches would eat into the item
    if not len(item_c) or apart.min() < 3 * FLOOR_MARGIN:
        return nothing
    pts = lab[kept]
    like_floor = np.zeros((sh, sw), bool)
    like_floor[kept] = _nearest(pts, floor_c) + FLOOR_MARGIN < _nearest(pts, item_c)
    like_floor = cv2.morphologyEx(like_floor.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, _c = cv2.connectedComponentsWithStats(like_floor, connectivity=8)
    big = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= FLOOR_MIN_PATCH * sw * sh]
    if not big:
        return nothing
    patches = np.isin(labels, big)
    if patches.sum() > FLOOR_MAX_SHARE * kept.sum():
        return nothing
    patches = cv2.dilate(patches.astype(np.uint8), np.ones((3, 3), np.uint8))
    return cv2.resize(patches, (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)


def refine(rgb: np.ndarray, mask: np.ndarray, backdrop_cleanup: bool = True) -> np.ndarray:
    """Full-size soft mask (float32 0..1) -> cleaned alpha (float32 0..1)."""
    h, w = mask.shape
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    radius = max(3, max(h, w) // 160) | 1
    a = _curve(_guided_filter(gray, mask, radius, 1e-3), 0.25, 0.75)

    # Product shots: where the model is unsure, backdrop-colored pixels are backdrop (the gap
    # between sleeve and body, a fringe along the hem). Confident pixels are never touched.
    unlike_backdrop = np.ones_like(a, dtype=bool)
    bg = backdrop_color(rgb) if backdrop_cleanup else None
    if bg is not None:
        dist = np.linalg.norm(rgb.astype(np.float32) - bg, axis=2)
        keep = np.clip((dist - BACKDROP_CLEAR) / (BACKDROP_KEEP - BACKDROP_CLEAR), 0, 1)
        a = np.where(mask < CONFIDENT, a * keep, a)
        unlike_backdrop = dist >= BACKDROP_KEEP

    # pixels not solid and not connected to the border are enclosed by the subject
    open_area = (a <= 0.5).astype(np.uint8)
    _n, labels = cv2.connectedComponents(open_area, connectivity=4)
    edge_labels = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    enclosed = (open_area == 1) & ~np.isin(labels, edge_labels)
    a[enclosed & (mask > 0.08) & unlike_backdrop] = 1.0
    if bg is None and backdrop_cleanup:
        a[floor_patches(rgb, a)] = 0.0

    a = _curve(a, 0.35, 0.75)
    k = max(3, max(h, w) // 500) | 1
    a = cv2.erode(a, np.ones((k, k), np.uint8))

    # drop small leftover specks (both shoes of a pair are kept: each is a large part)
    n, labels, stats, _c = cv2.connectedComponentsWithStats((a > 0.5).astype(np.uint8), connectivity=8)
    small = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] < MIN_PART * h * w]
    if small:
        a[np.isin(labels, small)] = 0
    return a


class Segmenter:
    """Callable: RGB PIL image -> alpha mask ("L", same size). Load once, use for a whole batch."""

    def __init__(self, model_path: Path = MODEL_PATH, threads: int = 4,
                 backdrop_cleanup: bool = True):
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"model missing: {model_path} (./wardrobe.sh start downloads it)")
        cv2.setNumThreads(threads)
        self.net = cv2.dnn.readNetFromONNX(str(model_path))
        # U^2-Net has 7 outputs: the fused mask first, then 6 coarser side outputs. Ask for it by
        # name: a bare forward() returns the *last* layer's output on OpenCV 4.x (a blurry blob).
        self.output = self.net.getUnconnectedOutLayersNames()[0]
        self.backdrop_cleanup = backdrop_cleanup

    def predict(self, rgb: np.ndarray) -> np.ndarray:
        """Raw model output, resized to the photo: float32 0..1."""
        x = cv2.resize(rgb, (SIZE, SIZE), interpolation=cv2.INTER_AREA).astype(np.float32)
        x /= max(float(x.max()), 1e-6)
        x = (x - MEAN) / STD
        self.net.setInput(x.transpose(2, 0, 1)[None])
        out = self.net.forward(self.output)[0, 0]
        out = (out - out.min()) / max(float(out.max() - out.min()), 1e-6)
        return cv2.resize(out, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)

    def __call__(self, im: Image.Image) -> Image.Image:
        rgb = np.asarray(im.convert("RGB"))
        alpha = refine(rgb, self.predict(rgb), self.backdrop_cleanup)
        return Image.fromarray((alpha * 255 + 0.5).astype(np.uint8), "L")
