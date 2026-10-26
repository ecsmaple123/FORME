"""Item operations used by the routes: staging images, create/update/delete, photos, search,
categories.

Adding an item is two steps. First its photos are *staged* (stored, with a JSON sidecar each in
data/staging/), then the form is saved and the staged photos are attached to the new item (the
first one is the cover). Abandoned staged photos are removed after a day. Photos added to an
existing item skip staging.
"""
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_engine
from ..models import (MAX_PHOTOS, PHOTO_KINDS, SEASONS, Category, Item, ItemColor, ItemPhoto,
                      ItemTag, OutfitItem, Tag, utcnow)
from . import colors, fabric, fetch, images
from .extract import Extracted, parse_product_html

STEM_RE = re.compile(r"^[0-9a-f]{32}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
STAGING_MAX_AGE = 24 * 3600
SORTS = {"new": "Newest first", "old": "Oldest first", "name": "Name A–Z"}
MAX_PER_REQUEST = 6  # photos per upload / import at once


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


def ingest_upload(stream: BinaryIO) -> images.ProcessedImage:
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
        return images.ingest(tmp, settings.images_dir)
    except images.ImageError as exc:
        raise UserError(str(exc))
    finally:
        tmp.unlink(missing_ok=True)


def ingest_image_url(image_url: str, referer: Optional[str] = None) -> images.ProcessedImage:
    settings = get_settings()
    tmp = _tempfile()
    try:
        sha = fetch.download_image(image_url, tmp, settings.max_upload_bytes, referer=referer)
        return images.ingest(tmp, settings.images_dir, sha256=sha)
    except (fetch.FetchError, images.ImageError) as exc:
        raise UserError(str(exc))
    finally:
        tmp.unlink(missing_ok=True)


def stage_upload(stream: BinaryIO) -> Staged:
    return _stage(ingest_upload(stream))


def stage_from_image_url(image_url: str, referer: Optional[str] = None) -> Staged:
    return _stage(ingest_image_url(image_url, referer))


def run_many(jobs: Sequence, label: str) -> Tuple[list, List[str]]:
    """Run several photo jobs (zero-arg callables); returns (results, error messages)."""
    if len(jobs) > MAX_PER_REQUEST:
        raise UserError(f"Add at most {MAX_PER_REQUEST} photos at once.")
    done, errors = [], []
    for n, job in enumerate(jobs, 1):
        try:
            done.append(job())
        except UserError as exc:
            errors.append(f"{label} {n}: {exc}" if len(jobs) > 1 else str(exc))
    return done, errors


def clean_image_urls(urls: Sequence[str]) -> List[str]:
    """Candidate image URLs from a page or the bookmark: http(s) only, de-duplicated, max 10."""
    out: List[str] = []
    for u in urls:
        u = (u or "").strip()
        if re.match(r"^https?://", u, re.I) and len(u) <= 2000 and u not in out:
            out.append(u)
    return out[:10]


def clean_kind(kind: str, default: str = "product") -> str:
    return kind if kind in PHOTO_KINDS else default


def _cutout_status(kind: str) -> str:
    """Fit pictures keep their background; every other photo is queued for the cutout worker."""
    return "skip" if kind == "fit" else "pending"


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
    # Photos whose background was removed keep only the cutout (the worker deletes the rest; this
    # catches photos cut out before that, or a worker stopped in between).
    with Session(get_engine()) as session:
        for stem, ext in session.exec(select(ItemPhoto.image_file, ItemPhoto.image_ext)
                                      .where(ItemPhoto.cutout_status == "done")).all():
            images.delete_files(settings.images_dir, stem, ext)
    # Image files that no item and no staged upload refers to (e.g. left by a crash).
    with Session(get_engine()) as session:
        keep = set(session.exec(select(ItemPhoto.image_file)).all())
        keep |= {c for c in session.exec(select(ItemPhoto.cutout_file)).all() if c}
    keep |= {side.stem for side in settings.staging_dir.glob("*.json")}
    for kind in ("orig", "display", "thumb", "cutout"):
        for f in (settings.images_dir / kind).iterdir():
            # name.ext and cutout thumbnails name.thumb.webp
            if f.name.split(".")[0] not in keep and now - f.stat().st_mtime > max_age:
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
    fabric: str = ""
    brand: str = ""
    size: str = ""
    seasons: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    source_url: str = ""
    new_category: str = ""  # typed into the form: created on save if it doesn't exist

    @property
    def tags_text(self) -> str:
        return ", ".join(self.tags)

    @classmethod
    def from_item(cls, item: Item) -> "ItemData":
        return cls(
            name=item.name, category_id=item.category_id, subcategory=item.subcategory,
            color_hex=item.color_hex, color_name=item.color_name, fabric=item.fabric,
            brand=item.brand,
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
    data.new_category = _category_name(data.new_category)
    if data.new_category:
        data.category_id = None  # resolved below, once everything else is valid
    elif data.category_id is None or session.get(Category, data.category_id) is None:
        errors["category_id"] = "Pick a category."
    data.fabric = fabric.clean(data.fabric)
    data.color_hex = data.color_hex.strip().lower()
    if re.match(r"^[0-9a-f]{6}$", data.color_hex):
        data.color_hex = "#" + data.color_hex  # typed without the # (awkward on phone keyboards)
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
    if data.new_category and not errors:
        # Reuse a same-named category; otherwise add it at the end. Committed with the item.
        data.category_id = find_or_add_category(session, data.new_category).id
        data.new_category = ""
    return errors


def _apply(item: Item, data: ItemData, session: Session) -> None:
    item.name = data.name
    item.category_id = data.category_id
    item.subcategory = data.subcategory
    item.color_hex = data.color_hex
    item.color_name = data.color_name
    item.fabric = data.fabric
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

def _color_rows(found: Sequence) -> List[ItemColor]:
    """ItemColor rows from staged color dicts or images.DominantColor objects."""
    rows = []
    for i, c in enumerate(found):
        if not isinstance(c, dict):
            c = {"hex": c.hex, "share": c.share, "lab": c.lab, "hue": c.hue}
        rows.append(ItemColor(rank=i, hex=c["hex"], share=c["share"], lab_l=c["lab"][0],
                              lab_a=c["lab"][1], lab_b=c["lab"][2], hue=c["hue"]))
    return rows


def create_item(session: Session, data: ItemData, photos: Sequence[Tuple[str, str]]) -> Item:
    """photos: (staged token, kind) pairs; the first becomes the cover."""
    if not photos:
        raise UserError("Add at least one photo.")
    staged = [(load_staged(token), clean_kind(kind)) for token, kind in photos[:MAX_PHOTOS]]
    item = Item(name=data.name, category_id=data.category_id)
    _apply(item, data, session)
    item.photos = [
        ItemPhoto(position=i, kind=kind, cutout_status=_cutout_status(kind),
                  image_file=st.token, image_ext=st.ext,
                  image_sha256=st.sha256, width=st.width, height=st.height)
        for i, (st, kind) in enumerate(staged)
    ]
    item.colors = _color_rows(staged[0][0].colors)
    session.add(item)
    session.commit()
    for st, _kind in staged:
        _sidecar(st.token).unlink(missing_ok=True)
    session.refresh(item)
    return item


# ---------- photos of an existing item ----------

def check_room(item: Item, adding: int = 1) -> None:
    if len(item.photos) + adding > MAX_PHOTOS:
        raise UserError(f"An item can have at most {MAX_PHOTOS} photos "
                        f"(this one has {len(item.photos)}).")


def add_photo(session: Session, item: Item, processed: images.ProcessedImage,
              kind: str) -> ItemPhoto:
    kind = clean_kind(kind)
    photo = ItemPhoto(
        position=len(item.photos), kind=kind, cutout_status=_cutout_status(kind),
        image_file=processed.stem, image_ext=processed.ext, image_sha256=processed.sha256,
        width=processed.width, height=processed.height,
    )
    item.photos.append(photo)
    item.updated_at = utcnow()
    session.add(item)
    session.commit()
    session.refresh(photo)
    return photo


def _renumber(ordered: List[ItemPhoto]) -> None:
    for i, p in enumerate(ordered):
        p.position = i


def _recolor(session: Session, item: Item) -> None:
    """Item colors always come from the cover photo (its cutout, when there is one).

    The item's color field follows the new main color while it still holds the detected one
    (hex and name as filled in automatically), or is empty; a color the user edited stays.
    """
    old = item.colors[0].hex if item.colors else ""
    auto = not item.color_hex or (item.color_hex == old
                                  and item.color_name.lower() == colors.nearest_color_name(old).lower())
    item.colors = []
    session.flush()
    cover = item.cover
    if cover:
        item.colors = _color_rows(images.colors_of(get_settings().images_dir, cover.image_file,
                                                   cover.cutout_shown))
    if auto and item.colors:
        item.color_hex = item.colors[0].hex
        item.color_name = colors.nearest_color_name(item.color_hex)


def recolor_all() -> int:
    """Detect every item's colors again (after the detection changed); edited colors stay.

    Returns how many items got a different main color."""
    changed = 0
    with Session(get_engine()) as session:
        for item in session.exec(select(Item)).all():
            before = item.color_hex
            _recolor(session, item)
            session.add(item)
            changed += item.color_hex != before
        session.commit()
    return changed


def set_cover(session: Session, item: Item, photo: ItemPhoto) -> None:
    ordered = [photo] + [p for p in item.photos if p.id != photo.id]
    _renumber(ordered)
    item.photos = ordered
    _recolor(session, item)
    item.updated_at = utcnow()
    session.add(item)
    session.commit()


def retry_cutout(session: Session, photo: ItemPhoto) -> None:
    """Queue the photo for background removal again (the worker picks it up within seconds)."""
    photo.cutout_status = "pending"
    session.add(photo)
    session.commit()


def delete_photo(session: Session, item: Item, photo: ItemPhoto) -> None:
    if len(item.photos) <= 1:
        raise UserError("This is the item's only photo. Add another one first, or delete the item.")
    was_cover = item.cover is not None and item.cover.id == photo.id
    stem, ext, cutout = photo.image_file, photo.image_ext, photo.cutout_file
    item.photos = [p for p in item.photos if p.id != photo.id]  # delete-orphan removes the row
    _renumber(item.photos)
    session.flush()
    if was_cover:
        _recolor(session, item)
    item.updated_at = utcnow()
    session.add(item)
    session.commit()
    images.delete_files(get_settings().images_dir, stem, ext, cutout)


def get_photo(item: Item, photo_id: int) -> Optional[ItemPhoto]:
    return next((p for p in item.photos if p.id == photo_id), None)


def update_item(session: Session, item: Item, data: ItemData) -> Item:
    _apply(item, data, session)
    session.add(item)
    session.flush()
    _drop_unused_tags(session)
    session.commit()
    session.refresh(item)
    return item


def delete_item(session: Session, item: Item) -> None:
    files = [(p.image_file, p.image_ext, p.cutout_file) for p in item.photos]
    for link in session.exec(select(OutfitItem).where(OutfitItem.item_id == item.id)).all():
        session.delete(link)
    session.delete(item)
    session.flush()
    _drop_unused_tags(session)
    session.commit()
    for stem, ext, cutout in files:
        images.delete_files(get_settings().images_dir, stem, ext, cutout)


def get_item(session: Session, item_id: int) -> Optional[Item]:
    return session.exec(
        select(Item).where(Item.id == item_id)
        .options(selectinload(Item.tags), selectinload(Item.colors), selectinload(Item.category),
                 selectinload(Item.photos))
    ).first()


def search_items(session: Session, q: str = "", category_id: Optional[int] = None,
                 sort: str = "new") -> List[Item]:
    stmt = select(Item).options(selectinload(Item.category), selectinload(Item.tags),
                                selectinload(Item.photos))
    if category_id:
        stmt = stmt.where(Item.category_id == category_id)
    q = (q or "").strip()
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        tagged = select(ItemTag.item_id).join(Tag, Tag.id == ItemTag.tag_id).where(
            Tag.name.ilike(like, escape="\\"))
        stmt = stmt.where(or_(
            Item.name.ilike(like, escape="\\"),
            Item.fabric.ilike(like, escape="\\"),
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


def fabric_suggestions(session: Session) -> List[str]:
    """Fabrics already used, then the common ones (for the form's suggestion list)."""
    used = session.exec(select(Item.fabric).where(Item.fabric != "").distinct()).all()
    seen, out = set(), []
    for name in sorted(used, key=str.lower) + fabric.SUGGESTIONS:
        if name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


# ---------- categories ----------

def list_categories(session: Session) -> List[Category]:
    return list(session.exec(select(Category).order_by(Category.sort_order, Category.name)).all())


def category_counts(session: Session) -> Dict[int, int]:
    rows = session.exec(select(Item.category_id, func.count()).group_by(Item.category_id)).all()
    return dict(rows)


def group_by_category(items: Sequence[Item],
                      categories: Sequence[Category]) -> List[Tuple[Category, List[Item]]]:
    """Items in the user's category order (set in Settings), keeping their order within each."""
    by_cat: Dict[int, List[Item]] = {}
    for item in items:
        by_cat.setdefault(item.category_id, []).append(item)
    return [(c, by_cat[c.id]) for c in categories if c.id in by_cat]


def _category_name(name: str) -> str:
    return re.sub(r"\s+", " ", name or "").strip()[:60]


def _find_category(session: Session, name: str) -> Optional[Category]:
    return session.exec(select(Category).where(func.lower(Category.name) == name.lower())).first()


def _next_sort_order(session: Session) -> int:
    return (session.exec(select(func.max(Category.sort_order))).one() or 0) + 10


def find_or_add_category(session: Session, name: str) -> Category:
    """For the item form: the existing category with this name (any case), or a new one at the
    end. Only flushed, so it is saved together with the item."""
    name = _category_name(name)
    category = _find_category(session, name)
    if category is None:
        category = Category(name=name, sort_order=_next_sort_order(session))
        session.add(category)
        session.flush()
    return category


def save_category(session: Session, name: str, category: Optional[Category] = None) -> Category:
    """Add a category (at the end) or rename one."""
    name = _category_name(name)
    if not name:
        raise UserError("A category needs a name.")
    clash = _find_category(session, name)
    if clash and (category is None or clash.id != category.id):
        raise UserError(f"There is already a category called {clash.name}.")
    if category is None:
        category = Category(name=name, sort_order=_next_sort_order(session))
    category.name = name
    session.add(category)
    session.commit()
    return category


def move_category(session: Session, category: Category, step: int) -> None:
    """Move one place up (step -1) or down (+1). Renumbers 10, 20, … so the order stays clean."""
    ordered = list_categories(session)
    i = next(n for n, c in enumerate(ordered) if c.id == category.id)
    j = i + step
    if 0 <= j < len(ordered):
        ordered[i], ordered[j] = ordered[j], ordered[i]
    for n, c in enumerate(ordered):
        c.sort_order = (n + 1) * 10
        session.add(c)
    session.commit()


def delete_category(session: Session, category: Category) -> None:
    count = session.exec(select(func.count()).where(Item.category_id == category.id)).one()
    if count:
        raise UserError(f"{category.name} still has {count} item(s). Move them first.")
    session.delete(category)
    session.commit()
