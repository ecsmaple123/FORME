"""Outfits made in the Studio: each is a set of items placed on a 3:4 board.

The Studio sends the board as JSON: [{"item_id": 3, "x": 0.1, "y": 0.05, "w": 0.45}, ...], back to
front. x/y are the item's top-left corner and w its width, as fractions of the board's width (x, w)
and height (y).
"""
import json
import math
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from ..models import Item, Outfit, OutfitItem, utcnow
from .library import UserError

MAX_ITEMS = 20
MIN_W, MAX_W = 0.05, 1.5
MIN_POS, MAX_POS = -1.0, 1.5  # items may hang over the edge a little


@dataclass
class Placed:
    item_id: int
    x: float
    y: float
    w: float


def _num(value, low: float, high: float) -> float:
    v = float(value)
    if not math.isfinite(v):
        raise ValueError
    return min(max(v, low), high)


def parse_layout(text: str) -> List[Placed]:
    """The Studio's JSON board -> placed items (back to front). Raises UserError."""
    try:
        raw = json.loads(text or "[]")
        if not isinstance(raw, list):
            raise ValueError
        placed: List[Placed] = []
        for entry in raw:
            item_id = int(entry["item_id"])
            placed = [p for p in placed if p.item_id != item_id]  # once per outfit: keep the last
            placed.append(Placed(item_id, _num(entry["x"], MIN_POS, MAX_POS),
                                 _num(entry["y"], MIN_POS, MAX_POS), _num(entry["w"], MIN_W, MAX_W)))
    except (ValueError, TypeError, KeyError):
        raise UserError("The outfit board couldn't be read. Please try again.")
    if not placed:
        raise UserError("Put at least one item on the board.")
    if len(placed) > MAX_ITEMS:
        raise UserError(f"An outfit can have at most {MAX_ITEMS} items.")
    return placed


def _options():
    return (selectinload(Outfit.links).selectinload(OutfitItem.item).selectinload(Item.photos),)


def list_outfits(session: Session) -> List[Outfit]:
    stmt = select(Outfit).options(*_options()).order_by(Outfit.updated_at.desc(), Outfit.id.desc())
    return list(session.exec(stmt).all())


def get_outfit(session: Session, outfit_id: int) -> Optional[Outfit]:
    return session.exec(select(Outfit).where(Outfit.id == outfit_id).options(*_options())).first()


def default_name(session: Session) -> str:
    count = session.exec(select(func.count()).select_from(Outfit)).one()
    return f"Outfit {count + 1}"


def save_outfit(session: Session, outfit: Optional[Outfit], name: str, notes: str,
                placed: List[Placed]) -> Outfit:
    """Create (outfit=None) or replace an outfit's name, notes and board."""
    ids = {p.item_id for p in placed}
    found = set(session.exec(select(Item.id).where(Item.id.in_(ids))).all())
    placed = [p for p in placed if p.item_id in found]  # e.g. deleted in another tab meanwhile
    if not placed:
        raise UserError("The items on the board no longer exist.")
    if outfit is None:
        outfit = Outfit(name="")
    outfit.name = (name or "").strip()[:200] or default_name(session)
    outfit.notes = (notes or "").strip()[:4000]
    outfit.updated_at = utcnow()
    # Update links in place: re-inserting a removed (outfit_id, item_id) in the same flush would
    # run the INSERT before the DELETE and hit the primary key.
    existing = {link.item_id: link for link in outfit.links}
    links = []
    for i, p in enumerate(placed):
        link = existing.get(p.item_id) or OutfitItem(item_id=p.item_id)
        link.position, link.x, link.y, link.w = i, p.x, p.y, p.w
        links.append(link)
    outfit.links = links
    session.add(outfit)
    session.commit()
    return get_outfit(session, outfit.id)


def delete_outfit(session: Session, outfit: Outfit) -> None:
    session.delete(outfit)
    session.commit()


def board_json(outfit: Optional[Outfit]) -> List[dict]:
    """An outfit's board in the Studio's format (the Studio adds names and images itself)."""
    if outfit is None:
        return []
    return [{"item_id": link.item_id, "x": link.x, "y": link.y, "w": link.w}
            for link in outfit.links]
