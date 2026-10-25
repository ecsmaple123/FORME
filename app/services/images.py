"""Image pipeline: validate, keep a (size-capped) original, make display + thumbnail, find colors.

Memory: JPEGs are decoded with draft() at a reduced scale. Other formats must be decoded at full
size, so they have lower pixel caps (PIXEL_LIMITS). Alpha is flattened before resizing, the decoded
source is freed before resampling, only one image is processed at a time, and color analysis runs
on a 96 px copy.
"""
import hashlib
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


def delete_files(images_dir: Path, stem: str, ext: str) -> None:
    if not stem:
        return
    for p in paths(images_dir, stem, ext).values():
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
    """Main colors, ignoring a uniform background (e.g. the white of product shots)."""
    small = im.copy()
    small.thumbnail((COLOR_SAMPLE, COLOR_SAMPLE))
    w, h = small.size
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
    palette = quant.getpalette()[: count * 3]
    total = len(pixels)
    result = []
    for n, idx in sorted(quant.getcolors(), reverse=True):
        rgb = tuple(palette[idx * 3: idx * 3 + 3])
        result.append(DominantColor(
            hex=colors.rgb_to_hex(rgb),
            share=round(n / total, 3),
            lab=tuple(round(v, 2) for v in colors.rgb_to_lab(rgb)),
            hue=colors.hue_degrees(rgb),
        ))
    return result


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
