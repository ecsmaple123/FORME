"""fabric: item.fabric, filled from fabric words in existing names (which are then removed)

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

from app.services.fabric import split_name

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("item") as batch:
        batch.add_column(sa.Column("fabric", sa.String(80), nullable=False, server_default=""))
    conn = op.get_bind()
    for item_id, name in conn.execute(sa.text("SELECT id, name FROM item")).fetchall():
        rest, fabric = split_name(name)
        if fabric:
            conn.execute(sa.text("UPDATE item SET name = :n, fabric = :f WHERE id = :i"),
                         {"n": rest, "f": fabric, "i": item_id})


def downgrade() -> None:
    # Put the fabric back in front of the name, so nothing is lost.
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE item SET name = fabric || ' ' || name WHERE fabric != ''"))
    with op.batch_alter_table("item") as batch:
        batch.drop_column("fabric")
