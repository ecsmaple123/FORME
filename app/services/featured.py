"""Featured items for the home page ("Today's picks").

For now the picks are random: the same set all day (seeded by the date), with a shuffle button
for a fresh set. Items whose cover has a cutout come first, because they look best side by side.

Later this is where the AI stylist plugs in: `pick` already receives the weather (when known) and
returns items plus a short reason line, so the home page won't need to change.
"""
import random
from dataclasses import dataclass
from datetime import date
from typing import List

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from ..models import Item

COUNT = 4


@dataclass
class Picks:
    items: List[Item]
    reason: str


def pick(session: Session, day: date, weather=None, shuffle: bool = False,
         count: int = COUNT) -> Picks:
    """`weather` is unused for now (random picks); the AI version will use it."""
    items = list(session.exec(select(Item).options(selectinload(Item.photos),
                                                   selectinload(Item.category))).all())
    rng = random.Random() if shuffle else random.Random(day.toordinal())
    rng.shuffle(items)
    items.sort(key=lambda i: not (i.cover and i.cover.cutout_shown))  # stable: keeps the shuffle
    return Picks(items=items[:count], reason="Picked at random for now. Soon: chosen for the weather and your style.")


def recent(session: Session, count: int = 6) -> List[Item]:
    return list(session.exec(
        select(Item).options(selectinload(Item.photos), selectinload(Item.category))
        .order_by(Item.created_at.desc(), Item.id.desc()).limit(count)).all())


def welcome(now) -> str:
    hour = now.hour
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 17:
        return "Good afternoon"
    if 17 <= hour < 22:
        return "Good evening"
    return "Hello"
