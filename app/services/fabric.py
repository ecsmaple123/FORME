"""Fabric names: suggestions for the form, and splitting a fabric out of an item name
("Cashmere Quarter Zip" -> "Quarter Zip" + "Cashmere"). Used for store imports and by migration 0005."""
import re
from typing import List, Tuple

# Lower-case words that are a fabric or material on their own. Words that are also garment
# names or styles (oxford, chino, knit, down, mesh) are left out so they never get stripped.
FABRICS = {
    "cashmere", "wool", "merino", "lambswool", "alpaca", "mohair", "angora", "camel", "vicuna",
    "vicuña", "cotton", "silk", "linen", "hemp", "denim", "corduroy", "velvet", "velour", "satin",
    "chiffon", "crepe", "tweed", "flannel", "jersey", "fleece", "boucle", "bouclé", "gabardine",
    "twill", "poplin", "chambray", "seersucker", "canvas", "suede", "nubuck", "leather",
    "calfskin", "lambskin", "shearling", "nylon", "polyester", "viscose", "rayon", "lyocell",
    "tencel", "modal", "elastane", "spandex", "lace", "tulle", "organza", "terry", "piqué", "pique",
}
SUGGESTIONS = sorted(w.capitalize() for w in FABRICS if w not in {"vicuna", "pique", "boucle"})


def _is_fabric(word: str) -> bool:
    parts = [p for p in re.split(r"[-/]", word.lower().strip(".,;:()")) if p]
    return bool(parts) and all(p in FABRICS for p in parts)


def split_name(name: str) -> Tuple[str, str]:
    """(name without fabric words, fabric). Unchanged with "" if there is no fabric word, or if
    the name is nothing but fabric words (e.g. "Cashmere"), so a name is never emptied."""
    words = (name or "").split()
    fabric: List[str] = [w for w in words if _is_fabric(w)]
    rest = [w for w in words if not _is_fabric(w)]
    if not fabric or not rest:
        return (name or "").strip(), ""
    return " ".join(rest), " ".join(fabric)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:80]
