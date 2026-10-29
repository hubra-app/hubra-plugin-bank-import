"""Book bank statement lines.

Matching runs in this order for each new line:

1. QR reference (QRR) -> invoice, marked paid when the amount fits.
2. Amount plus a known payer (the member's name, or an IBAN the member paid
   from before) -> one open invoice: a suggestion the treasurer confirms.
3. The club's rules -> a finance transaction in the rule's category.
4. Anything else waits in the review queue.

Hubra's invoices only carry QR references, so a creditor reference (SCOR)
is kept on the line but goes through steps 2 to 4.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from sqlalchemy import select

from hubra.api.finance.services import InvoiceService, _link_pending_transaction
from hubra.api.utils import log_audit
from hubra.core.errors import raise_error
from hubra.core.extensions import db
from hubra.core.models.finance import Invoice, Transaction, TransactionCategory
from hubra.core.models.qrr_reference import QrrReference

from .lines import BankLine, Statement
from .models import (
    DIRECTIONS,
    OPEN_STATUSES,
    RULE_FIELDS,
    BankCsvProfile,
    BankPayment,
    BankRule,
)

SUMMARY_KEYS = (
    "matched",
    "suggested",
    "booked",
    "unmatched",
    "mismatch",
    "duplicate_payment",
    "batch",
    "already_imported",
)


def payment_to_dict(p: BankPayment) -> dict:
    return {
        "id": p.id,
        "bankReference": p.bank_reference,
        "direction": p.direction,
        "reference": p.reference,
        "referenceType": p.reference_type,
        # Kept for API clients written against the camt.054-only version.
        "qrReference": p.reference if p.reference_type == "QRR" else None,
        "amount": str(p.amount),
        "currency": p.currency,
        "bookedOn": p.booked_on.isoformat(),
        "valueDate": p.value_date.isoformat() if p.value_date else None,
        "counterpartyName": p.counterparty_name,
        "debtorName": p.counterparty_name,
        "counterpartyIban": p.counterparty_iban,
        "accountIban": p.account_iban,
        "remittance": p.remittance,
        "reversal": p.reversal,
        "status": p.status,
        "invoiceId": p.invoice_id,
        "suggestedInvoiceId": p.suggested_invoice_id,
        "transactionId": p.transaction_id,
        "ruleId": p.rule_id,
        "fileName": p.file_name,
        "fileFormat": p.file_format,
        "importedAt": p.imported_at.isoformat() if p.imported_at else None,
    }


def rule_to_dict(r: BankRule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "direction": r.direction,
        "matchField": r.match_field,
        "pattern": r.pattern,
        "categoryId": r.category_id,
        "categoryName": r.category.name if r.category else None,
        "description": r.description,
        "active": r.active,
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
            # The books hold what arrived; a payment assigned by hand may
            # differ from the invoice (a "mismatch" the treasurer accepted).
            tx.amount = payment.amount
        payment.transaction_id = invoice.transaction_id


def _book(
    payment: BankPayment, category_id: int, description: str | None
) -> Transaction:
    text = description or payment.remittance or payment.counterparty_name
    tx = Transaction(
        date=payment.booked_on,
        description=(text or "Bank booking")[:255],
        category_id=category_id,
        payee_name=payment.counterparty_name,
        # Expenses are stored negative, as the finance screens create them.
        amount=payment.amount if payment.direction == "credit" else -payment.amount,
        method="IBAN",
        type="income" if payment.direction == "credit" else "expense",
        status="Completed",
    )
    db.session.add(tx)
    db.session.flush()
    payment.transaction_id = tx.id
    payment.status = "booked"
    return tx


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    return {t for t in re.split(r"[^a-z0-9]+", text) if len(t) > 1}


def _payer_names(invoice: Invoice) -> list[str]:
    names = []
    member = invoice.member
    if member is not None and member.user is not None:
        names.append(f"{member.user.first_name} {member.user.last_name}")
    if invoice.external_party is not None:
        names.append(invoice.external_party.name)
    return names


def _payer_key(invoice: Invoice) -> tuple[str, int] | None:
    if invoice.member_id:
        return ("member", invoice.member_id)
    if invoice.external_party_id:
        return ("external", invoice.external_party_id)
    return None


class _Matcher:
    """Loads what matching needs once per import."""

    def __init__(self):
        self.open_by_amount: dict = defaultdict(list)
        for inv in db.session.scalars(
            select(Invoice).where(Invoice.status.in_(("Open", "Overdue")))
        ):
            self.open_by_amount[inv.amount].append(inv)
        # IBAN -> payers it paid invoices for before.
        self.iban_payers: dict[str, set] = defaultdict(set)
        rows = db.session.execute(
            select(
                BankPayment.counterparty_iban,
                Invoice.member_id,
                Invoice.external_party_id,
            )
            .join(Invoice, Invoice.id == BankPayment.invoice_id)
            .where(BankPayment.counterparty_iban.is_not(None))
        )
        for iban, member_id, external_id in rows:
            if member_id:
                self.iban_payers[iban].add(("member", member_id))
            elif external_id:
                self.iban_payers[iban].add(("external", external_id))
        self.rules = list(
            db.session.scalars(
                select(BankRule).where(BankRule.active.is_(True)).order_by(BankRule.id)
            )
        )
        # Invoices already claimed by an earlier line of the same file.
        self.claimed: set[int] = set()

    def suggest(self, line: BankLine) -> Invoice | None:
        if line.currency != "CHF":
            return None
        payer_tokens = _tokens(line.counterparty_name)
        known = self.iban_payers.get(line.counterparty_iban or "", set())
        hits = []
        for inv in self.open_by_amount.get(line.amount, []):
            if inv.id in self.claimed:
                continue
            if _payer_key(inv) in known:
                hits.append(inv)
                continue
            for name in _payer_names(inv):
                wanted = _tokens(name)
                if wanted and wanted <= payer_tokens:
                    hits.append(inv)
                    break
        return hits[0] if len(hits) == 1 else None

    def rule(self, line: BankLine) -> BankRule | None:
        fields = {
            "counterparty": line.counterparty_name or "",
            "text": line.remittance or "",
            "iban": line.counterparty_iban or "",
        }
        fields["any"] = " ".join(fields.values())
        for rule in self.rules:
            if rule.direction != "any" and rule.direction != line.direction:
                continue
            haystack = fields.get(rule.match_field, fields["any"]).casefold()
            needle = rule.pattern.casefold()
            if rule.match_field == "iban":
                haystack, needle = haystack.replace(" ", ""), needle.replace(" ", "")
            if needle and needle in haystack:
                return rule
        return None

    def classify(
        self, line: BankLine
    ) -> tuple[str, Invoice | None, Invoice | None, BankRule | None]:
        """(status, invoice, suggested invoice, rule)"""
        if line.batch:
            return "batch", None, None, None
        if line.direction == "credit" and not line.reversal:
            if line.reference_type == "QRR":
                invoice = _invoice_for(line.reference)
                if invoice is not None:
                    if invoice.status == "Paid" or invoice.id in self.claimed:
                        return "duplicate_payment", invoice, None, None
                    if line.currency != "CHF" or line.amount != invoice.amount:
                        return "mismatch", invoice, None, None
                    self.claimed.add(invoice.id)
                    return "matched", invoice, None, None
            suggested = self.suggest(line)
            if suggested is not None:
                self.claimed.add(suggested.id)
                return "suggested", None, suggested, None
        rule = self.rule(line)
        if rule is not None:
            return "booked", None, None, rule
        return "unmatched", None, None, None


def _item(line: BankLine, status, invoice, suggested, rule) -> dict:
    target = invoice or suggested
    return {
        "bankReference": line.bank_reference,
        "direction": line.direction,
        "reference": line.reference,
        "referenceType": line.reference_type,
        "qrReference": line.reference if line.reference_type == "QRR" else None,
        "amount": str(line.amount),
        "currency": line.currency,
        "bookedOn": line.booked_on.isoformat(),
        "counterpartyName": line.counterparty_name,
        "debtorName": line.counterparty_name,
        "remittance": line.remittance,
        "status": status,
        "invoiceId": invoice.id if invoice else None,
        "suggestedInvoiceId": suggested.id if suggested else None,
        "invoiceAmount": str(target.amount) if target else None,
        "ruleId": rule.id if rule else None,
        "ruleName": rule.name if rule else None,
    }


class BankImportService:
    @staticmethod
    def import_statement(
        statement: Statement,
        file_name: str | None,
        actor_id: int,
        dry_run: bool,
    ) -> dict:
        lines = statement.lines
        known = set(
            db.session.scalars(
                select(BankPayment.bank_reference).where(
                    BankPayment.bank_reference.in_([ln.bank_reference for ln in lines])
                )
            )
        )
        matcher = _Matcher()
        summary = dict.fromkeys(SUMMARY_KEYS, 0)
        items = []
        for line in lines:
            if line.bank_reference in known:
                summary["already_imported"] += 1
                continue
            known.add(line.bank_reference)
            status, invoice, suggested, rule = matcher.classify(line)
            summary[status] += 1
            items.append(_item(line, status, invoice, suggested, rule))
            if dry_run:
                continue
            payment = BankPayment(
                bank_reference=line.bank_reference,
                direction=line.direction,
                reference=line.reference,
                reference_type=line.reference_type,
                amount=line.amount,
                currency=line.currency,
                booked_on=line.booked_on,
                value_date=line.value_date,
                counterparty_name=line.counterparty_name,
                counterparty_iban=line.counterparty_iban,
                account_iban=line.account_iban,
                remittance=line.remittance,
                reversal=line.reversal,
                status=status,
                invoice_id=invoice.id if invoice else None,
                suggested_invoice_id=suggested.id if suggested else None,
                rule_id=rule.id if rule else None,
                file_name=file_name,
                file_format=statement.format,
            )
            db.session.add(payment)
            db.session.flush()
            if status == "matched":
                _mark_paid(invoice, payment, actor_id)
            elif status == "booked":
                _book(payment, rule.category_id, rule.description)
        if not dry_run:
            log_audit(
                actor_id,
                "import_bank_file",
                "BankPayment",
                None,
                f"{file_name or statement.format}: {summary['matched']} matched, "
                f"{summary['booked']} booked, "
                f"{summary['suggested'] + summary['unmatched'] + summary['mismatch']} to check",
            )
        return {
            "dryRun": dry_run,
            "format": statement.format,
            "summary": summary,
            "balances": [
                {
                    "accountIban": b.account_iban,
                    "opening": str(b.opening),
                    "closing": str(b.closing),
                    "movement": str(b.movement),
                    "ok": b.ok,
                }
                for b in statement.balances
            ],
            "items": items,
        }

    @staticmethod
    def list(
        status: str | None = None, direction: str | None = None, open_only: bool = False
    ) -> list[BankPayment]:
        q = select(BankPayment).order_by(
            BankPayment.booked_on.desc(), BankPayment.id.desc()
        )
        if status:
            q = q.where(BankPayment.status == status)
        if open_only:
            q = q.where(BankPayment.status.in_(OPEN_STATUSES))
        if direction:
            q = q.where(BankPayment.direction == direction)
        return list(db.session.scalars(q.limit(500)))

    @staticmethod
    def _open(payment_id: int) -> BankPayment:
        payment = db.session.get(BankPayment, payment_id)
        if payment is None:
            raise_error(404, "NOT_FOUND", "Payment not found")
        if payment.status not in OPEN_STATUSES:
            raise_error(409, "CONFLICT", "This payment is already booked")
        return payment

    @staticmethod
    def assign(payment_id: int, invoice_id: int, actor_id: int) -> BankPayment:
        """Match a payment that was not matched automatically by hand."""
        payment = BankImportService._open(payment_id)
        if payment.direction != "credit":
            raise_error(409, "CONFLICT", "Only incoming payments can pay an invoice")
        invoice = db.session.get(Invoice, invoice_id)
        if invoice is None:
            raise_error(404, "NOT_FOUND", "Invoice not found")
        if invoice.status == "Paid":
            raise_error(409, "CONFLICT", "This invoice is already paid")
        payment.invoice_id = invoice.id
        payment.suggested_invoice_id = None
        payment.status = "assigned"
        _mark_paid(invoice, payment, actor_id)
        db.session.flush()
        return payment

    @staticmethod
    def confirm(payment_id: int, actor_id: int) -> BankPayment:
        """Accept the suggested invoice."""
        payment = BankImportService._open(payment_id)
        if payment.suggested_invoice_id is None:
            raise_error(409, "CONFLICT", "This payment has no suggestion")
        return BankImportService.assign(
            payment_id, payment.suggested_invoice_id, actor_id
        )

    @staticmethod
    def book(
        payment_id: int, category_id: int, description: str | None, actor_id: int
    ) -> BankPayment:
        """Put a line in the books without an invoice (expense, donation...)."""
        payment = BankImportService._open(payment_id)
        if db.session.get(TransactionCategory, category_id) is None:
            raise_error(404, "NOT_FOUND", "Category not found")
        payment.suggested_invoice_id = None
        tx = _book(payment, category_id, description)
        log_audit(actor_id, "book_bank_payment", "Transaction", tx.id, tx.description)
        return payment

    @staticmethod
    def ignore(payment_id: int, actor_id: int) -> BankPayment:
        payment = BankImportService._open(payment_id)
        payment.status = "ignored"
        payment.suggested_invoice_id = None
        log_audit(
            actor_id,
            "ignore_bank_payment",
            "BankPayment",
            payment.id,
            payment.bank_reference,
        )
        db.session.flush()
        return payment


class RuleService:
    @staticmethod
    def validate(data: dict, partial: bool = False) -> dict:
        out = {}
        for key, field in (
            ("name", "name"),
            ("pattern", "pattern"),
            ("description", "description"),
        ):
            if key in data:
                if data[key] is not None and not isinstance(data[key], str):
                    raise_error(400, "VALIDATION_ERROR", f"{key} must be text")
                value = (data.get(key) or "").strip()
                out[field] = value or None
        if "direction" in data:
            if data["direction"] not in (*DIRECTIONS, "any"):
                raise_error(
                    400, "VALIDATION_ERROR", "direction is credit, debit or any"
                )
            out["direction"] = data["direction"]
        if "matchField" in data:
            if data["matchField"] not in RULE_FIELDS:
                raise_error(400, "VALIDATION_ERROR", "Unknown matchField")
            out["match_field"] = data["matchField"]
        if "categoryId" in data:
            if db.session.get(TransactionCategory, data["categoryId"]) is None:
                raise_error(404, "NOT_FOUND", "Category not found")
            out["category_id"] = data["categoryId"]
        if "active" in data:
            out["active"] = bool(data["active"])
        if not partial:
            for required in ("name", "pattern", "category_id"):
                if not out.get(required):
                    raise_error(400, "VALIDATION_ERROR", f"{required} is required")
            out.setdefault("direction", "any")
            out.setdefault("match_field", "any")
        elif (
            "name" in out and not out["name"] or "pattern" in out and not out["pattern"]
        ):
            raise_error(400, "VALIDATION_ERROR", "name and pattern can't be empty")
        if out.get("name"):
            out["name"] = out["name"][:120]
        if out.get("pattern"):
            out["pattern"] = out["pattern"][:255]
        return out

    @staticmethod
    def list() -> list[BankRule]:
        return list(db.session.scalars(select(BankRule).order_by(BankRule.id)))

    @staticmethod
    def create(data: dict) -> BankRule:
        rule = BankRule(**RuleService.validate(data))
        db.session.add(rule)
        db.session.flush()
        return rule

    @staticmethod
    def update(rule_id: int, data: dict) -> BankRule:
        rule = db.session.get(BankRule, rule_id)
        if rule is None:
            raise_error(404, "NOT_FOUND", "Rule not found")
        for key, value in RuleService.validate(data, partial=True).items():
            setattr(rule, key, value)
        db.session.flush()
        return rule

    @staticmethod
    def delete(rule_id: int) -> None:
        rule = db.session.get(BankRule, rule_id)
        if rule is None:
            raise_error(404, "NOT_FOUND", "Rule not found")
        db.session.delete(rule)
        db.session.flush()


class CsvProfileService:
    @staticmethod
    def get(signature: str) -> dict | None:
        row = db.session.scalar(
            select(BankCsvProfile).where(BankCsvProfile.signature == signature)
        )
        return dict(row.mapping) if row else None

    @staticmethod
    def save(signature: str, mapping: dict) -> None:
        row = db.session.scalar(
            select(BankCsvProfile).where(BankCsvProfile.signature == signature)
        )
        if row is None:
            db.session.add(BankCsvProfile(signature=signature, mapping=mapping))
        else:
            row.mapping = mapping
        db.session.flush()
