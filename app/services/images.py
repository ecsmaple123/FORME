"""Image pipeline: validate, keep a (size-capped) original, make display + thumbnail, find colors.

Memory: JPEGs are decoded with draft() at a reduced scale. Other formats must be decoded at full
size, so they have lower pixel caps (PIXEL_LIMITS). Alpha is flattened before resizing, the decoded
source is freed before resampling, only one image is processed at a time, and color analysis runs
on a 96 px copy.
"""
import functools
import hashlib
import math
import shutil
import threading
import uuid
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from PIL import Image, UnidentifiedImageError

from . import colors

MAX_PIXELS = 40_000_000
# Formats without reduced-scale decoding are capped so one upload stays under ~100 MB extra RSS
# (measured on the Pi, 2026-10-24). 8.5 MP fits a 4K screenshot; Pillow's WebP decoder needs
# roughly 3x the pixels' size, hence its lower cap.
MAX_FULL_DECODE = 8_500_000
PIXEL_LIMITS = {"JPEG": MAX_PIXELS, "MPO": MAX_PIXELS, "WEBP": 6_000_000}
ORIG_MAX = 3000      # JPEG originals are capped here (enough for background removal later)
DISPLAY_MAX = 1500   # half of ORIG_MAX, so JPEG draft() can decode a capped original at 1/2
THUMB_MAX = 400
COLOR_SAMPLE = 96
KEEP_AS_IS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
ACCEPTED = set(KEEP_AS_IS) | {"MPO", "GIF", "BMP", "TIFF"}

Image.MAX_IMAGE_PIXELS = MAX_PIXELS
warnings.simplefilter("error", Image.DecompressionBombWarning)

_one_at_a_time = threading.Semaphore(1)
DRAFTABLE = {"JPEG", "MPO"}
ORIENTATION_TAG = 0x0112
TRANSPOSE = {
    2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90,
}


class ImageError(ValueError):
    """Shown to the user as-is."""


@dataclass
class DominantColor:
    hex: str
    share: float
    lab: tuple
    hue: float


@dataclass
class ProcessedImage:
    stem: str
    ext: str
    sha256: str
    width: int
    height: int
    colors: List[DominantColor] = field(default_factory=list)

    @property
    def primary_hex(self) -> str:
        return self.colors[0].hex if self.colors else ""


def paths(images_dir: Path, stem: str, ext: str = "jpg") -> dict:
    return {
        "orig": images_dir / "orig" / f"{stem}.{ext}",
        "display": images_dir / "display" / f"{stem}.jpg",
        "thumb": images_dir / "thumb" / f"{stem}.webp",
    }


def cutout_paths(images_dir: Path, name: str) -> dict:
    return {
        "display": images_dir / "cutout" / f"{name}.webp",
        "thumb": images_dir / "cutout" / f"{name}.thumb.webp",
    }


def delete_files(images_dir: Path, stem: str, ext: str, cutout: Optional[str] = None) -> None:
    if stem:
        for p in paths(images_dir, stem, ext).values():
            p.unlink(missing_ok=True)
    if cutout:
        for p in cutout_paths(images_dir, cutout).values():
            p.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _open(path: Path) -> Image.Image:
    try:
        im = Image.open(path)
    except UnidentifiedImageError:
        raise ImageError(
            "That file isn't an image Pillow can read. JPEG, PNG and WebP work; "
            "for iPhone HEIC photos, export as JPEG first (or set Camera → Formats → Most Compatible)."
        )
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageError("That image is too large (over 40 megapixels).")
    if im.format not in ACCEPTED:
        im.close()
        raise ImageError(f"Unsupported image format: {im.format}.")
    limit = PIXEL_LIMITS.get(im.format, MAX_FULL_DECODE)
    if im.width * im.height > limit:
        im.close()
        if im.format in DRAFTABLE:
            raise ImageError("That image is too large (over 40 megapixels).")
        raise ImageError(
            f"{im.format} images over {limit / 1e6:g} megapixels aren't accepted here (unlike "
            "JPEG they must be decoded at full size). Save it as JPEG or make it smaller first.")
    return im


def _orientation(im: Image.Image) -> int:
    # Only JPEG/WebP carry orientation in practice; PNG's getexif() would decode the whole image.
    if im.format not in DRAFTABLE and im.format != "WEBP":
        return 1
    try:
        return int(im.getexif().get(ORIENTATION_TAG, 1))
    except Exception:
        return 1


def _flatten(im: Image.Image) -> Image.Image:
    """Any mode -> RGB, transparency composited on white. May return `im` itself."""
    if im.mode == "RGB":
        return im
    if im.mode == "P":
        im = im.convert("RGBA" if "transparency" in im.info else "RGB")
        if im.mode == "RGB":
            return im
    if im.mode in ("RGBA", "LA", "PA"):
        rgba = im if im.mode == "RGBA" else im.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return im.convert("RGB")


def _load_scaled(path: Path, max_edge: int) -> Image.Image:
    """Decode at (roughly) max_edge, flatten to RGB on white, shrink, apply EXIF rotation.

    Flattening comes before resizing because Pillow resizes RGBA via a premultiplied full-size
    copy; flattening costs the same single copy and lets the decoded source be freed earlier.
    """
    with _open(path) as src:
        orientation = _orientation(src)
        if src.format in DRAFTABLE:
            # draft() only scales down if the result still covers the box in *both* dimensions,
            # so ask for the image's own aspect ratio, not a square.
            scale = min(1.0, max_edge / max(src.size))
            src.draft("RGB", (max(1, int(src.width * scale)), max(1, int(src.height * scale))))
        im = _flatten(src)
        if im is not src:
            src.close()  # free the decoded source before resampling
        # Non-JPEG was decoded at full size: box-reduce first (small intermediate), then Lanczos.
        im.thumbnail((max_edge, max_edge), Image.LANCZOS,
                     reducing_gap=3.0 if src.format in DRAFTABLE else 1.0)
        if orientation in TRANSPOSE:
            im = im.transpose(TRANSPOSE[orientation])
        return im.copy() if im is src else im  # src's pixels are freed when the file closes


def dominant_colors(im: Image.Image, count: int = 5) -> List[DominantColor]:
    """Main colors, ignoring a uniform background (e.g. the white of product shots).

    For a cutout (RGBA) only the opaque pixels count, so no background guessing is needed.
    """
    small = im.copy()
    small.thumbnail((COLOR_SAMPLE, COLOR_SAMPLE))
    w, h = small.size
    if small.mode == "RGBA":
        opaque = [c[:3] for c in small.getdata() if c[3] >= 128]
        small = small.convert("RGB")
        pixels = opaque if len(opaque) >= 20 else list(small.getdata())
    else:
        pixels = list(small.getdata())
        border = [pixels[x] for x in range(w)] + [pixels[(h - 1) * w + x] for x in range(w)]
        border += [pixels[y * w] for y in range(h)] + [pixels[y * w + w - 1] for y in range(h)]
        bg = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))
        near_bg = sum(1 for c in border if colors.color_distance(c, bg) < 12)
        if near_bg / len(border) > 0.6:
            fg = [c for c in pixels if colors.color_distance(c, bg) >= 12]
            if len(fg) >= len(pixels) * 0.03:
                pixels = fg

    sample = Image.new("RGB", (len(pixels), 1))
    sample.putdata(pixels)
    quant = sample.quantize(colors=count, method=Image.Quantize.MEDIANCUT, kmeans=3)
    clusters = {}
    for rgb, idx in zip(pixels, quant.getdata()):
        clusters.setdefault(idx, []).append(rgb)
    total = len(pixels)
    result = []
    for members in sorted(_merge_shades(list(clusters.values())), key=len, reverse=True):
        rgb = _true_color(members)
        result.append(DominantColor(
            hex=colors.rgb_to_hex(rgb),
            share=round(len(members) / total, 3),
            lab=tuple(round(v, 2) for v in colors.rgb_to_lab(rgb)),
            hue=colors.hue_degrees(rgb),
        ))
    return result


SHADE_CHROMA = 12      # clusters this close in a*/b* ...
SHADE_LIGHTNESS = 40   # ...and this close in lightness are one fabric in light and in shadow


@functools.lru_cache(maxsize=65536)
def _lab(rgb: tuple) -> tuple:
    return colors.rgb_to_lab(rgb)


def _median(values: list) -> float:
    values = sorted(values)
    return values[len(values) // 2]


def _merge_shades(clusters: List[list]) -> List[list]:
    """Join clusters that are the same color lit differently (a fold in shadow, a sunny patch)."""
    centers = []
    for members in clusters:
        labs = [_lab(c) for c in members]
        centers.append(tuple(_median([v[i] for v in labs]) for i in range(3)))
    group = list(range(len(clusters)))

    def root(i):
        while group[i] != i:
            i = group[i]
        return i

    for i in range(len(clusters)):
        for j in range(i + 1, len(clusters)):
            (li, ai, bi), (lj, aj, bj) = centers[i], centers[j]
            if abs(li - lj) < SHADE_LIGHTNESS and math.hypot(ai - aj, bi - bj) < SHADE_CHROMA:
                group[root(j)] = root(i)
    merged = {}
    for i, members in enumerate(clusters):
        merged.setdefault(root(i), []).extend(members)
    return list(merged.values())


def _true_color(members: list) -> tuple:
    """The color as it looks in plain light: the median of the mid-tones, so deep shadows and
    shine don't drag it darker or lighter (a quantizer's palette entry tends to run dark)."""
    by_light = sorted(members, key=lambda c: _lab(c)[0])
    n = len(by_light)
    mid = by_light[n // 4: max(n // 4 + 1, n * 9 // 10)]
    return tuple(int(_median([c[i] for c in mid])) for i in range(3))


def render_derivatives(images_dir: Path, stem: str, ext: str) -> List[DominantColor]:
    """(Re)build display + thumbnail from the stored original; returns its colors."""
    p = paths(images_dir, stem, ext)
    with _one_at_a_time:
        display = _load_scaled(p["orig"], DISPLAY_MAX)
        display.save(p["display"], "JPEG", quality=85, optimize=True, progressive=True)
        thumb = display.copy()
        thumb.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
        thumb.save(p["thumb"], "WEBP", quality=80, method=4)
        found = dominant_colors(thumb)
        display.close()
        thumb.close()
    return found


def ingest(src: Path, images_dir: Path, sha256: Optional[str] = None) -> ProcessedImage:
    """Store a new image from a temp file. The temp file is left for the caller to delete."""
    stem = uuid.uuid4().hex
    with _open(src) as im:
        fmt, w, h, orientation = im.format, im.width, im.height, _orientation(im)
    # PNG/WebP are kept as uploaded (already bounded by MAX_FULL_DECODE); JPEGs over ORIG_MAX
    # and other formats are re-encoded to JPEG.
    reencode = fmt not in KEEP_AS_IS or (fmt in DRAFTABLE and max(w, h) > ORIG_MAX)
    ext = "jpg" if reencode else KEEP_AS_IS[fmt]
    p = paths(images_dir, stem, ext)
    try:
        if reencode:
            with _one_at_a_time:
                big = _load_scaled(src, ORIG_MAX)
                big.save(p["orig"], "JPEG", quality=90)
                w, h = big.size
                big.close()
        else:
            shutil.copyfile(src, p["orig"])  # keeps EXIF; display/thumb are rotated + stripped
            if orientation in (5, 6, 7, 8):
                w, h = h, w
        found = render_derivatives(images_dir, stem, ext)
    except ImageError:
        delete_files(images_dir, stem, ext)
        raise
    except (OSError, ValueError, SyntaxError) as exc:  # truncated/corrupt files
        delete_files(images_dir, stem, ext)
        raise ImageError(f"That image couldn't be processed ({exc.__class__.__name__}); "
                         "it may be damaged. Try another copy or a screenshot.")
    return ProcessedImage(
        stem=stem, ext=ext, sha256=sha256 or sha256_file(src), width=w, height=h, colors=found,
    )


def colors_of(images_dir: Path, stem: str, cutout: Optional[str] = None) -> List[DominantColor]:
    """Dominant colors of a stored photo, read from its (small) thumbnail or cutout thumbnail."""
    if cutout:
        with Image.open(cutout_paths(images_dir, cutout)["thumb"]) as thumb:
            return dominant_colors(thumb.convert("RGBA"))
    with Image.open(paths(images_dir, stem)["thumb"]) as thumb:
        return dominant_colors(thumb.convert("RGB"))


# ---------- cutouts (background removed; the mask comes from app.services.cutout) ----------

CUTOUT_MIN_SHARE = 0.02   # less than this is "no clear subject"
CUTOUT_MAX_SHARE = 0.95   # more than this means nothing to remove (e.g. a fabric close-up)
CUTOUT_PAD = 0.03         # margin around the subject, as a share of its longer side


def subject_box(alpha: Image.Image) -> Optional[tuple]:
    """Padded bounding box of the opaque part of a mask ("L"), or None if it isn't a usable subject."""
    solid = alpha.point(lambda v: 255 if v >= 128 else 0)
    share = solid.histogram()[255] / (alpha.width * alpha.height)
    box = solid.getbbox()
    if box is None or not CUTOUT_MIN_SHARE <= share <= CUTOUT_MAX_SHARE:
        return None
    left, top, right, bottom = box
    pad = int(CUTOUT_PAD * max(right - left, bottom - top))
    return (max(left - pad, 0), max(top - pad, 0),
            min(right + pad, alpha.width), min(bottom + pad, alpha.height))


def save_cutout(images_dir: Path, rgb: Image.Image, alpha: Image.Image) -> Optional[str]:
    """Write the cutout (display + thumbnail, transparent WebP cropped to the subject).

    Returns its new file name, or None when the mask has no usable subject.
    """
    box = subject_box(alpha)
    if box is None:
        return None
    name = uuid.uuid4().hex
    p = cutout_paths(images_dir, name)
    p["display"].parent.mkdir(parents=True, exist_ok=True)
    cut = rgb.convert("RGB")
    cut.putalpha(alpha)
    cut = cut.crop(box)
    try:
        cut.save(p["display"], "WEBP", quality=88, method=4)
        cut.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
        cut.save(p["thumb"], "WEBP", quality=82, method=4)
    except OSError:
        delete_files(images_dir, "", "", cutout=name)
        raise
    return name
