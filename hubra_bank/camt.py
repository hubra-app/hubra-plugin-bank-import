"""camt.052, camt.053 and camt.054 reader (ISO 20022, Swiss SPS flavour).

camt.053 is the daily account statement every Swiss bank offers, camt.054
the detailed notification some banks use for QR-bill credits, and camt.052
the intraday report.  All three share the entry layout, so one reader
handles them.  It is namespace-agnostic, so .001.04 to .001.08 and the
bank-specific variants all work.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation

from .lines import (
    Balance,
    BankLine,
    Statement,
    StatementError,
    check_size,
    classify_reference,
    derived_reference,
    normalise_iban,
)


class CamtError(StatementError):
    pass


# Root element -> (format name, report element)
_KINDS = {
    "BkToCstmrStmt": ("camt.053", "Stmt"),
    "BkToCstmrAcctRpt": ("camt.052", "Rpt"),
    "BkToCstmrDbtCdtNtfctn": ("camt.054", "Ntfctn"),
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, *path):
    """Follow local tag names, ignoring namespaces."""
    for name in path:
        if el is None:
            return None
        el = next((c for c in el if _local(c.tag) == name), None)
    return el


def _children(el, name):
    return [c for c in el if _local(c.tag) == name] if el is not None else []


def _text(el, *path) -> str | None:
    node = _child(el, *path)
    if node is None or node.text is None:
        return None
    return node.text.strip() or None


def _date(el, name: str) -> date | None:
    for sub in ("Dt", "DtTm"):
        value = _text(el, name, sub)
        if value:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                continue
    return None


def _amount(el) -> tuple[Decimal, str] | None:
    node = _child(el, "Amt")
    if node is None or not node.text:
        node = _child(el, "AmtDtls", "TxAmt", "Amt")
    if node is None or not node.text:
        return None
    try:
        return Decimal(node.text.strip()), node.get("Ccy", "CHF")
    except InvalidOperation:
        return None


def _party(tx, role: str) -> tuple[str | None, str | None]:
    parties = _child(tx, "RltdPties")
    name = _text(parties, role, "Pty", "Nm") or _text(parties, role, "Nm")
    iban = _text(parties, f"{role}Acct", "Id", "IBAN")
    return name, normalise_iban(iban)


def _booked(entry) -> bool:
    status = _text(entry, "Sts", "Cd") or _text(entry, "Sts")
    return status in (None, "BOOK")


def _balances(report, movement: Decimal) -> list[Balance]:
    found: dict[str, Decimal] = {}
    for bal in _children(report, "Bal"):
        code = _text(bal, "Tp", "CdOrPrtry", "Cd")
        amt = _amount(bal)
        if code is None or amt is None:
            continue
        value = amt[0] if _text(bal, "CdtDbtInd") != "DBIT" else -amt[0]
        found.setdefault(code, value)
    opening = found.get("OPBD", found.get("PRCD"))
    closing = found.get("CLBD")
    if opening is None or closing is None:
        return []
    iban = normalise_iban(_text(report, "Acct", "Id", "IBAN"))
    return [Balance(iban, opening, closing, movement)]


def _entry_lines(entry, account: str | None) -> list[BankLine]:
    direction = "credit" if _text(entry, "CdtDbtInd") == "CRDT" else "debit"
    booked_on = _date(entry, "BookgDt") or _date(entry, "ValDt")
    entry_amt = _amount(entry)
    if booked_on is None or entry_amt is None:
        return []
    value_date = _date(entry, "ValDt")
    reversal = (_text(entry, "RvslInd") or "").lower() == "true"
    entry_ref = _text(entry, "AcctSvcrRef") or _text(entry, "NtryRef")
    entry_text = _text(entry, "AddtlNtryInf")
    details = [
        tx for d in _children(entry, "NtryDtls") for tx in _children(d, "TxDtls")
    ]
    batch_count = max(
        (
            int(n)
            for d in _children(entry, "NtryDtls")
            if (n := _text(d, "Btch", "NbOfTxs")) and n.isdigit()
        ),
        default=0,
    )
    if not details:
        details = [entry]
    lines = []
    for index, tx in enumerate(details):
        tx_direction = direction
        if tx is not entry and _text(tx, "CdtDbtInd") in ("CRDT", "DBIT"):
            tx_direction = "credit" if _text(tx, "CdtDbtInd") == "CRDT" else "debit"
        amt = _amount(tx) if tx is not entry else entry_amt
        if amt is None and len(details) == 1:
            amt = entry_amt
        if amt is None:
            continue
        role = "Dbtr" if tx_direction == "credit" else "Cdtr"
        name, iban = _party(tx, role)
        ref, ref_type = classify_reference(
            _text(tx, "RmtInf", "Strd", "CdtrRefInf", "Ref")
        )
        remittance = " ".join(
            (u.text or "").strip() for u in _children(_child(tx, "RmtInf"), "Ustrd")
        ).strip() or (_text(tx, "AddtlTxInf") or entry_text or "")
        bank_ref = _text(tx, "Refs", "AcctSvcrRef") if tx is not entry else None
        if bank_ref is None and entry_ref:
            bank_ref = entry_ref if len(details) == 1 else f"{entry_ref}/{index}"
        if bank_ref is None:
            bank_ref = derived_reference(
                account, booked_on, tx_direction, amt[0], ref, name, index
            )
        lines.append(
            BankLine(
                bank_reference=bank_ref[:120],
                direction=tx_direction,
                amount=abs(amt[0]),
                currency=amt[1],
                booked_on=booked_on,
                value_date=value_date,
                reference=ref,
                reference_type=ref_type,
                counterparty_name=name[:255] if name else None,
                counterparty_iban=iban,
                remittance=remittance[:500] or None,
                account_iban=account,
                reversal=reversal,
                batch=tx is entry and batch_count > 1,
            )
        )
    return lines


def parse(data: bytes) -> Statement:
    check_size(data)
    # Bank files never need a DTD; refusing one rules out entity tricks.
    if b"<!DOCTYPE" in data[:4096].upper():
        raise CamtError("File contains a DOCTYPE")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise CamtError(f"Not an XML file: {exc}") from exc

    for tag, (fmt, report_tag) in _KINDS.items():
        body = _child(root, tag)
        if body is not None:
            break
    else:
        raise CamtError("Not a camt.052, camt.053 or camt.054 file")

    statement = Statement(format=fmt)
    for report in _children(body, report_tag):
        account = normalise_iban(_text(report, "Acct", "Id", "IBAN"))
        movement = Decimal(0)
        for entry in _children(report, "Ntry"):
            if not _booked(entry):
                continue
            amt = _amount(entry)
            if amt is not None:
                sign = 1 if _text(entry, "CdtDbtInd") == "CRDT" else -1
                movement += sign * amt[0]
            statement.lines.extend(_entry_lines(entry, account))
        statement.balances.extend(_balances(report, movement))
    return statement
