"""bank statements: debits, rules and CSV profiles

bank_payments now holds every booking of a statement (camt.053/052/054,
MT940, CSV), money in and out, with the transaction it was booked as.

Revision ID: a77fc2bce2f6
Revises: 34f6bf1bb6de
Create Date: 2026-10-28 12:00:00

"""

from alembic import op
import sqlalchemy as sa

from hubra.core.plugins.ops import columns, has_table


# revision identifiers, used by Alembic.
revision = "a77fc2bce2f6"
down_revision = "34f6bf1bb6de"
branch_labels = None
depends_on = None

_NEW_COLUMNS = (
    "direction",
    "reference_type",
    "value_date",
    "counterparty_iban",
    "account_iban",
    "reversal",
    "suggested_invoice_id",
    "transaction_id",
    "rule_id",
    "file_format",
)


def upgrade():
    if not has_table("bank_rules"):
        op.create_table(
            "bank_rules",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("direction", sa.String(length=10), nullable=False),
            sa.Column("match_field", sa.String(length=20), nullable=False),
            sa.Column("pattern", sa.String(length=255), nullable=False),
            sa.Column("category_id", sa.Integer(), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["category_id"], ["transaction_categories.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    if not has_table("bank_csv_profiles"):
        op.create_table(
            "bank_csv_profiles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("signature", sa.String(length=32), nullable=False),
            sa.Column("mapping", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("signature"),
        )
    present = columns("bank_payments")
    if "direction" in present:
        return
    with op.batch_alter_table("bank_payments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "direction",
                sa.String(length=10),
                server_default="credit",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("reference_type", sa.String(length=4), nullable=True)
        )
        batch_op.add_column(sa.Column("value_date", sa.Date(), nullable=True))
        batch_op.add_column(
            sa.Column("counterparty_iban", sa.String(length=34), nullable=True)
        )
        batch_op.add_column(
            sa.Column("account_iban", sa.String(length=34), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "reversal", sa.Boolean(), server_default=sa.false(), nullable=False
            )
        )
        batch_op.add_column(
            sa.Column("suggested_invoice_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(sa.Column("transaction_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("rule_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("file_format", sa.String(length=10), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_bank_payments_suggested_invoice",
            "invoices",
            ["suggested_invoice_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_bank_payments_transaction",
            "transactions",
            ["transaction_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_bank_payments_rule",
            "bank_rules",
            ["rule_id"],
            ["id"],
            ondelete="SET NULL",
        )
    # Every row so far came from a camt.054 file.
    op.execute("UPDATE bank_payments SET file_format = 'camt.054'")
    op.execute(
        "UPDATE bank_payments SET reference_type = 'QRR' WHERE qr_reference IS NOT NULL"
    )


def downgrade():
    with op.batch_alter_table("bank_payments", schema=None) as batch_op:
        for name in (
            "fk_bank_payments_rule",
            "fk_bank_payments_transaction",
            "fk_bank_payments_suggested_invoice",
        ):
            batch_op.drop_constraint(name, type_="foreignkey")
        for column in reversed(_NEW_COLUMNS):
            batch_op.drop_column(column)
    op.drop_table("bank_csv_profiles")
    op.drop_table("bank_rules")
