"""Bank import tables (tenant schema).

BankPayment: one booking read from a bank file, money in or out.
BankRule: books recurring lines (rent, phone, a sponsor) into a category.
BankCsvProfile: the column mapping of one bank's CSV layout.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Numeric, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hubra.core.extensions import db

# matched: QR reference found, invoice marked paid; assigned: matched by
# hand later; suggested: amount and payer fit one open invoice, waiting for
# the treasurer; booked: a rule or the treasurer put it in the books;
# unmatched: nothing found; mismatch: the invoice amount differs;
# duplicate_payment: the invoice was already paid; ignored: left out of the
# books on purpose; batch: a collective booking whose details come in a
# camt.054.
PAYMENT_STATUSES = (
    "matched",
    "assigned",
    "suggested",
    "booked",
    "unmatched",
    "mismatch",
    "duplicate_payment",
    "ignored",
    "batch",
)
# Lines the treasurer still has to look at.
OPEN_STATUSES = ("suggested", "unmatched", "mismatch")
DIRECTIONS = ("credit", "debit")
RULE_FIELDS = ("counterparty", "text", "iban", "any")


class BankPayment(db.Model):
    __tablename__ = "bank_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The bank's own reference for the booking, so re-importing a file
    # (or overlapping files) books nothing twice.
    bank_reference: Mapped[str] = mapped_column(
        db.String(120), nullable=False, unique=True
    )
    direction: Mapped[str] = mapped_column(
        db.String(10), nullable=False, default="credit", server_default="credit"
    )
    # The columns kept their camt.054-era names: they now hold any payment
    # reference (QRR or SCOR) and the other party of a credit or a debit.
    reference: Mapped[str | None] = mapped_column(
        "qr_reference", db.String(35), nullable=True, index=True
    )
    reference_type: Mapped[str | None] = mapped_column(db.String(4), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(db.String(3), nullable=False)
    booked_on: Mapped[date] = mapped_column(Date, nullable=False)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(
        "debtor_name", db.String(255), nullable=True
    )
    counterparty_iban: Mapped[str | None] = mapped_column(db.String(34), nullable=True)
    account_iban: Mapped[str | None] = mapped_column(db.String(34), nullable=True)
    remittance: Mapped[str | None] = mapped_column(db.String(500), nullable=True)
    reversal: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=False, server_default=false()
    )
    status: Mapped[str] = mapped_column(db.String(20), nullable=False)
    invoice_id: Mapped[int | None] = mapped_column(
        db.Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    suggested_invoice_id: Mapped[int | None] = mapped_column(
        db.Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    transaction_id: Mapped[int | None] = mapped_column(
        db.Integer, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    rule_id: Mapped[int | None] = mapped_column(
        db.Integer, ForeignKey("bank_rules.id", ondelete="SET NULL"), nullable=True
    )
    file_name: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    file_format: Mapped[str | None] = mapped_column(db.String(10), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    invoice = relationship("Invoice", foreign_keys=[invoice_id])
    suggested_invoice = relationship("Invoice", foreign_keys=[suggested_invoice_id])


class BankRule(db.Model):
    __tablename__ = "bank_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    # credit | debit | any
    direction: Mapped[str] = mapped_column(db.String(10), nullable=False)
    # Where to look for the pattern: counterparty | text | iban | any
    match_field: Mapped[str] = mapped_column(db.String(20), nullable=False)
    # Case-insensitive "contains".
    pattern: Mapped[str] = mapped_column(db.String(255), nullable=False)
    category_id: Mapped[int] = mapped_column(
        db.Integer,
        ForeignKey("transaction_categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Description for the booked transaction; empty uses the bank text.
    description: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    active: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    category = relationship("TransactionCategory")


class BankCsvProfile(db.Model):
    __tablename__ = "bank_csv_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    # csvimport.signature() of the header row.
    signature: Mapped[str] = mapped_column(db.String(32), nullable=False, unique=True)
    # field -> list of column names
    mapping: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
