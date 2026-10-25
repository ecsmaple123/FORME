"""stylist: suggestions from the AI stylist and the user's likes and dislikes

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "suggestion",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("source", sa.String(10), nullable=False, server_default="stylist"),
        sa.Column("day", sa.String(10), nullable=False, server_default=""),
        sa.Column("replaced", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("request", sa.String(300), nullable=False, server_default=""),
        sa.Column("weather", sa.String(200), nullable=False, server_default=""),
        sa.Column("title", sa.String(120), nullable=False, server_default=""),
        sa.Column("reason", sa.String(600), nullable=False, server_default=""),
        sa.Column("item_ids", sa.String(400), nullable=False, server_default=""),
        sa.Column("verdict", sa.String(10), nullable=False, server_default=""),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.Column("outfit_id", sa.Integer, sa.ForeignKey("outfit.id", ondelete="SET NULL"),
                  nullable=True),
    )
    op.create_index("ix_suggestion_created_at", "suggestion", ["created_at"])
    op.create_index("ix_suggestion_day", "suggestion", ["day"])


def downgrade() -> None:
    op.drop_index("ix_suggestion_day", "suggestion")
    op.drop_index("ix_suggestion_created_at", "suggestion")
    op.drop_table("suggestion")
