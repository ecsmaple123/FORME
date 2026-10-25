"""stylist notes: feedback the user gives the stylist directly

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stylist_note",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("text", sa.String(300), nullable=False, server_default=""),
    )
    op.create_index("ix_stylist_note_created_at", "stylist_note", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_stylist_note_created_at", "stylist_note")
    op.drop_table("stylist_note")
