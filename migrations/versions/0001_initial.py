"""initial schema: categories, items, tags, colors, outfits

Revision ID: 0001
Revises:
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

DEFAULT_CATEGORIES = [
    "Tops", "Bottoms", "Dresses/One-pieces", "Outerwear", "Shoes",
    "Accessories", "Bags", "Activewear", "Underwear/Sleepwear",
]


def upgrade() -> None:
    category = op.create_table(
        "category",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(60), nullable=False, unique=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "tag",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(40), nullable=False, unique=True),
    )
    op.create_table(
        "item",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category_id", sa.Integer,
                  sa.ForeignKey("category.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subcategory", sa.String(80), nullable=False, server_default=""),
        sa.Column("color_hex", sa.String(7), nullable=False, server_default=""),
        sa.Column("color_name", sa.String(40), nullable=False, server_default=""),
        sa.Column("brand", sa.String(100), nullable=False, server_default=""),
        sa.Column("size", sa.String(40), nullable=False, server_default=""),
        sa.Column("seasons", sa.String(60), nullable=False, server_default=""),
        sa.Column("notes", sa.String(4000), nullable=False, server_default=""),
        sa.Column("source_url", sa.String(2000), nullable=False, server_default=""),
        sa.Column("image_file", sa.String(64), nullable=False, server_default=""),
        sa.Column("image_ext", sa.String(8), nullable=False, server_default="jpg"),
        sa.Column("image_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("width", sa.Integer, nullable=False, server_default="0"),
        sa.Column("height", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cutout_file", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_item_category_id", "item", ["category_id"])
    op.create_index("ix_item_created_at", "item", ["created_at"])
    op.create_table(
        "item_tag",
        sa.Column("item_id", sa.Integer, sa.ForeignKey("item.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("tag_id", sa.Integer, sa.ForeignKey("tag.id", ondelete="CASCADE"),
                  primary_key=True),
    )
    op.create_table(
        "item_color",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("item.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("hex", sa.String(7), nullable=False),
        sa.Column("share", sa.Float, nullable=False),
        sa.Column("lab_l", sa.Float, nullable=False),
        sa.Column("lab_a", sa.Float, nullable=False),
        sa.Column("lab_b", sa.Float, nullable=False),
        sa.Column("hue", sa.Float, nullable=False),
    )
    op.create_index("ix_item_color_item_id", "item_color", ["item_id"])
    op.create_table(
        "outfit",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("notes", sa.String(4000), nullable=False, server_default=""),
        sa.Column("occasion", sa.String(80), nullable=False, server_default=""),
        sa.Column("season", sa.String(60), nullable=False, server_default=""),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "outfit_item",
        sa.Column("outfit_id", sa.Integer, sa.ForeignKey("outfit.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("item.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
    )
    op.bulk_insert(category, [
        {"name": name, "sort_order": i * 10} for i, name in enumerate(DEFAULT_CATEGORIES)
    ])


def downgrade() -> None:
    for table in ("outfit_item", "outfit", "item_color", "item_tag", "item", "tag", "category"):
        op.drop_table(table)
