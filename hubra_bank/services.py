"""Book camt.054 credits: match QR references to invoices and mark them paid."""

from __future__ import annotations

from sqlalchemy import select

from hubra.api.finance.services import InvoiceService, _link_pending_transaction
from hubra.api.utils import log_audit
from hubra.core.errors import raise_error
from hubra.core.extensions import db
from hubra.core.models.finance import Invoice, Transaction
from hubra.core.models.qrr_reference import QrrReference

from .camt import Credit
from .models import BankPayment


def payment_to_dict(p: BankPayment) -> dict:
    return {
        "id": p.id,
        "bankReference": p.bank_reference,
        "qrReference": p.qr_reference,
        "amount": str(p.amount),
        "currency": p.currency,
        "bookedOn": p.booked_on.isoformat(),
        "debtorName": p.debtor_name,
        "remittance": p.remittance,
        "status": p.status,
        "invoiceId": p.invoice_id,
        "fileName": p.file_name,
        "importedAt": p.imported_at.isoformat() if p.imported_at else None,
    }


def _invoice_for(reference: str | None) -> Invoice | None:
    if not reference:
        return None
    mapping = db.session.scalar(
        select(QrrReference).where(QrrReference.opaque_reference == reference)
    )
    return db.session.get(Invoice, mapping.invoice_id) if mapping else None


def _mark_paid(invoice: Invoice, payment: BankPayment, actor_id: int) -> None:
    if invoice.transaction_id is None:
        _link_pending_transaction(invoice, invoice.member_id)
    InvoiceService.update(invoice, {"status": "Paid"}, actor_id)
    if invoice.transaction_id is not None:
        tx = db.session.get(Transaction, invoice.transaction_id)
        if tx is not None:
            tx.date = payment.booked_on
            tx.method = "IBAN"
            tx.status = "Completed"


class BankImportService:
    @staticmethod
    def classify(credit: Credit) -> tuple[str, Invoice | None]:
        invoice = _invoice_for(credit.qr_reference)
        if invoice is None:
            return "unmatched", None
        if invoice.status == "Paid":
            return "duplicate_payment", invoice
        if credit.currency != "CHF" or credit.amount != invoice.amount:
            return "mismatch", invoice
        return "matched", invoice

    @staticmethod
    def import_credits(
        credits: list[Credit], file_name: str | None, actor_id: int, dry_run: bool
    ) -> dict:
        known = set(
            db.session.scalars(
                select(BankPayment.bank_reference).where(
                    BankPayment.bank_reference.in_([c.bank_reference for c in credits])
                )
            )
        )
        summary = {
            "matched": 0,
            "unmatched": 0,
            "mismatch": 0,
            "duplicate_payment": 0,
            "already_imported": 0,
        }
        items = []
        for credit in credits:
            if credit.bank_reference in known:
                summary["already_imported"] += 1
                continue
            known.add(credit.bank_reference)
            status, invoice = BankImportService.classify(credit)
            summary[status] += 1
            items.append(
                {
                    "bankReference": credit.bank_reference,
                    "qrReference": credit.qr_reference,
                    "amount": str(credit.amount),
                    "currency": credit.currency,
                    "bookedOn": credit.booked_on.isoformat(),
                    "debtorName": credit.debtor_name,
                    "status": status,
                    "invoiceId": invoice.id if invoice else None,
                    "invoiceAmount": str(invoice.amount) if invoice else None,
                }
            )
            if dry_run:
                continue
            payment = BankPayment(
                bank_reference=credit.bank_reference,
                qr_reference=credit.qr_reference,
                amount=credit.amount,
                currency=credit.currency,
                booked_on=credit.booked_on,
                debtor_name=credit.debtor_name,
                remittance=credit.remittance,
                status=status,
                invoice_id=invoice.id if invoice else None,
                file_name=file_name,
            )
            db.session.add(payment)
            db.session.flush()
            if status == "matched":
                _mark_paid(invoice, payment, actor_id)
        if not dry_run:
            log_audit(
                actor_id,
                "import_camt054",
                "BankPayment",
                None,
                f"{file_name or 'camt.054'}: {summary['matched']} matched, "
                f"{summary['unmatched'] + summary['mismatch']} to check",
            )
        return {"dryRun": dry_run, "summary": summary, "items": items}

    @staticmethod
    def list(status: str | None = None) -> list[BankPayment]:
        q = select(BankPayment).order_by(
            BankPayment.booked_on.desc(), BankPayment.id.desc()
        )
        if status:
            q = q.where(BankPayment.status == status)
        return list(db.session.scalars(q.limit(500)))

    @staticmethod
    def assign(payment_id: int, invoice_id: int, actor_id: int) -> BankPayment:
        """Match a payment that was not matched automatically by hand."""
        payment = db.session.get(BankPayment, payment_id)
        if payment is None:
            raise_error(404, "NOT_FOUND", "Payment not found")
        if payment.status not in ("unmatched", "mismatch"):
            raise_error(409, "CONFLICT", "This payment is already booked")
        invoice = db.session.get(Invoice, invoice_id)
        if invoice is None:
            raise_error(404, "NOT_FOUND", "Invoice not found")
        if invoice.status == "Paid":
            raise_error(409, "CONFLICT", "This invoice is already paid")
        payment.invoice_id = invoice.id
        payment.status = "assigned"
        _mark_paid(invoice, payment, actor_id)
        db.session.flush()
        return payment
