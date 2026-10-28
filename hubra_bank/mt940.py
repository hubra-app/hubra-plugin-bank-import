"""MT940 reader (SWIFT customer statement).

Older than camt.053 and still offered by some banks for accounting
software.  Reads ``:61:`` statement lines with their ``:86:`` information,
and the ``:60F:``/``:62F:`` balances.  ``:86:`` comes in several dialects:
the German structured one (``?20``-``?29`` remittance, ``?32`` name, ``?31``
IBAN), the slash-tagged one (``/NAME/``, ``/REMI/``) and plain text; all
three are understood.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from decimal import Decimal

from .lines import (
    Balance,
    BankLine,
    Statement,
    StatementError,
    check_size,
    classify_reference,
    derived_reference,
    normalise_iban,
    reference_in_text,
)


class Mt940Error(StatementError):
    pass


_TAG = re.compile(r"^:(\d{2}[A-Z]?):", re.MULTILINE)
_LINE61 = re.compile(
    r"^(?P<value>\d{6})(?P<entry>\d{4})?(?P<mark>R?[CD])[A-Z]?"
    r"(?P<amount>\d+,\d*)(?P<type>[NSF][A-Z0-9]{3})"
    r"(?P<cust>[^/\n]{0,16})(?://(?P<bank>[^\n]{1,16}))?(?:\n(?P<extra>.*))?",
    re.DOTALL,
)
_BAL = re.compile(r"^(?P<mark>[CD])(?P<date>\d{6})(?P<ccy>[A-Z]{3})(?P<amount>\d+,\d*)")
_IBAN_IN_TEXT = re.compile(
    r"\b([A-Z]{2}\d{2}(?: ?[0-9A-Z]{4}){3,7}(?: ?[0-9A-Z]{1,3})?)\b"
)


def looks_like(data: bytes) -> bool:
    head = data[:4096]
    return b":20:" in head and (b":61:" in data or b":60F:" in head)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _amount(raw: str) -> Decimal:
    return Decimal(raw.replace(",", "."))


def _yymmdd(raw: str) -> date:
    return date(2000 + int(raw[:2]), int(raw[2:4]), int(raw[4:6]))


def _booking_date(value: date, mmdd: str | None) -> date:
    if not mmdd:
        return value
    month, day = int(mmdd[:2]), int(mmdd[2:])
    year = value.year
    if value.month == 12 and month == 1:
        year += 1
    elif value.month == 1 and month == 12:
        year -= 1
    return date(year, month, day)


def _info(text: str) -> tuple[str | None, str | None, str | None]:
    """(counterparty name, IBAN, remittance) from an ``:86:`` field."""
    flat = text.replace("\r", "").replace("\n", "")
    if re.match(r"^\d{3}\?", flat):
        fields: dict[str, list[str]] = {}
        for code, value in re.findall(r"\?(\d{2})([^?]*)", flat):
            fields.setdefault(code, []).append(value.strip())
        remittance = " ".join(
            v
            for code in [
                *(f"{n}" for n in range(20, 30)),
                *(f"{n}" for n in range(60, 64)),
            ]
            for v in fields.get(code, [])
            if v
        )
        name = " ".join(v for c in ("32", "33") for v in fields.get(c, []) if v)
        iban = normalise_iban("".join(fields.get("31", [])))
        return name or None, iban, remittance or " ".join(fields.get("00", [])) or None
    if flat.startswith("/"):
        tags = dict(re.findall(r"/([A-Z]{4})/((?:[^/]|//)*)", flat))
        name = tags.get("NAME", "").replace("//", "/").strip() or None
        remittance = tags.get("REMI", "").replace("USTD//", "").replace("//", "/")
        iban = normalise_iban(tags.get("IBAN") or tags.get("ACCW"))
        return name, iban, remittance.strip() or None
    plain = " ".join(text.split())
    m = _IBAN_IN_TEXT.search(plain)
    return None, normalise_iban(m.group(1)) if m else None, plain or None


def _fields(block: str) -> list[tuple[str, str]]:
    marks = list(_TAG.finditer(block))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(block)
        out.append((m.group(1), block[m.end() : end].strip("\r\n -")))
    return out


def parse(data: bytes) -> Statement:
    check_size(data)
    text = _decode(data).replace("\r\n", "\n")
    # Strip the SWIFT envelope ({1:...}{2:...}{4: ... -}) when present.
    text = re.sub(r"\{[1-3,5]:[^{}]*\}", "", text).replace("{4:", "")
    if ":61:" not in text and ":60F:" not in text:
        raise Mt940Error("Not an MT940 file")

    statement = Statement(format="mt940")
    account: str | None = None
    opening: Decimal | None = None
    movement = Decimal(0)
    seen: Counter = Counter()
    last: BankLine | None = None
    currency = "CHF"

    for tag, value in _fields(text):
        if tag == "20":
            account, opening, movement, last = None, None, Decimal(0), None
        elif tag == "25":
            account = normalise_iban(value.split("/")[-1]) or value[:34]
        elif tag in ("60F", "60M"):
            m = _BAL.match(value)
            if m:
                amt = _amount(m["amount"])
                opening = amt if m["mark"] == "C" else -amt
                currency = m["ccy"]
        elif tag in ("62F", "62M"):
            m = _BAL.match(value)
            if m and opening is not None:
                amt = _amount(m["amount"])
                closing = amt if m["mark"] == "C" else -amt
                iban = account if account and account[:2].isalpha() else None
                statement.balances.append(Balance(iban, opening, closing, movement))
        elif tag == "61":
            m = _LINE61.match(value)
            if not m:
                raise Mt940Error(f"Can't read the statement line :61:{value[:40]}")
            value_date = _yymmdd(m["value"])
            mark = m["mark"]
            direction = "credit" if mark in ("C", "RD") else "debit"
            amount = _amount(m["amount"])
            movement += amount if direction == "credit" else -amount
            last = BankLine(
                bank_reference="",
                direction=direction,
                amount=amount,
                currency=currency,
                booked_on=_booking_date(value_date, m["entry"]),
                value_date=value_date,
                account_iban=account if account and account[:2].isalpha() else None,
                reversal=mark.startswith("R"),
            )
            bank = (m["bank"] or "").strip()
            cust = (m["cust"] or "").strip()
            last.bank_reference = bank if bank and bank != "NONREF" else ""
            last.remittance = (m["extra"] or "").strip() or None
            ref, kind = classify_reference(cust if cust != "NONREF" else None)
            if kind:
                last.reference, last.reference_type = ref, kind
            statement.lines.append(last)
        elif tag == "86" and last is not None:
            name, iban, remittance = _info(value)
            last.counterparty_name = name[:255] if name else None
            last.counterparty_iban = iban
            if remittance:
                last.remittance = remittance[:500]
            if not last.reference:
                last.reference, last.reference_type = reference_in_text(remittance)

    for line in statement.lines:
        if not line.bank_reference:
            key = (
                line.account_iban,
                line.booked_on,
                line.direction,
                line.amount,
                line.remittance,
            )
            seen[key] += 1
            line.bank_reference = derived_reference(*key, seen[key])
        elif not line.reference:
            line.reference, line.reference_type = reference_in_text(line.remittance)
    return statement
