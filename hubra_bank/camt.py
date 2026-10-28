"""camt.054 parser (ISO 20022 debit/credit notification, Swiss SPS flavour).

Reads the credits of a file into plain dicts. Namespace-agnostic, so
camt.054.001.04 and .08 (and the bank-specific variants) all work.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

MAX_BYTES = 10 * 1024 * 1024


class CamtError(ValueError):
    pass


@dataclass
class Credit:
    bank_reference: str
    amount: Decimal
    currency: str
    booked_on: date
    qr_reference: str | None
    debtor_name: str | None
    remittance: str | None


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


def _date(el) -> date | None:
    for path in (("BookgDt", "Dt"), ("BookgDt", "DtTm"), ("ValDt", "Dt")):
        value = _text(el, *path)
        if value:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                continue
    return None


def _amount(el) -> tuple[Decimal, str] | None:
    node = _child(el, "Amt")
    if node is None or not node.text:
        return None
    try:
        return Decimal(node.text.strip()), node.get("Ccy", "CHF")
    except InvalidOperation:
        return None


def _debtor(tx) -> str | None:
    parties = _child(tx, "RltdPties")
    return _text(parties, "Dbtr", "Pty", "Nm") or _text(parties, "Dbtr", "Nm")


def parse(data: bytes) -> list[Credit]:
    if len(data) > MAX_BYTES:
        raise CamtError("File is too large")
    # Bank files never need a DTD; refusing one rules out entity tricks.
    if b"<!DOCTYPE" in data[:4096].upper():
        raise CamtError("File contains a DOCTYPE")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise CamtError(f"Not an XML file: {exc}") from exc

    notif = _child(root, "BkToCstmrDbtCdtNtfctn")
    if notif is None:
        raise CamtError("Not a camt.054 file (no BkToCstmrDbtCdtNtfctn)")

    credits: list[Credit] = []
    for ntfctn in _children(notif, "Ntfctn"):
        for entry in _children(ntfctn, "Ntry"):
            if _text(entry, "CdtDbtInd") != "CRDT":
                continue
            if (_text(entry, "RvslInd") or "").lower() == "true":
                continue
            status = _text(entry, "Sts") or _text(entry, "Sts", "Cd")
            if status and status != "BOOK":
                continue
            booked_on = _date(entry)
            entry_ref = _text(entry, "AcctSvcrRef") or _text(entry, "NtryRef")
            details = [
                tx
                for d in _children(entry, "NtryDtls")
                for tx in _children(d, "TxDtls")
            ]
            if not details:
                details = [entry]
            for index, tx in enumerate(details):
                if tx is not entry and _text(tx, "CdtDbtInd") == "DBIT":
                    continue
                amt = _amount(tx) or (_amount(entry) if len(details) == 1 else None)
                if amt is None or booked_on is None:
                    continue
                ref = _text(tx, "RmtInf", "Strd", "CdtrRefInf", "Ref")
                unstructured = " ".join(
                    (u.text or "").strip()
                    for u in _children(_child(tx, "RmtInf"), "Ustrd")
                ).strip()
                bank_ref = _text(tx, "Refs", "AcctSvcrRef") or (
                    f"{entry_ref}/{index}" if entry_ref else None
                )
                if bank_ref is None:
                    # No bank reference at all: derive a stable one.
                    digest = hashlib.sha256(
                        f"{booked_on}|{amt[0]}|{ref}|{_debtor(tx)}|{index}".encode()
                    ).hexdigest()[:32]
                    bank_ref = f"sha:{digest}"
                credits.append(
                    Credit(
                        bank_reference=bank_ref[:120],
                        amount=amt[0],
                        currency=amt[1],
                        booked_on=booked_on,
                        qr_reference=ref.replace(" ", "") if ref else None,
                        debtor_name=_debtor(tx),
                        remittance=unstructured[:500] or None,
                    )
                )
    return credits
