"""CSV reader for e-banking exports.

Every bank lays its CSV out differently, so columns are found by their
header (German, French and English names used by PostFinance, UBS,
Raiffeisen, ZKB, the cantonal banks, Yuh and neon).  When that fails the
treasurer maps the columns once; the mapping is saved per header layout
(``BankCsvProfile``) and used for the next file with the same columns.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .lines import (
    BankLine,
    Statement,
    StatementError,
    check_size,
    classify_reference,
    derived_reference,
    normalise_iban,
    reference_in_text,
)

FIELDS = (
    "date",
    "value_date",
    "amount",
    "credit",
    "debit",
    "currency",
    "text",
    "counterparty",
    "iban",
    "reference",
    "bank_reference",
)

# Normalised header -> field.  Several "text" columns are joined.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": (
        "buchungsdatum",
        "buchungstag",
        "datum",
        "date",
        "booking date",
        "transaction date",
        "abschlussdatum",
        "date de comptabilisation",
        "date comptable",
        "date d operation",
        "data di registrazione",
        "trade date",
        "abschluss",
    ),
    "value_date": (
        "valuta",
        "valutadatum",
        "valuta datum",
        "value date",
        "date de valeur",
        "wertstellung",
        "data valuta",
    ),
    "amount": ("betrag", "amount", "montant", "importo", "transaktionsbetrag"),
    "credit": (
        "gutschrift",
        "gutschriften",
        "credit",
        "haben",
        "einzahlung",
        "eingang",
        "accredito",
        "credit amount",
    ),
    "debit": (
        "lastschrift",
        "lastschriften",
        "belastung",
        "belastungen",
        "debit",
        "soll",
        "auszahlung",
        "ausgang",
        "addebito",
        "debit amount",
    ),
    "currency": ("wahrung", "waehrung", "currency", "monnaie", "devise", "ccy"),
    "text": (
        "buchungstext",
        "avisierungstext",
        "beschreibung",
        "beschreibung1",
        "beschreibung2",
        "beschreibung3",
        "text",
        "description",
        "libelle",
        "details",
        "mitteilung",
        "zahlungszweck",
        "verwendungszweck",
        "mitteilungen",
        "communication",
        "descrizione",
        "notes",
        "booking text",
    ),
    "counterparty": (
        "auftraggeber",
        "empfanger",
        "auftraggeber empfanger",
        "name",
        "gegenpartei",
        "zahlungsempfanger",
        "begunstigter",
        "counterparty",
        "payee",
        "payer",
        "beneficiaire",
        "donneur d ordre",
        "partner",
        "name gegenpartei",
        "empfanger auftraggeber",
    ),
    "iban": (
        "iban",
        "iban gegenpartei",
        "konto gegenpartei",
        "counterparty iban",
        "kontonummer",
    ),
    "reference": (
        "referenz",
        "referenznummer",
        "qr referenz",
        "esr referenz",
        "zahlungsreferenz",
        "reference",
        "payment reference",
        "reference qr",
    ),
    "bank_reference": (
        "transaktions nr",
        "transaktionsnummer",
        "transaction id",
        "transaktions id",
        "buchungs nr",
        "id transaction",
        "transaction number",
    ),
}
_LOOKUP = {name: field for field, names in _SYNONYMS.items() for name in names}


class CsvError(StatementError):
    pass


class CsvMappingRequired(CsvError):
    """The columns couldn't be recognised; the user has to map them."""

    def __init__(self, columns: list[str], sample: list[list[str]], signature: str):
        super().__init__("Map the CSV columns to import this file")
        self.columns = columns
        self.sample = sample
        self.signature = signature


def _norm(header: str) -> str:
    text = unicodedata.normalize("NFKD", header)
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    text = re.sub(r"\(.*?\)|\[.*?\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def signature(columns: list[str]) -> str:
    """Identifies a bank's CSV layout, to remember its mapping."""
    joined = "|".join(_norm(c) for c in columns)
    return hashlib.sha256(joined.encode()).hexdigest()[:32]


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _rows(text: str) -> list[list[str]]:
    sample = "\n".join(text.splitlines()[:40])
    counts = {d: sample.count(d) for d in (";", "\t", ",")}
    delimiter = max(counts, key=lambda d: counts[d])
    return [
        [c.strip() for c in row]
        for row in csv.reader(io.StringIO(text), delimiter=delimiter)
    ]


def auto_mapping(columns: list[str]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for col in columns:
        field = _LOOKUP.get(_norm(col))
        if field is None:
            key = _norm(col)
            field = next(
                (
                    f
                    for f in ("credit", "debit", "amount")
                    if key.startswith(_SYNONYMS[f])
                ),
                None,
            )
        if field and (field == "text" or field not in mapping):
            mapping.setdefault(field, []).append(col)
    return mapping


def _usable(mapping: dict[str, list[str]]) -> bool:
    return "date" in mapping and (
        "amount" in mapping or "credit" in mapping or "debit" in mapping
    )


def parse_amount(raw: str) -> Decimal | None:
    s = (
        raw.strip()
        .replace("’", "")
        .replace("'", "")
        .replace(" ", "")
        .replace("\xa0", "")
    )
    if not s:
        return None
    negative = (
        s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    )
    s = s.strip("-+()")
    s = re.sub(r"[A-Za-z]", "", s)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = (
            f"{head.replace(',', '')}.{tail}"
            if len(tail) in (1, 2)
            else s.replace(",", "")
        )
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative else value


_DATE_FORMATS = ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y", "%Y%m%d")


def parse_date(raw: str) -> date | None:
    s = raw.strip().split(" ")[0].split("T")[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _header_row(rows: list[list[str]]) -> int | None:
    """The first row that names a date and an amount column."""
    for i, row in enumerate(rows[:30]):
        if _usable(auto_mapping(row)):
            return i
    return None


def _candidate_header(rows: list[list[str]]) -> int:
    """Without a recognised header: the first row as wide as the data."""
    widths = Counter(len(r) for r in rows if len(r) > 1)
    if not widths:
        raise CsvError("Not a CSV file")
    width = widths.most_common(1)[0][0]
    return next(i for i, r in enumerate(rows) if len(r) == width)


def read_columns(data: bytes) -> tuple[list[str], list[list[str]], int]:
    rows = _rows(_decode(data))
    index = _header_row(rows)
    if index is None:
        index = _candidate_header(rows)
    return rows[index], rows[index + 1 :], index


def parse(data: bytes, mapping: dict[str, list[str] | str] | None = None) -> Statement:
    """Read a CSV export.  *mapping* is field -> column name(s)."""
    check_size(data)
    columns, body, _ = read_columns(data)
    if mapping:
        chosen = {
            f: [v] if isinstance(v, str) else list(v)
            for f, v in mapping.items()
            if f in FIELDS and v
        }
        missing = [c for cols in chosen.values() for c in cols if c not in columns]
        if missing:
            raise CsvError(f"Column not in the file: {', '.join(missing)}")
    else:
        chosen = auto_mapping(columns)
    if not _usable(chosen):
        raise CsvMappingRequired(columns, body[:5], signature(columns))

    pos = {c: i for i, c in enumerate(columns)}

    def get(row: list[str], field: str) -> str:
        values = [row[pos[c]] for c in chosen.get(field, []) if pos[c] < len(row)]
        return " ".join(v for v in values if v).strip()

    statement = Statement(format="csv")
    seen: Counter = Counter()
    for row in body:
        if not any(row):
            continue
        booked_on = parse_date(get(row, "date"))
        if booked_on is None:
            continue
        credit = parse_amount(get(row, "credit")) if "credit" in chosen else None
        debit = parse_amount(get(row, "debit")) if "debit" in chosen else None
        if credit:
            direction, amount = "credit", abs(credit)
        elif debit:
            direction, amount = "debit", abs(debit)
        else:
            value = parse_amount(get(row, "amount")) if "amount" in chosen else None
            if not value:
                continue
            direction, amount = ("credit" if value > 0 else "debit"), abs(value)
        text = get(row, "text") or None
        name = get(row, "counterparty") or None
        ref, kind = classify_reference(get(row, "reference") or None)
        if not kind:
            ref, kind = reference_in_text(text)
        bank_ref = get(row, "bank_reference")
        if not bank_ref:
            key = (booked_on, direction, amount, text, name)
            seen[key] += 1
            bank_ref = derived_reference(*key, seen[key])
        statement.lines.append(
            BankLine(
                bank_reference=bank_ref[:120],
                direction=direction,
                amount=amount,
                currency=(get(row, "currency") or "CHF")[:3].upper(),
                booked_on=booked_on,
                value_date=parse_date(get(row, "value_date"))
                if "value_date" in chosen
                else None,
                reference=ref,
                reference_type=kind,
                counterparty_name=name[:255] if name else None,
                counterparty_iban=normalise_iban(get(row, "iban")),
                remittance=text[:500] if text else None,
            )
        )
    if not statement.lines:
        raise CsvError("No bookings found in the file")
    return statement
