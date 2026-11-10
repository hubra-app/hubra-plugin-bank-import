"""Dashboard widget of the bank import (docs/dashboards.md in hubra-app/hubra).

finance.bank.open  stat  imported payments that still need a look (suggested,
                         unmatched, wrong amount or paid twice)

It reads as the viewing member, who needs ``bank.payments.read``.
"""

from __future__ import annotations

from sqlalchemy import func, select

from hubra.core.extensions import db

from .models import OPEN_STATUSES, BankPayment


def open_payments(ctx, config: dict) -> dict:
    count = db.session.scalar(
        select(func.count()).where(BankPayment.status.in_(OPEN_STATUSES))
    )
    return {"value": count or 0, "sub": None, "path": "/app/finance/bank"}
