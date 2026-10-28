"""BankPayment: one credit read from a bank file (tenant schema)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hubra.core.extensions import db

# matched: invoice marked paid; unmatched: no invoice for the reference;
# mismatch: amount differs from the invoice; duplicate_payment: the invoice
# was already paid; assigned: matched by hand later.
PAYMENT_STATUSES = ("matched", "unmatched", "mismatch", "duplicate_payment", "assigned")


class BankPayment(db.Model):
    __tablename__ = "bank_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The bank's own reference for the booking, so re-importing a file
    # (or overlapping files) books nothing twice.
    bank_reference: Mapped[str] = mapped_column(
        db.String(120), nullable=False, unique=True
    )
    qr_reference: Mapped[str | None] = mapped_column(
        db.String(35), nullable=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(db.String(3), nullable=False)
    booked_on: Mapped[date] = mapped_column(Date, nullable=False)
    debtor_name: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    remittance: Mapped[str | None] = mapped_column(db.String(500), nullable=True)
    status: Mapped[str] = mapped_column(db.String(20), nullable=False)
    invoice_id: Mapped[int | None] = mapped_column(
        db.Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    file_name: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    invoice = relationship("Invoice")
