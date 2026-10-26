"""touch-ups: white balance per photo, and photos whose cutout the user edited by hand

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("item_photo") as batch:
        batch.add_column(sa.Column("white_balance", sa.String(40), nullable=False, server_default=""))
        batch.add_column(sa.Column("touched_up", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("item_photo") as batch:
        batch.drop_column("touched_up")
        batch.drop_column("white_balance")
