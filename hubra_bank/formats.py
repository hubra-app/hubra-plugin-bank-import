"""Pick the reader for an uploaded bank file."""

from __future__ import annotations

import csv

from . import camt, csvimport, mt940
from .lines import Statement, StatementError, check_size

FORMATS = ("camt", "mt940", "csv")


def detect(data: bytes) -> str:
    head = data[:4096].lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"<"):
        return "camt"
    if mt940.looks_like(data):
        return "mt940"
    return "csv"


def read(
    data: bytes,
    fmt: str | None = None,
    mapping: dict | None = None,
) -> Statement:
    check_size(data)
    fmt = fmt or detect(data)
    if fmt not in FORMATS:
        raise StatementError(f"Unknown format {fmt!r}")
    try:
        if fmt == "camt":
            return camt.parse(data)
        if fmt == "mt940":
            return mt940.parse(data)
        return csvimport.parse(data, mapping)
    except StatementError:
        raise
    except (ValueError, ArithmeticError, TypeError, csv.Error) as exc:
        # A malformed file (an impossible date, a bad mapping, a huge field)
        # is the uploader's problem to fix, not a server error.
        raise StatementError(f"The file could not be read: {exc}") from exc
