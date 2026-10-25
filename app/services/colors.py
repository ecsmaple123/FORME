"""Color math: hex <-> RGB, sRGB -> CIE Lab, hue, and nearest named color."""
import colorsys
import math
from typing import Dict, Tuple

RGB = Tuple[int, int, int]

# A clothing-oriented palette; names are what shows in the UI.
NAMED_COLORS: Dict[str, str] = {
    "black": "#111111", "charcoal": "#36454f", "grey": "#808080", "light grey": "#c8c8c8",
    "white": "#f8f8f8", "cream": "#f3ead3", "beige": "#d9c7a7", "camel": "#c19a6b",
    "tan": "#d2b48c", "brown": "#7b4b2a", "chocolate": "#4a2c1d", "khaki": "#a9a27a",
    "olive": "#6b6b2f", "forest green": "#228b22", "green": "#3c9a4b", "mint": "#a8e4c0",
    "sage": "#9caf88", "teal": "#1f7a7a", "turquoise": "#40c4c0", "light blue": "#9ec9ea",
    "sky blue": "#62a8e5", "denim": "#4f6d8f", "blue": "#2f5fc4", "royal blue": "#2340a8",
    "navy": "#1d2645", "lavender": "#c4b3e3", "purple": "#6f3e9e", "plum": "#6e2d5c",
    "burgundy": "#6d1a2a", "maroon": "#5a1e1e", "red": "#c62a2a", "coral": "#f0806a",
    "rust": "#a5472a", "orange": "#e9822a", "mustard": "#d4a32a", "yellow": "#f2d43a",
    "blush": "#efc4c0", "pink": "#ec8fb0", "hot pink": "#e0388a", "gold": "#c9a54a",
    "silver": "#b7b9bd",
}


def hex_to_rgb(value: str) -> RGB:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def rgb_to_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb: RGB) -> Tuple[float, float, float]:
    r, g, b = (_lin(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def hue_degrees(rgb: RGB) -> float:
    h, _s, _v = colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb))
    return round(h * 360.0, 1)


def color_distance(a: RGB, b: RGB) -> float:
    """CIE76 delta E; good enough for naming and clustering."""
    la, lb = rgb_to_lab(a), rgb_to_lab(b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(la, lb)))


_NAMED_LAB = {name: rgb_to_lab(hex_to_rgb(h)) for name, h in NAMED_COLORS.items()}


def nearest_color_name(hex_value: str) -> str:
    lab = rgb_to_lab(hex_to_rgb(hex_value))
    return min(
        _NAMED_LAB,
        key=lambda name: sum((x - y) ** 2 for x, y in zip(lab, _NAMED_LAB[name])),
    )
