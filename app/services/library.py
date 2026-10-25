"""Item operations used by the routes: staging images, create/update/delete, search, categories.

Adding an item is two steps. First the image is *staged* (stored, with a JSON sidecar in
data/staging/), then the form is saved and the staged image is attached to the new item.
Abandoned staged images are removed after a day.
"""
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_engine
from ..models import SEASONS, Category, Item, ItemColor, ItemTag, OutfitItem, Tag, utcnow
from . import colors, fetch, images
from .extract import Extracted, parse_product_html

STEM_RE = re.compile(r"^[0-9a-f]{32}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
STAGING_MAX_AGE = 24 * 3600
SORTS = {"new": "Newest first", "old": "Oldest first", "name": "Name A–Z"}


class UserError(ValueError):
    """Message is shown to the user."""


# ---------- staging ----------

@dataclass
class Staged:
    token: str
    ext: str
    sha256: str
    width: int
    height: int
    colors: List[dict]

    @property
    def primary_hex(self) -> str:
        return self.colors[0]["hex"] if self.colors else ""


def _sidecar(token: str) -> Path:
    if not STEM_RE.match(token or ""):
        raise UserError("The uploaded image has expired. Please add it again.")
    return get_settings().staging_dir / f"{token}.json"


def _stage(processed: images.ProcessedImage) -> Staged:
    staged = Staged(
        token=processed.stem, ext=processed.ext, sha256=processed.sha256,
        width=processed.width, height=processed.height,
        colors=[{"hex": c.hex, "share": c.share, "lab": list(c.lab), "hue": c.hue}
                for c in processed.colors],
    )
    _sidecar(staged.token).write_text(json.dumps(staged.__dict__), encoding="utf-8")
    return staged


def load_staged(token: str) -> Staged:
    path = _sidecar(token)
    if not path.is_file():
        raise UserError("The uploaded image has expired. Please add it again.")
    return Staged(**json.loads(path.read_text(encoding="utf-8")))


def _tempfile() -> Path:
    fd, name = tempfile.mkstemp(dir=get_settings().tmp_dir, suffix=".upload")
    os.close(fd)
    return Path(name)


def stage_upload(stream: BinaryIO) -> Staged:
    settings = get_settings()
    tmp = _tempfile()
    try:
        size = 0
        with tmp.open("wb") as out:
            for chunk in iter(lambda: stream.read(1 << 16), b""):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise UserError(f"That file is larger than {settings.max_upload_mb} MB.")
                out.write(chunk)
        if size == 0:
            raise UserError("No file was uploaded.")
        return _stage(images.ingest(tmp, settings.images_dir))
    except images.ImageError as exc:
        raise UserError(str(exc))
    finally:
        tmp.unlink(missing_ok=True)


def stage_from_image_url(image_url: str, referer: Optional[str] = None) -> Staged:
    settings = get_settings()
    tmp = _tempfile()
    try:
        sha = fetch.download_image(image_url, tmp, settings.max_upload_bytes, referer=referer)
        return _stage(images.ingest(tmp, settings.images_dir, sha256=sha))
    except (fetch.FetchError, images.ImageError) as exc:
        raise UserError(str(exc))
    finally:
        tmp.unlink(missing_ok=True)


def extract_from_page(url: str) -> Extracted:
    """Raises UserError with a friendly message when nothing usable is found."""
    try:
        resp = fetch.fetch_page(url)
    except fetch.Blocked as exc:
        raise UserError(f"{exc} Many stores block automated requests — paste the image URL "
                        "or upload the photo instead.")
    except fetch.FetchError as exc:
        raise UserError(f"{exc} You can paste the image URL or upload the photo instead.")
    found = parse_product_html(resp.body, resp.url)
    if not found.image_url:
        reason = ("The store showed a bot check instead of the product page."
                  if found.looks_blocked else "No product image was found on that page.")
        raise UserError(f"{reason} Paste the image URL or upload the photo instead.")
    return found


def cleanup_staging(max_age: int = STAGING_MAX_AGE) -> int:
    settings = get_settings()
    removed = 0
    now = time.time()
    for side in settings.staging_dir.glob("*.json"):
        if now - side.stat().st_mtime > max_age:
            try:
                data = json.loads(side.read_text(encoding="utf-8"))
                images.delete_files(settings.images_dir, data["token"], data["ext"])
            except (ValueError, KeyError):
                pass
            side.unlink(missing_ok=True)
            removed += 1
    # Image files that no item and no staged upload refers to (e.g. left by a crash).
    with Session(get_engine()) as session:
        keep = set(session.exec(select(Item.image_file)).all())
    keep |= {side.stem for side in settings.staging_dir.glob("*.json")}
    for kind in ("orig", "display", "thumb"):
        for f in (settings.images_dir / kind).iterdir():
            if f.stem not in keep and now - f.stat().st_mtime > max_age:
                f.unlink(missing_ok=True)
                removed += 1
    for tmp in settings.tmp_dir.glob("*"):
        if now - tmp.stat().st_mtime > 3600:
            if tmp.is_dir():
                shutil.rmtree(tmp, ignore_errors=True)
            else:
                tmp.unlink(missing_ok=True)
    return removed


# ---------- form data ----------

@dataclass
class ItemData:
    name: str = ""
    category_id: Optional[int] = None
    subcategory: str = ""
    color_hex: str = ""
    color_name: str = ""
    brand: str = ""
    size: str = ""
    seasons: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    source_url: str = ""

    @property
    def tags_text(self) -> str:
        return ", ".join(self.tags)

    @classmethod
    def from_item(cls, item: Item) -> "ItemData":
        return cls(
            name=item.name, category_id=item.category_id, subcategory=item.subcategory,
            color_hex=item.color_hex, color_name=item.color_name, brand=item.brand,
            size=item.size, seasons=item.season_list, tags=[t.name for t in item.tags],
            notes=item.notes, source_url=item.source_url,
        )


def parse_tags(text: str) -> List[str]:
    seen: List[str] = []
    for raw in re.split(r"[,\n]", text or ""):
        tag = re.sub(r"\s+", " ", raw).strip().lower()[:40]
        if tag and tag not in seen:
            seen.append(tag)
    return seen[:30]


def validate(data: ItemData, session: Session) -> Dict[str, str]:
    errors = {}
    data.name = data.name.strip()[:200]
    if not data.name:
        errors["name"] = "Give the item a name."
    if data.category_id is None or session.get(Category, data.category_id) is None:
        errors["category_id"] = "Pick a category."
    data.color_hex = data.color_hex.strip().lower()
    if data.color_hex and not HEX_RE.match(data.color_hex):
        errors["color_hex"] = "Use a hex color like #1d2645."
    elif data.color_hex and not data.color_name.strip():
        data.color_name = colors.nearest_color_name(data.color_hex)
    data.seasons = [s for s in SEASONS if s in data.seasons]
    data.source_url = data.source_url.strip()[:2000]
    if data.source_url and not re.match(r"^https?://", data.source_url, re.I):
        errors["source_url"] = "The source URL must start with http:// or https://."
    for attr, limit in (("subcategory", 80), ("color_name", 40), ("brand", 100),
                        ("size", 40), ("notes", 4000)):
        setattr(data, attr, getattr(data, attr).strip()[:limit])
    return errors


def _apply(item: Item, data: ItemData, session: Session) -> None:
    item.name = data.name
    item.category_id = data.category_id
    item.subcategory = data.subcategory
    item.color_hex = data.color_hex
    item.color_name = data.color_name
    item.brand = data.brand
    item.size = data.size
    item.seasons = ",".join(data.seasons)
    item.notes = data.notes
    item.source_url = data.source_url
    item.tags = [_get_or_create_tag(session, name) for name in data.tags]
    item.updated_at = utcnow()


def _get_or_create_tag(session: Session, name: str) -> Tag:
    tag = session.exec(select(Tag).where(Tag.name == name)).first()
    if tag is None:
        tag = Tag(name=name)
        session.add(tag)
        session.flush()
    return tag


def _drop_unused_tags(session: Session) -> None:
    used = select(ItemTag.tag_id)
    for tag in session.exec(select(Tag).where(Tag.id.not_in(used))).all():
        session.delete(tag)


# ---------- items ----------

def create_item(session: Session, data: ItemData, token: str) -> Item:
    staged = load_staged(token)
    item = Item(
        name=data.name, category_id=data.category_id, image_file=staged.token,
        image_ext=staged.ext, image_sha256=staged.sha256,
        width=staged.width, height=staged.height,
    )
    _apply(item, data, session)
    item.colors = [
        ItemColor(rank=i, hex=c["hex"], share=c["share"], lab_l=c["lab"][0], lab_a=c["lab"][1],
                  lab_b=c["lab"][2], hue=c["hue"])
        for i, c in enumerate(staged.colors)
    ]
    session.add(item)
    session.commit()
    _sidecar(token).unlink(missing_ok=True)
    session.refresh(item)
    return item


def update_item(session: Session, item: Item, data: ItemData) -> Item:
    _apply(item, data, session)
    session.add(item)
    session.flush()
    _drop_unused_tags(session)
    session.commit()
    session.refresh(item)
    return item


def delete_item(session: Session, item: Item) -> None:
    stem, ext = item.image_file, item.image_ext
    for link in session.exec(select(OutfitItem).where(OutfitItem.item_id == item.id)).all():
        session.delete(link)
    session.delete(item)
    session.flush()
    _drop_unused_tags(session)
    session.commit()
    images.delete_files(get_settings().images_dir, stem, ext)


def get_item(session: Session, item_id: int) -> Optional[Item]:
    return session.exec(
        select(Item).where(Item.id == item_id)
        .options(selectinload(Item.tags), selectinload(Item.colors), selectinload(Item.category))
    ).first()


def search_items(session: Session, q: str = "", category_id: Optional[int] = None,
                 sort: str = "new") -> List[Item]:
    stmt = select(Item).options(selectinload(Item.category), selectinload(Item.tags))
    if category_id:
        stmt = stmt.where(Item.category_id == category_id)
    q = (q or "").strip()
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        tagged = select(ItemTag.item_id).join(Tag, Tag.id == ItemTag.tag_id).where(
            Tag.name.ilike(like, escape="\\"))
        stmt = stmt.where(or_(
            Item.name.ilike(like, escape="\\"),
            Item.brand.ilike(like, escape="\\"),
            Item.id.in_(tagged),
        ))
    if sort == "name":
        stmt = stmt.order_by(func.lower(Item.name), Item.id)
    elif sort == "old":
        stmt = stmt.order_by(Item.created_at, Item.id)
    else:
        stmt = stmt.order_by(Item.created_at.desc(), Item.id.desc())
    return list(session.exec(stmt).all())


def subcategory_suggestions(session: Session) -> Dict[int, List[str]]:
    rows = session.exec(
        select(Item.category_id, Item.subcategory).where(Item.subcategory != "").distinct()
    ).all()
    out: Dict[int, List[str]] = {}
    for cat_id, sub in rows:
        out.setdefault(cat_id, []).append(sub)
    return {k: sorted(v, key=str.lower) for k, v in out.items()}


# ---------- categories ----------

def list_categories(session: Session) -> List[Category]:
    return list(session.exec(select(Category).order_by(Category.sort_order, Category.name)).all())


def category_counts(session: Session) -> Dict[int, int]:
    rows = session.exec(select(Item.category_id, func.count()).group_by(Item.category_id)).all()
    return dict(rows)


def save_category(session: Session, name: str, sort_order: int,
                  category: Optional[Category] = None) -> Category:
    name = re.sub(r"\s+", " ", name or "").strip()[:60]
    if not name:
        raise UserError("A category needs a name.")
    clash = session.exec(select(Category).where(func.lower(Category.name) == name.lower())).first()
    if clash and (category is None or clash.id != category.id):
        raise UserError(f"There is already a category called {clash.name}.")
    category = category or Category(name=name)
    category.name, category.sort_order = name, sort_order
    session.add(category)
    session.commit()
    return category


def delete_category(session: Session, category: Category) -> None:
    count = session.exec(select(func.count()).where(Item.category_id == category.id)).one()
    if count:
        raise UserError(f"{category.name} still has {count} item(s). Move them first.")
    session.delete(category)
    session.commit()
