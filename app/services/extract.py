"""Pull the main product image, title and brand out of a product page.

Image order: og:image (and friends) -> JSON-LD Product image -> largest <img>.
"""
import json
import re
from dataclasses import dataclass
from typing import Iterator, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BOT_WALL_MARKERS = (
    "captcha", "cf-chl", "just a moment...", "access denied", "px-captcha",
    "are you a robot", "verify you are human", "request unsuccessful",
)
SKIP_IMG = re.compile(r"logo|icon|sprite|pixel|spacer|badge|avatar|placeholder|loading", re.I)
PRODUCT_TYPES = {"product", "productgroup", "individualproduct", "productmodel"}


@dataclass
class Extracted:
    image_url: Optional[str] = None
    image_source: str = ""     # og | json-ld | img
    title: str = ""
    brand: str = ""
    looks_blocked: bool = False


def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return ""


def _walk_jsonld(node) -> Iterator[dict]:
    if isinstance(node, list):
        for x in node:
            yield from _walk_jsonld(x)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in node:
                yield from _walk_jsonld(node[key])


def _is_product(node: dict) -> bool:
    types = node.get("@type", [])
    types = [types] if isinstance(types, str) else types
    return any(str(t).lower() in PRODUCT_TYPES for t in types)


def _first_image(value) -> Optional[str]:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for v in value:
            found = _first_image(v)
            if found:
                return found
    if isinstance(value, dict):
        return _first_image(value.get("contentUrl") or value.get("url"))
    return None


def _brand_name(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and value:
        return _brand_name(value[0])
    if isinstance(value, dict):
        return str(value.get("name", "")).strip()
    return ""


def _jsonld_products(soup: BeautifulSoup) -> List[dict]:
    products = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        try:
            data = json.loads(script.string or script.get_text() or "", strict=False)
        except ValueError:
            continue
        products.extend(n for n in _walk_jsonld(data) if _is_product(n))
    return products


def _srcset_best(srcset: str):
    best, best_w = None, 0
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = 0
        if len(bits) > 1 and bits[1].endswith("w") and bits[1][:-1].isdigit():
            w = int(bits[1][:-1])
        elif len(bits) > 1 and bits[1].endswith("x"):
            try:
                w = int(float(bits[1][:-1]) * 500)
            except ValueError:
                w = 0
        if best is None or w > best_w:
            best, best_w = bits[0], w
    return best, best_w


def _int_attr(value) -> int:
    m = re.match(r"\s*(\d+)", str(value or ""))
    return int(m.group(1)) if m else 0


def _largest_img(soup: BeautifulSoup) -> Optional[str]:
    best, best_score = None, -1
    for img in soup.find_all("img"):
        url, score = None, 0
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            url, w = _srcset_best(srcset)
            score = w * w
        url = url or img.get("data-src") or img.get("data-original") or img.get("src")
        if not url or url.startswith("data:") or url.lower().split("?")[0].endswith(".svg"):
            continue
        hint = " ".join([url, " ".join(img.get("class", [])), img.get("alt", ""), img.get("id", "")])
        if SKIP_IMG.search(hint):
            continue
        w, h = _int_attr(img.get("width")), _int_attr(img.get("height"))
        if w and h:
            if w < 100 or h < 100:
                continue
            score = max(score, w * h)
        score = max(score, 1)
        if score > best_score:
            best, best_score = url, score
    return best


def parse_product_html(html, base_url: str) -> Extracted:
    soup = BeautifulSoup(html, "html.parser")
    out = Extracted()
    products = _jsonld_products(soup)

    og = _meta(soup, "og:image:secure_url", "og:image", "og:image:url",
               "twitter:image", "twitter:image:src")
    if og:
        out.image_url, out.image_source = og, "og"
    else:
        for p in products:
            img = _first_image(p.get("image"))
            if img:
                out.image_url, out.image_source = img, "json-ld"
                break
    if not out.image_url:
        img = _largest_img(soup)
        if img:
            out.image_url, out.image_source = img, "img"
    if out.image_url:
        out.image_url = urljoin(base_url, out.image_url.strip())

    ld_name = next((str(p["name"]).strip() for p in products if p.get("name")), "")
    page_title = soup.title.get_text(strip=True) if soup.title else ""
    out.title = _meta(soup, "og:title") or ld_name or _meta(soup, "twitter:title") or page_title

    out.brand = next((b for b in (_brand_name(p.get("brand")) for p in products) if b), "")
    if not out.brand:
        out.brand = _meta(soup, "product:brand", "og:brand", "brand")
    if not out.brand:
        tag = soup.find(attrs={"itemprop": "brand"})
        if tag:
            out.brand = (tag.get("content") or tag.get_text(" ", strip=True))[:100]

    if not out.image_url:
        text = soup.get_text(" ", strip=True).lower()[:5000] + " " + page_title.lower()
        out.looks_blocked = any(m in text for m in BOT_WALL_MARKERS)
    out.title = re.sub(r"\s+", " ", out.title)[:200]
    out.brand = re.sub(r"\s+", " ", out.brand)[:100]
    return out
