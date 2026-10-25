"""multiple photos per item: move image columns from item to item_photo

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

IMAGE_COLUMNS = ["image_file", "image_ext", "image_sha256", "width", "height", "cutout_file"]


def upgrade() -> None:
    op.create_table(
        "item_photo",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("item.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("kind", sa.String(20), nullable=False, server_default="product"),
        sa.Column("image_file", sa.String(64), nullable=False),
        sa.Column("image_ext", sa.String(8), nullable=False, server_default="jpg"),
        sa.Column("image_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("width", sa.Integer, nullable=False, server_default="0"),
        sa.Column("height", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cutout_file", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_item_photo_item_id", "item_photo", ["item_id"])
    # Each existing item's single photo becomes its cover. The source isn't known, so the photo type is "product".
    op.execute(
        "INSERT INTO item_photo (item_id, position, kind, image_file, image_ext, image_sha256, "
        "width, height, cutout_file, created_at) "
        "SELECT id, 0, 'product', image_file, image_ext, image_sha256, width, height, "
        "cutout_file, created_at FROM item WHERE image_file != ''"
    )
    with op.batch_alter_table("item") as batch:
        for col in IMAGE_COLUMNS:
            batch.drop_column(col)


def downgrade() -> None:
    with op.batch_alter_table("item") as batch:
        batch.add_column(sa.Column("image_file", sa.String(64), nullable=False, server_default=""))
        batch.add_column(sa.Column("image_ext", sa.String(8), nullable=False, server_default="jpg"))
        batch.add_column(sa.Column("image_sha256", sa.String(64), nullable=False, server_default=""))
        batch.add_column(sa.Column("width", sa.Integer, nullable=False, server_default="0"))
        batch.add_column(sa.Column("height", sa.Integer, nullable=False, server_default="0"))
        batch.add_column(sa.Column("cutout_file", sa.String(64), nullable=True))
    # Keep the cover only; other photos' files stay on disk (the startup cleanup removes them).
    op.execute(
        "UPDATE item SET (image_file, image_ext, image_sha256, width, height, cutout_file) = "
        "(SELECT image_file, image_ext, image_sha256, width, height, cutout_file FROM item_photo p "
        " WHERE p.item_id = item.id ORDER BY position LIMIT 1) "
        "WHERE EXISTS (SELECT 1 FROM item_photo p WHERE p.item_id = item.id)"
    )
    op.drop_table("item_photo")
