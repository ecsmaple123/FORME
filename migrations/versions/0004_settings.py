"""settings: key/value preferences (name, theme, weather location, units)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setting",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("value", sa.String(500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("setting")
