"""finance.bank: camt.054 import and QR reference matching."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import pytest

from tests.helpers import set_modules
from hubra.core.models.finance import Invoice, Transaction, TransactionCategory
from hubra.core.services.qr_reference import generate_qrr_reference
from hubra_bank.camt import CamtError, parse

NS = "urn:iso:std:iso:20022:tech:xsd:camt.054.001.08"


def _tx(amount, ref, acct_ref, name="Hans Muster", ccy="CHF"):
    ref_xml = (
        f"<RmtInf><Strd><CdtrRefInf><Tp><CdOrPrtry><Prtry>QRR</Prtry></CdOrPrtry></Tp>"
        f"<Ref>{ref}</Ref></CdtrRefInf></Strd></RmtInf>"
        if ref
        else "<RmtInf><Ustrd>Spende</Ustrd></RmtInf>"
    )
    return (
        f"<TxDtls><Refs><AcctSvcrRef>{acct_ref}</AcctSvcrRef></Refs>"
        f'<Amt Ccy="{ccy}">{amount}</Amt><CdtDbtInd>CRDT</CdtDbtInd>'
        f"<RltdPties><Dbtr><Pty><Nm>{name}</Nm></Pty></Dbtr></RltdPties>"
        f"{ref_xml}</TxDtls>"
    )


def _camt(*txs, extra=""):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="{NS}"><BkToCstmrDbtCdtNtfctn>
<GrpHdr><MsgId>1</MsgId></GrpHdr>
<Ntfctn><Id>n1</Id>
<Ntry><Amt Ccy="CHF">0</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>
<BookgDt><Dt>2026-10-27</Dt></BookgDt><AcctSvcrRef>E1</AcctSvcrRef>
<NtryDtls>{"".join(txs)}</NtryDtls></Ntry>
<Ntry><Amt Ccy="CHF">99</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>
<BookgDt><Dt>2026-10-27</Dt></BookgDt></Ntry>
<Ntry><Amt Ccy="CHF">5</Amt><CdtDbtInd>CRDT</CdtDbtInd><RvslInd>true</RvslInd>
<Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>2026-10-27</Dt></BookgDt></Ntry>
{extra}
</Ntfctn></BkToCstmrDbtCdtNtfctn></Document>""".encode()


@pytest.fixture
def invoices(db, seeded_db):
    set_modules(True, "finance.bank")
    db.session.add(TransactionCategory(name="Membership"))
    member = seeded_db["admin"]
    a = Invoice(
        member_id=member.id,
        issued=date(2026, 9, 1),
        due=date(2026, 9, 30),
        amount=Decimal("120.00"),
        status="Open",
    )
    b = Invoice(
        member_id=member.id,
        issued=date(2026, 9, 1),
        due=date(2026, 9, 30),
        amount=Decimal("50.00"),
        status="Overdue",
    )
    db.session.add_all([a, b])
    db.session.flush()
    refs = (
        generate_qrr_reference(member.id, a.id),
        generate_qrr_reference(member.id, b.id),
    )
    db.session.commit()
    return a, b, refs


def test_parser_reads_credits_only():
    credits = parse(
        _camt(
            _tx("120.00", "21 00000 00003 13947 14300 09017", "T1"),
            _tx("10", None, "T2"),
        )
    )
    assert [(c.bank_reference, c.amount) for c in credits] == [
        ("T1", Decimal("120.00")),
        ("T2", Decimal("10")),
    ]
    assert credits[0].qr_reference == "210000000003139471430009017"
    assert credits[0].debtor_name == "Hans Muster"
    assert credits[1].remittance == "Spende"
    assert credits[0].booked_on == date(2026, 10, 27)


@pytest.mark.parametrize(
    "data",
    [b"not xml", b"<a/>", b'<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>'],
)
def test_parser_rejects_bad_files(data):
    with pytest.raises(CamtError):
        parse(data)


def test_import_marks_matching_invoice_paid(client, db, auth_headers, invoices):
    a, b, (ref_a, ref_b) = invoices
    data = _camt(
        _tx("120.00", ref_a, "T1"),
        _tx("40.00", ref_b, "T2"),  # short payment
        _tx("30.00", "000000000000000000000000000", "T3"),
    )
    preview = client.post("/api/v1/bank/camt054?dry_run=1", data=data)
    assert preview.status_code == 200
    assert preview.get_json()["summary"]["matched"] == 1
    assert db.session.get(Invoice, a.id).status == "Open"

    resp = client.post(
        "/api/v1/bank/camt054",
        data={"file": (io.BytesIO(data), "october.xml")},
        content_type="multipart/form-data",
    )
    summary = resp.get_json()["summary"]
    assert summary == {
        "matched": 1,
        "unmatched": 1,
        "mismatch": 1,
        "duplicate_payment": 0,
        "already_imported": 0,
    }
    db.session.expire_all()
    paid = db.session.get(Invoice, a.id)
    assert paid.status == "Paid"
    tx = db.session.get(Transaction, paid.transaction_id)
    assert tx.status == "Completed" and tx.date == date(2026, 10, 27)
    assert db.session.get(Invoice, b.id).status == "Overdue"

    # Same file again books nothing.
    again = client.post("/api/v1/bank/camt054", data=data).get_json()["summary"]
    assert again["already_imported"] == 3 and again["matched"] == 0

    # The short payment can be assigned by hand.
    payments = client.get("/api/v1/bank/payments?status=mismatch").get_json()
    assert len(payments) == 1
    resp = client.post(
        f"/api/v1/bank/payments/{payments[0]['id']}/assign", json={"invoice_id": b.id}
    )
    assert resp.get_json()["status"] == "assigned"
    db.session.expire_all()
    assert db.session.get(Invoice, b.id).status == "Paid"


def test_payment_for_paid_invoice_is_flagged(client, db, auth_headers, invoices):
    a, _, (ref_a, _) = invoices
    a.status = "Paid"
    db.session.commit()
    resp = client.post("/api/v1/bank/camt054", data=_camt(_tx("120.00", ref_a, "T9")))
    assert resp.get_json()["summary"]["duplicate_payment"] == 1


def test_module_off(client, auth_headers, invoices):
    set_modules(False, "finance.bank")
    assert client.post("/api/v1/bank/camt054", data=b"<x/>").status_code == 403
