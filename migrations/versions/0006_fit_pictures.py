"""photo types: only item photos and fit pictures; no switch back to the photo with its background

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # "Real photo" becomes a fit picture (keeps its background); detail/other become item photos.
    conn.execute(sa.text("UPDATE item_photo SET kind = 'fit' WHERE kind = 'real'"))
    conn.execute(sa.text("UPDATE item_photo SET kind = 'product' WHERE kind != 'fit'"))
    # Fit pictures are never cut out; their old cutout files are removed by the startup cleanup.
    conn.execute(sa.text("UPDATE item_photo SET cutout_status = 'skip', cutout_file = NULL "
                         "WHERE kind = 'fit'"))
    with op.batch_alter_table("item_photo") as batch:
        batch.drop_column("show_cutout")


def downgrade() -> None:
    # Photos whose background was removed don't get it back (only the cutout was kept).
    with op.batch_alter_table("item_photo") as batch:
        batch.add_column(sa.Column("show_cutout", sa.Boolean, nullable=False,
                                   server_default=sa.true()))
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE item_photo SET cutout_status = 'none' WHERE cutout_status = 'skip'"))
    conn.execute(sa.text("UPDATE item_photo SET kind = 'real' WHERE kind = 'fit'"))
