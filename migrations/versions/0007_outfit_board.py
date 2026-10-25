"""outfits: where each item sits on the Studio board, and when an outfit was last changed

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("outfit_item") as batch:
        batch.add_column(sa.Column("x", sa.Float, nullable=False, server_default="0"))
        batch.add_column(sa.Column("y", sa.Float, nullable=False, server_default="0"))
        batch.add_column(sa.Column("w", sa.Float, nullable=False, server_default="0.4"))
    with op.batch_alter_table("outfit") as batch:
        batch.add_column(sa.Column("updated_at", sa.DateTime, nullable=True))
    op.execute("UPDATE outfit SET updated_at = created_at")
    op.create_index("ix_outfit_created_at", "outfit", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_outfit_created_at", "outfit")
    with op.batch_alter_table("outfit") as batch:
        batch.drop_column("updated_at")
    with op.batch_alter_table("outfit_item") as batch:
        batch.drop_column("w")
        batch.drop_column("y")
        batch.drop_column("x")
