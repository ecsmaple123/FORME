"""Database tables. The schema itself is owned by Alembic (migrations/); keep both in sync."""
from datetime import datetime
from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel

SEASONS = ["spring", "summer", "autumn", "winter"]
# Item photos get their background removed (and only the cutout is kept); fit pictures keep it.
PHOTO_KINDS = {"product": "Item photo", "fit": "Fit picture"}
MAX_PHOTOS = 12
# Background removal per photo: pending -> done (cutout made) | none (no clear subject) | failed;
# skip = a fit picture, never cut out
CUTOUT_STATES = ("pending", "done", "none", "failed", "skip")


def utcnow() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


class Category(SQLModel, table=True):
    __tablename__ = "category"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=60, unique=True)
    sort_order: int = 0


class ItemTag(SQLModel, table=True):
    __tablename__ = "item_tag"
    item_id: int = Field(foreign_key="item.id", primary_key=True, ondelete="CASCADE")
    tag_id: int = Field(foreign_key="tag.id", primary_key=True, ondelete="CASCADE")


class Tag(SQLModel, table=True):
    __tablename__ = "tag"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=40, unique=True)


class Item(SQLModel, table=True):
    __tablename__ = "item"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=200)
    category_id: int = Field(foreign_key="category.id", ondelete="RESTRICT", index=True)
    subcategory: str = Field(default="", max_length=80)
    color_hex: str = Field(default="", max_length=7)
    color_name: str = Field(default="", max_length=40)
    fabric: str = Field(default="", max_length=80)
    brand: str = Field(default="", max_length=100)
    size: str = Field(default="", max_length=40)
    seasons: str = Field(default="", max_length=60)  # comma list from SEASONS
    notes: str = Field(default="", max_length=4000)
    source_url: str = Field(default="", max_length=2000)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)

    category: Optional[Category] = Relationship()
    tags: List[Tag] = Relationship(link_model=ItemTag)
    colors: List["ItemColor"] = Relationship(
        back_populates="item",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "ItemColor.rank"},
    )
    photos: List["ItemPhoto"] = Relationship(
        back_populates="item",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "ItemPhoto.position"},
    )

    @property
    def season_list(self) -> List[str]:
        return [s for s in self.seasons.split(",") if s]

    @property
    def cover(self) -> Optional["ItemPhoto"]:
        """The first photo: shown in the grid, and the source of the item's colors."""
        return self.photos[0] if self.photos else None


class ItemPhoto(SQLModel, table=True):
    """One photo of an item. Files: data/images/{orig,display,thumb}/<image_file>.* until the
    background is removed; then only data/images/cutout/<cutout_file>.webp + .thumb.webp (made by
    app.worker, which deletes the photo with its background)."""
    __tablename__ = "item_photo"
    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", ondelete="CASCADE", index=True)
    position: int = 0  # 0 = cover
    kind: str = Field(default="product", max_length=20)  # key of PHOTO_KINDS
    image_file: str = Field(max_length=64)
    image_ext: str = Field(default="jpg", max_length=8)  # extension of the original
    image_sha256: str = Field(default="", max_length=64)
    width: int = 0
    height: int = 0
    cutout_file: Optional[str] = Field(default=None, max_length=64)  # new name on every redo
    cutout_status: str = Field(default="pending", max_length=12, index=True)  # CUTOUT_STATES
    created_at: datetime = Field(default_factory=utcnow)

    item: Optional[Item] = Relationship(back_populates="photos")

    @property
    def kind_label(self) -> str:
        return PHOTO_KINDS.get(self.kind, "Item photo")

    @property
    def cutout_shown(self) -> Optional[str]:
        """The cutout's file name once the background is removed (the photo itself is gone then)."""
        if self.cutout_status == "done" and self.cutout_file:
            return self.cutout_file
        return None


class ItemColor(SQLModel, table=True):
    """Dominant colors per item (filled on upload; used later for color sorting)."""
    __tablename__ = "item_color"
    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", ondelete="CASCADE", index=True)
    rank: int
    hex: str = Field(max_length=7)
    share: float
    lab_l: float
    lab_a: float
    lab_b: float
    hue: float

    item: Optional[Item] = Relationship(back_populates="colors")


class Setting(SQLModel, table=True):
    """User preferences as key/value strings (see app/services/prefs.py for keys and defaults)."""
    __tablename__ = "setting"
    key: str = Field(primary_key=True, max_length=40)
    value: str = Field(default="", max_length=500)


class Outfit(SQLModel, table=True):
    """An outfit made in the Studio: its items and where each sits on the board."""
    __tablename__ = "outfit"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=200)
    notes: str = Field(default="", max_length=4000)
    occasion: str = Field(default="", max_length=80)  # not used by the UI yet
    season: str = Field(default="", max_length=60)  # not used by the UI yet
    source: str = Field(default="manual", max_length=20)  # manual | ai | photo-import
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)

    links: List["OutfitItem"] = Relationship(
        back_populates="outfit",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "OutfitItem.position"},
    )


class OutfitItem(SQLModel, table=True):
    """One item on an outfit's board: x, y = its top-left corner and w = its width, as fractions of
    the 3:4 board (the height follows the photo). position = stacking order, 0 at the back."""
    __tablename__ = "outfit_item"
    outfit_id: int = Field(foreign_key="outfit.id", primary_key=True, ondelete="CASCADE")
    item_id: int = Field(foreign_key="item.id", primary_key=True, ondelete="CASCADE")
    position: int = 0
    x: float = 0.0
    y: float = 0.0
    w: float = 0.4

    outfit: Optional[Outfit] = Relationship(back_populates="links")
    item: Optional[Item] = Relationship()


VERDICTS = ("like", "dislike")


class Suggestion(SQLModel, table=True):
    """An outfit the AI stylist proposed, and what the user thought of it (its memory).

    source: "daily" (Today's picks on the home page, one per day) or "stylist" (asked for on the
    Stylist page). item_ids is a comma list; items deleted since are skipped when it's shown.
    """
    __tablename__ = "suggestion"
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    source: str = Field(default="stylist", max_length=10)
    day: str = Field(default="", max_length=10, index=True)  # YYYY-MM-DD for daily picks
    replaced: bool = False  # a daily pick the user asked to redo
    request: str = Field(default="", max_length=300)  # the occasion the user typed
    weather: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=120)
    reason: str = Field(default="", max_length=600)
    item_ids: str = Field(default="", max_length=400)
    verdict: str = Field(default="", max_length=10)  # "", or one of VERDICTS
    note: str = Field(default="", max_length=300)  # why, in the user's words
    outfit_id: Optional[int] = Field(default=None, foreign_key="outfit.id", ondelete="SET NULL")

    @property
    def ids(self) -> List[int]:
        return [int(x) for x in self.item_ids.split(",") if x.strip().isdigit()]

