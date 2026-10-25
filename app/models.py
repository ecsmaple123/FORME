"""Database tables. The schema itself is owned by Alembic (migrations/); keep both in sync."""
from datetime import datetime
from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel

SEASONS = ["spring", "summer", "autumn", "winter"]
PHOTO_KINDS = {"product": "Product photo", "real": "Real photo", "detail": "Detail", "other": "Other"}
MAX_PHOTOS = 12
# Background removal per photo: pending -> done (cutout made) | none (no clear subject) | failed
CUTOUT_STATES = ("pending", "done", "none", "failed")


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
    """One photo of an item. Files: data/images/{orig,display,thumb}/<image_file>.*, and once the
    background is removed data/images/cutout/<cutout_file>.webp + .thumb.webp (made by app.worker)."""
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
    show_cutout: bool = True  # the user can switch back to the photo with its background
    created_at: datetime = Field(default_factory=utcnow)

    item: Optional[Item] = Relationship(back_populates="photos")

    @property
    def kind_label(self) -> str:
        return PHOTO_KINDS.get(self.kind, "Other")

    @property
    def cutout_shown(self) -> Optional[str]:
        """The cutout's file name if it exists and should be shown instead of the photo."""
        if self.show_cutout and self.cutout_status == "done" and self.cutout_file:
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


class Outfit(SQLModel, table=True):
    """Not used by the MVP UI yet; here so outfits need no schema rework later."""
    __tablename__ = "outfit"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=200)
    notes: str = Field(default="", max_length=4000)
    occasion: str = Field(default="", max_length=80)
    season: str = Field(default="", max_length=60)
    source: str = Field(default="manual", max_length=20)  # manual | ai | photo-import
    created_at: datetime = Field(default_factory=utcnow)


class OutfitItem(SQLModel, table=True):
    __tablename__ = "outfit_item"
    outfit_id: int = Field(foreign_key="outfit.id", primary_key=True, ondelete="CASCADE")
    item_id: int = Field(foreign_key="item.id", primary_key=True, ondelete="CASCADE")
    position: int = 0
