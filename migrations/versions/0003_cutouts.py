"""background removal: cutout status + per-photo "show cutout" switch

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing photos start as "pending", so the cutout worker processes them too.
    with op.batch_alter_table("item_photo") as batch:
        batch.add_column(sa.Column("cutout_status", sa.String(12), nullable=False,
                                   server_default="pending"))
        batch.add_column(sa.Column("show_cutout", sa.Boolean, nullable=False,
                                   server_default=sa.true()))
    op.create_index("ix_item_photo_cutout_status", "item_photo", ["cutout_status"])


def downgrade() -> None:
    op.drop_index("ix_item_photo_cutout_status", "item_photo")
    with op.batch_alter_table("item_photo") as batch:
        batch.drop_column("show_cutout")
        batch.drop_column("cutout_status")
