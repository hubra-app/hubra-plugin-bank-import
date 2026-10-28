"""One bank line, whatever file it came from.

The camt, MT940 and CSV readers all return a ``Statement``: its lines plus,
where the file states them, the opening and closing balances.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

MAX_BYTES = 10 * 1024 * 1024

QRR_RE = re.compile(r"^\d{27}$")
SCOR_RE = re.compile(r"^RF\d{2}[0-9A-Z]{1,21}$")
# A QR or creditor reference written somewhere in a free-text field.
_QRR_IN_TEXT = re.compile(r"(?<!\d)(\d{2}(?: ?\d{5}){5})(?!\d)")
_SCOR_IN_TEXT = re.compile(
    r"\b((?:RF|rf)\d{2}(?: ?[0-9A-Z]{4}){0,5}(?: ?[0-9A-Z]{1,4})?)\b"
)


class StatementError(ValueError):
    """The file can't be read; the message is shown to the user."""


@dataclass
class BankLine:
    bank_reference: str
    # credit: money in; debit: money out.  ``amount`` is always positive.
    direction: str
    amount: Decimal
    currency: str
    booked_on: date
    value_date: date | None = None
    reference: str | None = None
    # QRR | SCOR | None
    reference_type: str | None = None
    counterparty_name: str | None = None
    counterparty_iban: str | None = None
    remittance: str | None = None
    account_iban: str | None = None
    # A booking that undoes an earlier one (returned payment and the like).
    reversal: bool = False
    # A collective booking whose details come in a separate camt.054.
    batch: bool = False


@dataclass
class Balance:
    account_iban: str | None
    opening: Decimal
    closing: Decimal
    movement: Decimal

    @property
    def ok(self) -> bool:
        return self.opening + self.movement == self.closing


@dataclass
class Statement:
    format: str
    lines: list[BankLine] = field(default_factory=list)
    balances: list[Balance] = field(default_factory=list)


def _iso7064_ok(ref: str) -> bool:
    """The RF check digits (ISO 11649, mod 97)."""
    moved = ref[4:] + ref[:4]
    digits = "".join(str(int(c, 36)) for c in moved)
    return int(digits) % 97 == 1


def classify_reference(raw: str | None) -> tuple[str | None, str | None]:
    """Normalise a payment reference and say whether it is QRR or SCOR."""
    if not raw:
        return None, None
    ref = re.sub(r"\s+", "", raw).upper()
    if QRR_RE.match(ref):
        return ref, "QRR"
    if SCOR_RE.match(ref) and _iso7064_ok(ref):
        return ref, "SCOR"
    return ref[:35] or None, None


def reference_in_text(text: str | None) -> tuple[str | None, str | None]:
    """Find a QR or creditor reference inside a free-text booking text."""
    if not text:
        return None, None
    m = _QRR_IN_TEXT.search(text)
    if m:
        return classify_reference(m.group(1))
    m = _SCOR_IN_TEXT.search(text)
    if m:
        ref, kind = classify_reference(m.group(1))
        if kind:
            return ref, kind
    return None, None


def normalise_iban(raw: str | None) -> str | None:
    if not raw:
        return None
    iban = re.sub(r"\s+", "", raw).upper()
    return iban[:34] if re.match(r"^[A-Z]{2}\d{2}[0-9A-Z]+$", iban) else None


def derived_reference(*parts: object) -> str:
    """A stable reference for files that carry none of their own."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return f"sha:{digest[:32]}"


def check_size(data: bytes) -> None:
    if len(data) > MAX_BYTES:
        raise StatementError("File is too large")
    if not data.strip():
        raise StatementError("The file is empty")
