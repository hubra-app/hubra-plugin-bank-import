"""bank_payments: credits imported from camt.054 files

Databases that ran Hubra's own revision 1894b9307388 have the table
already; it is kept as it is.

Revision ID: 34f6bf1bb6de
Revises:
Create Date: 2026-10-28 10:00:00

"""

from alembic import op
import sqlalchemy as sa

from hubra.core.plugins.ops import has_table


# revision identifiers, used by Alembic.
revision = "34f6bf1bb6de"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    if has_table("bank_payments"):
        return
    op.create_table(
        "bank_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bank_reference", sa.String(length=120), nullable=False),
        sa.Column("qr_reference", sa.String(length=35), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("booked_on", sa.Date(), nullable=False),
        sa.Column("debtor_name", sa.String(length=255), nullable=True),
        sa.Column("remittance", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bank_reference"),
    )
    with op.batch_alter_table("bank_payments", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_bank_payments_qr_reference"), ["qr_reference"], unique=False
        )


def downgrade():
    # Dropping a table drops its indexes; club schemas cloned from public
    # name them differently, so they are not dropped by name.
    op.drop_table("bank_payments")
