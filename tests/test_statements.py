"""finance.bank: camt.053, MT940 and CSV statements, suggestions and rules."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import pytest

from tests.helpers import set_modules
from hubra.core.models.finance import Invoice, Transaction, TransactionCategory
from hubra.core.services.qr_reference import generate_qrr_reference
from hubra_bank import camt, csvimport, mt940
from hubra_bank.formats import detect
from hubra_bank.lines import classify_reference, reference_in_text
from hubra_bank.models import BankCsvProfile, BankPayment

NS53 = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"
QRR = "210000000003139471430009017"


def _entry(
    amount,
    ind="CRDT",
    ref="E1",
    details="",
    text=None,
    batch=0,
):
    btch = f"<Btch><NbOfTxs>{batch}</NbOfTxs></Btch>" if batch else ""
    info = f"<AddtlNtryInf>{text}</AddtlNtryInf>" if text else ""
    return (
        f'<Ntry><Amt Ccy="CHF">{amount}</Amt><CdtDbtInd>{ind}</CdtDbtInd>'
        f"<Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>2026-10-27</Dt></BookgDt>"
        f"<ValDt><Dt>2026-10-28</Dt></ValDt><AcctSvcrRef>{ref}</AcctSvcrRef>"
        f"<NtryDtls>{btch}{details}</NtryDtls>{info}</Ntry>"
    )


def _detail(amount, ref, name, iban=None, role="Dbtr", ustrd=None, qrr=None):
    acct = f"<{role}Acct><Id><IBAN>{iban}</IBAN></Id></{role}Acct>" if iban else ""
    rmt = ""
    if qrr:
        rmt = f"<RmtInf><Strd><CdtrRefInf><Ref>{qrr}</Ref></CdtrRefInf></Strd></RmtInf>"
    elif ustrd:
        rmt = f"<RmtInf><Ustrd>{ustrd}</Ustrd></RmtInf>"
    return (
        f'<TxDtls><Refs><AcctSvcrRef>{ref}</AcctSvcrRef></Refs><Amt Ccy="CHF">{amount}</Amt>'
        f"<RltdPties><{role}><Pty><Nm>{name}</Nm></Pty></{role}>{acct}</RltdPties>"
        f"{rmt}</TxDtls>"
    )


def _camt053(*entries, opening="1000.00", closing="1000.00"):
    def bal(code, amount):
        return (
            f"<Bal><Tp><CdOrPrtry><Cd>{code}</Cd></CdOrPrtry></Tp>"
            f'<Amt Ccy="CHF">{amount}</Amt><CdtDbtInd>CRDT</CdtDbtInd>'
            f"<Dt><Dt>2026-10-27</Dt></Dt></Bal>"
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="{NS53}"><BkToCstmrStmt><GrpHdr><MsgId>1</MsgId></GrpHdr>
<Stmt><Id>s1</Id><Acct><Id><IBAN>CH93 0076 2011 6238 5295 7</IBAN></Id></Acct>
{bal("OPBD", opening)}{bal("CLBD", closing)}
{"".join(entries)}
</Stmt></BkToCstmrStmt></Document>""".encode()


MT940 = """{1:F01POFICHBEAXXX0000000000}{2:O940}{4:
:20:STMT2610
:25:CH9300762011623852957
:28C:00001/001
:60F:C261026CHF1000,00
:61:2610271027C120,00NTRFNONREF//B1
:86:166?00GUTSCHRIFT?20Mitgliederbeitrag 2026?32Hans Muster?31CH5604835012345678009
:61:2610271027D45,50NDDTNONREF//B2
:86:/NAME/Swisscom (Schweiz) AG/REMI/USTD//Rechnung Oktober/
:61:2610281028C30,00NTRFNONREF
:86:Spende Lisa Beispiel
:62F:C261028CHF1104,50
-}"""

POSTFINANCE_CSV = """Datum von:;2026-10-01
Datum bis:;2026-10-31
Konto:;CH9300762011623852957

Buchungsdatum;Avisierungstext;Gutschrift in CHF;Lastschrift in CHF;Valuta;Saldo in CHF
27.10.2026;GUTSCHRIFT AUFTRAGGEBER: Hans Muster MITTEILUNGEN: Beitrag;120.00;;27.10.2026;1120.00
27.10.2026;LASTSCHRIFT Swisscom (Schweiz) AG;;-45.50;27.10.2026;1074.50
28.10.2026;GUTSCHRIFT QR-REF: 21 00000 00003 13947 14300 09017;30.00;;28.10.2026;1104.50

Disclaimer:;Dies ist kein Kontoauszug
""".encode("cp1252")

ODD_CSV = b"""Tag,Wer,Was,Wieviel
2026-10-27,Hans Muster,Beitrag,"1'200.00"
2026-10-28,Swisscom,Telefon,-45.50
"""


@pytest.fixture
def setup(db, seeded_db):
    set_modules(True, "finance.bank")
    membership = TransactionCategory(name="Membership")
    phone = TransactionCategory(name="Telephone")
    db.session.add_all([membership, phone])
    member = seeded_db["admin"]  # Test Admin
    inv = Invoice(
        member_id=member.id,
        issued=date(2026, 9, 1),
        due=date(2026, 9, 30),
        amount=Decimal("120.00"),
        status="Open",
    )
    db.session.add(inv)
    db.session.flush()
    ref = generate_qrr_reference(member.id, inv.id)
    db.session.commit()
    return {"invoice": inv, "ref": ref, "membership": membership, "phone": phone}


# ── Readers ──────────────────────────────────────────────────────────────────


def test_references():
    assert classify_reference("21 00000 00003 13947 14300 09017") == (QRR, "QRR")
    assert classify_reference("rf18 5390 0754 7034") == ("RF18539007547034", "SCOR")
    assert classify_reference("Rechnung 12") == ("RECHNUNG12", None)
    assert reference_in_text("QR-REF: 21 00000 00003 13947 14300 09017") == (QRR, "QRR")
    assert reference_in_text("Zahlung RF18 5390 0754 7034 danke") == (
        "RF18539007547034",
        "SCOR",
    )
    assert reference_in_text("Beitrag 2026") == (None, None)


def test_camt053_lines_balance_and_batch():
    data = _camt053(
        _entry(
            "120.00",
            details=_detail("120.00", "T1", "Hans Muster", "CH5604835012345678009"),
        ),
        _entry(
            "45.50",
            ind="DBIT",
            ref="E2",
            details=_detail(
                "45.50", "T2", "Swisscom AG", role="Cdtr", ustrd="Rechnung Oktober"
            ),
        ),
        # A collective QR booking: the details come in a camt.054.
        _entry("300.00", ref="E3", batch=12, text="Sammelgutschrift QR"),
        opening="1000.00",
        closing="1374.50",
    )
    assert detect(data) == "camt"
    st = camt.parse(data)
    assert st.format == "camt.053"
    assert [(ln.bank_reference, ln.direction, ln.batch) for ln in st.lines] == [
        ("T1", "credit", False),
        ("T2", "debit", False),
        ("E3", "credit", True),
    ]
    assert st.lines[0].counterparty_iban == "CH5604835012345678009"
    assert st.lines[0].account_iban == "CH9300762011623852957"
    assert st.lines[1].counterparty_name == "Swisscom AG"
    assert st.lines[1].remittance == "Rechnung Oktober"
    assert st.lines[2].remittance == "Sammelgutschrift QR"
    assert st.lines[0].value_date == date(2026, 10, 28)
    [bal] = st.balances
    assert bal.ok and bal.movement == Decimal("374.50")


def test_camt053_balance_mismatch_is_reported():
    st = camt.parse(_camt053(_entry("10.00"), opening="0", closing="20"))
    assert not st.balances[0].ok


def test_mt940():
    data = MT940.encode()
    assert detect(data) == "mt940"
    st = mt940.parse(data)
    a, b, c = st.lines
    assert (a.bank_reference, a.direction, a.amount) == (
        "B1",
        "credit",
        Decimal("120.00"),
    )
    assert a.counterparty_name == "Hans Muster"
    assert a.counterparty_iban == "CH5604835012345678009"
    assert a.remittance == "Mitgliederbeitrag 2026"
    assert a.account_iban == "CH9300762011623852957"
    assert (b.direction, b.counterparty_name, b.remittance) == (
        "debit",
        "Swisscom (Schweiz) AG",
        "Rechnung Oktober",
    )
    assert (
        c.bank_reference.startswith("sha:") and c.remittance == "Spende Lisa Beispiel"
    )
    assert c.booked_on == date(2026, 10, 28)
    [bal] = st.balances
    assert bal.ok
    # The derived reference is stable, so a re-import is recognised.
    assert mt940.parse(data).lines[2].bank_reference == c.bank_reference


def test_mt940_year_end_booking_date():
    data = b""":20:X
:25:CH9300762011623852957
:60F:C261231CHF0,00
:61:2612310102C10,00NTRFNONREF//Y1
:86:Neujahr
:62F:C270102CHF10,00
"""
    [line] = mt940.parse(data).lines
    assert line.value_date == date(2026, 12, 31)
    assert line.booked_on == date(2027, 1, 2)


def test_postfinance_csv():
    assert detect(POSTFINANCE_CSV) == "csv"
    st = csvimport.parse(POSTFINANCE_CSV)
    a, b, c = st.lines
    assert (a.direction, a.amount, a.booked_on) == (
        "credit",
        Decimal("120.00"),
        date(2026, 10, 27),
    )
    assert (b.direction, b.amount) == ("debit", Decimal("45.50"))
    assert (c.reference, c.reference_type) == (QRR, "QRR")
    assert a.value_date == date(2026, 10, 27)


@pytest.mark.parametrize(
    "raw,value",
    [
        ("1'234.50", Decimal("1234.50")),
        ("1’234.50", Decimal("1234.50")),
        ("1.234,50", Decimal("1234.50")),
        ("-45,5", Decimal("-45.5")),
        ("45.50-", Decimal("-45.50")),
        ("(12.00)", Decimal("-12.00")),
        ("CHF 10.00", Decimal("10.00")),
        ("", None),
    ],
)
def test_csv_amounts(raw, value):
    assert csvimport.parse_amount(raw) == value


def test_unknown_csv_needs_a_mapping():
    with pytest.raises(csvimport.CsvMappingRequired) as exc:
        csvimport.parse(ODD_CSV)
    assert exc.value.columns == ["Tag", "Wer", "Was", "Wieviel"]
    st = csvimport.parse(
        ODD_CSV,
        {"date": "Tag", "amount": "Wieviel", "counterparty": "Wer", "text": ["Was"]},
    )
    assert [(ln.direction, ln.amount) for ln in st.lines] == [
        ("credit", Decimal("1200.00")),
        ("debit", Decimal("45.50")),
    ]


# ── Matching and booking ─────────────────────────────────────────────────────


def _upload(client, data, name, **query):
    qs = "&".join(f"{k}={v}" for k, v in query.items())
    return client.post(
        f"/api/v1/bank/import{'?' + qs if qs else ''}",
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def test_payer_name_suggests_invoice(client, db, auth_headers, setup):
    inv = setup["invoice"]
    data = _camt053(
        _entry(
            "120.00",
            details=_detail("120.00", "T1", "Admin Test", "CH5604835012345678009"),
        )
    )
    body = _upload(client, data, "oct.xml").get_json()
    assert body["summary"]["suggested"] == 1
    [item] = body["items"]
    assert item["suggestedInvoiceId"] == inv.id
    # Nothing is paid until the treasurer confirms.
    db.session.expire_all()
    assert db.session.get(Invoice, inv.id).status == "Open"

    [payment] = client.get("/api/v1/bank/payments?status=open").get_json()
    resp = client.post(f"/api/v1/bank/payments/{payment['id']}/confirm")
    assert resp.status_code == 200 and resp.get_json()["status"] == "assigned"
    db.session.expire_all()
    paid = db.session.get(Invoice, inv.id)
    assert paid.status == "Paid"
    assert resp.get_json()["transactionId"] == paid.transaction_id


def test_known_iban_suggests_invoice(client, db, auth_headers, setup, seeded_db):
    member = seeded_db["admin"]
    db.session.add(
        BankPayment(
            bank_reference="OLD",
            amount=Decimal("80"),
            currency="CHF",
            booked_on=date(2026, 1, 5),
            counterparty_iban="CH5604835012345678009",
            status="assigned",
            invoice_id=setup["invoice"].id,
        )
    )
    second = Invoice(
        member_id=member.id,
        issued=date(2026, 10, 1),
        due=date(2026, 10, 31),
        amount=Decimal("55.00"),
        status="Open",
    )
    db.session.add(second)
    db.session.commit()
    # The name doesn't fit (a parent pays), but the IBAN paid before.
    data = _camt053(
        _entry(
            "55.00",
            details=_detail("55.00", "T5", "Erika Muster", "CH5604835012345678009"),
        )
    )
    body = _upload(client, data, "oct.xml", dry_run=1).get_json()
    assert body["items"][0]["suggestedInvoiceId"] == second.id


def test_two_candidates_give_no_suggestion(client, db, auth_headers, setup, seeded_db):
    db.session.add(
        Invoice(
            member_id=seeded_db["admin"].id,
            issued=date(2026, 10, 1),
            due=date(2026, 10, 31),
            amount=Decimal("120.00"),
            status="Open",
        )
    )
    db.session.commit()
    data = _camt053(_entry("120.00", details=_detail("120.00", "T1", "Test Admin")))
    body = _upload(client, data, "oct.xml", dry_run=1).get_json()
    assert body["summary"]["unmatched"] == 1


def test_rule_books_debit_and_manual_booking(client, db, auth_headers, setup):
    phone = setup["phone"]
    resp = client.post(
        "/api/v1/bank/rules",
        json={
            "name": "Phone",
            "direction": "debit",
            "matchField": "counterparty",
            "pattern": "swisscom",
            "categoryId": phone.id,
        },
    )
    assert resp.status_code == 201
    rule_id = resp.get_json()["id"]
    for key in ("name", "pattern"):
        bad = client.post(
            "/api/v1/bank/rules",
            json={
                "name": "Phone",
                "direction": "debit",
                "matchField": "counterparty",
                "pattern": "swisscom",
                key: 5,
            },
        )
        assert bad.status_code == 400, key

    body = _upload(client, MT940.encode(), "oct.sta").get_json()
    assert body["format"] == "mt940"
    assert body["summary"]["booked"] == 1
    assert body["balances"][0]["ok"] is True
    booked = [i for i in body["items"] if i["status"] == "booked"]
    assert booked[0]["ruleId"] == rule_id

    tx = db.session.scalar(
        db.select(Transaction).where(Transaction.category_id == phone.id)
    )
    assert (tx.type, tx.amount, tx.status, tx.method) == (
        "expense",
        Decimal("-45.50"),
        "Completed",
        "IBAN",
    )

    # The donation has no invoice: book it by hand, then ignore nothing else.
    donation = next(
        p
        for p in client.get("/api/v1/bank/payments?status=open").get_json()
        if p["remittance"] == "Spende Lisa Beispiel"
    )
    resp = client.post(
        f"/api/v1/bank/payments/{donation['id']}/book",
        json={"category_id": setup["membership"].id, "description": "Spende"},
    )
    assert resp.status_code == 200 and resp.get_json()["status"] == "booked"
    tx = db.session.get(Transaction, resp.get_json()["transactionId"])
    assert (tx.type, tx.description) == ("income", "Spende")
    # A booked line can't be booked again.
    again = client.post(
        f"/api/v1/bank/payments/{donation['id']}/book",
        json={"category_id": setup["membership"].id},
    )
    assert again.status_code == 409

    # Re-importing the same statement books nothing twice.
    body = _upload(client, MT940.encode(), "oct.sta").get_json()
    assert body["summary"]["already_imported"] == 3


def test_ignore_and_rule_crud(client, db, auth_headers, setup):
    data = _camt053(_entry("7.00", ind="DBIT", ref="FEE", text="Kontofuehrung"))
    _upload(client, data, "oct.xml")
    [fee] = client.get("/api/v1/bank/payments?direction=debit").get_json()
    resp = client.post(f"/api/v1/bank/payments/{fee['id']}/ignore")
    assert resp.get_json()["status"] == "ignored"
    assert client.get("/api/v1/bank/payments?status=open").get_json() == []

    bad = client.post("/api/v1/bank/rules", json={"name": "x", "pattern": ""})
    assert bad.status_code == 400
    rule = client.post(
        "/api/v1/bank/rules",
        json={"name": "Fees", "pattern": "kontof", "categoryId": setup["phone"].id},
    ).get_json()
    assert (rule["direction"], rule["matchField"]) == ("any", "any")
    resp = client.patch(f"/api/v1/bank/rules/{rule['id']}", json={"active": False})
    assert resp.get_json()["active"] is False
    assert client.delete(f"/api/v1/bank/rules/{rule['id']}").status_code == 204
    assert client.get("/api/v1/bank/rules").get_json() == []


def test_csv_import_with_qr_reference(client, db, auth_headers, setup):
    # The QR reference is written in the booking text.
    csv_data = POSTFINANCE_CSV.replace(
        b"21 00000 00003 13947 14300 09017", setup["ref"].encode()
    ).replace(b"30.00;;28.10", b"120.00;;28.10")
    body = _upload(client, csv_data, "pf.csv").get_json()
    assert body["format"] == "csv"
    assert body["summary"]["matched"] == 1
    db.session.expire_all()
    assert db.session.get(Invoice, setup["invoice"].id).status == "Paid"


def test_csv_mapping_is_asked_once_then_remembered(client, db, auth_headers, setup):
    resp = _upload(client, ODD_CSV, "odd.csv")
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "CSV_MAPPING_REQUIRED"
    assert body["columns"] == ["Tag", "Wer", "Was", "Wieviel"]

    mapping = '{"date": ["Tag"], "amount": ["Wieviel"], "counterparty": ["Wer"], "text": ["Was"]}'
    resp = client.post(
        "/api/v1/bank/import",
        data={"file": (io.BytesIO(ODD_CSV), "odd.csv"), "mapping": mapping},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert (
        db.session.scalar(db.select(db.func.count()).select_from(BankCsvProfile)) == 1
    )

    # Next month's file with the same columns needs no mapping.
    november = ODD_CSV.replace(b"2026-10", b"2026-11")
    resp = _upload(client, november, "nov.csv", dry_run=1)
    assert resp.status_code == 200
    assert len(resp.get_json()["items"]) == 2


def test_bad_files(client, auth_headers, setup):
    assert _upload(client, b"<a/>", "x.xml").status_code == 400
    assert _upload(client, b"", "x.csv").status_code == 400
    assert _upload(client, b"x", "x.csv", format="pdf").status_code == 400


def test_csv_columns(client, auth_headers, setup):
    resp = client.post(
        "/api/v1/bank/csv/columns",
        data={"file": (io.BytesIO(POSTFINANCE_CSV), "pf.csv")},
        content_type="multipart/form-data",
    )
    body = resp.get_json()
    assert body["columns"][0] == "Buchungsdatum"
    assert body["mapping"]["credit"] == ["Gutschrift in CHF"]
    assert body["mapping"]["text"] == ["Avisierungstext"]
    assert len(body["sample"]) == 5


@pytest.mark.parametrize(
    "data",
    [
        # Past the first 4 KB, where a text search used to stop looking.
        b"<?xml version='1.0'?>" + b"<!-- " + b"x" * 5000 + b" -->"
        b"<!DOCTYPE d [<!ENTITY e 'boom'>]><Document>&e;</Document>",
        # UTF-16: no ASCII "<!DOCTYPE" bytes to find.
        "<?xml version='1.0' encoding='UTF-16'?>"
        "<!DOCTYPE d [<!ENTITY e 'boom'>]><Document>&e;</Document>".encode("utf-16"),
    ],
)
def test_camt_refuses_any_dtd(data):
    with pytest.raises(camt.CamtError, match="DOCTYPE"):
        camt.parse(data)
