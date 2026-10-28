"""Bank import blueprint: /api/v1/bank."""

from __future__ import annotations

import json

from flask import Blueprint, jsonify, request

from hubra.api.auth.helpers import get_current_member
from hubra.api.permissions import permission_required
from hubra.core.errors import api_error
from hubra.core.extensions import db

from . import csvimport
from .formats import FORMATS, detect, read
from .lines import StatementError
from .models import DIRECTIONS, PAYMENT_STATUSES
from .services import (
    BankImportService,
    CsvProfileService,
    RuleService,
    payment_to_dict,
    rule_to_dict,
)

bank_bp = Blueprint("bank_bp", __name__)


def _upload() -> tuple[bytes, str | None]:
    upload = request.files.get("file")
    data = upload.read() if upload else request.get_data()
    return data, upload.filename if upload else None


def _run_import(fmt: str | None):
    data, file_name = _upload()
    if not data:
        return api_error("VALIDATION_ERROR", "Upload a bank file", 400)
    if fmt is not None and fmt not in FORMATS:
        return api_error("VALIDATION_ERROR", "format is camt, mt940 or csv", 400)
    mapping = None
    raw_mapping = request.form.get("mapping") or request.args.get("mapping")
    if raw_mapping:
        try:
            mapping = json.loads(raw_mapping)
        except ValueError:
            mapping = None
        if not isinstance(mapping, dict):
            return api_error("VALIDATION_ERROR", "mapping must be a JSON object", 400)
    fmt = fmt or detect(data)
    signature = None
    if fmt == "csv":
        try:
            columns, _, _ = csvimport.read_columns(data)
        except StatementError as exc:
            return api_error("INVALID_FILE", str(exc), 400)
        signature = csvimport.signature(columns)
        if mapping is None:
            mapping = CsvProfileService.get(signature)
    try:
        statement = read(data, fmt, mapping)
    except csvimport.CsvMappingRequired as exc:
        return jsonify(
            {
                "error": "CSV_MAPPING_REQUIRED",
                "message": str(exc),
                "columns": exc.columns,
                "sample": exc.sample,
                "suggested": csvimport.auto_mapping(exc.columns),
                "fields": list(csvimport.FIELDS),
            }
        ), 422
    except StatementError as exc:
        return api_error("INVALID_FILE", str(exc), 400)
    dry_run = request.args.get("dry_run") in ("1", "true")
    result = BankImportService.import_statement(
        statement, file_name, get_current_member().id, dry_run=dry_run
    )
    if dry_run:
        db.session.rollback()
    else:
        if signature and mapping:
            CsvProfileService.save(signature, mapping)
        db.session.commit()
    return jsonify(result), 200


@bank_bp.post("/import")
@permission_required("payments", "import", "Import bank files")
def import_file():
    """Upload a bank file: camt.052/053/054, MT940 or CSV.

    Multipart field ``file`` (or the raw body).  ``?format=`` overrides the
    detection, ``mapping`` (form field, JSON) maps CSV columns, and
    ``?dry_run=1`` shows what would happen without booking anything.
    """
    return _run_import(request.args.get("format") or request.form.get("format"))


@bank_bp.post("/camt054")
@permission_required("payments", "import", "Import bank files")
def import_camt054():
    """The camt.054-only endpoint of plugin 1.0; reads any camt file."""
    return _run_import("camt")


@bank_bp.post("/csv/columns")
@permission_required("payments", "import", "Import bank files")
def csv_columns():
    """The header and first rows of a CSV, to map its columns by hand."""
    data, _ = _upload()
    try:
        columns, body, _ = csvimport.read_columns(data)
    except StatementError as exc:
        return api_error("INVALID_FILE", str(exc), 400)
    signature = csvimport.signature(columns)
    return jsonify(
        {
            "columns": columns,
            "sample": body[:5],
            "fields": list(csvimport.FIELDS),
            "mapping": CsvProfileService.get(signature)
            or csvimport.auto_mapping(columns),
        }
    ), 200


@bank_bp.get("/payments")
@permission_required("payments", "read", "View bank payments")
def list_payments():
    status = request.args.get("status")
    direction = request.args.get("direction")
    open_only = status == "open"
    if open_only:
        status = None
    if status and status not in PAYMENT_STATUSES:
        return api_error("VALIDATION_ERROR", "Unknown status", 400)
    if direction and direction not in DIRECTIONS:
        return api_error("VALIDATION_ERROR", "direction is credit or debit", 400)
    payments = BankImportService.list(status, direction, open_only)
    return jsonify([payment_to_dict(p) for p in payments]), 200


@bank_bp.post("/payments/<int:payment_id>/assign")
@permission_required("payments", "import", "Import bank files")
def assign_payment(payment_id: int):
    invoice_id = (request.get_json(silent=True) or {}).get("invoice_id")
    if not isinstance(invoice_id, int):
        return api_error("VALIDATION_ERROR", "invoice_id is required", 400)
    payment = BankImportService.assign(payment_id, invoice_id, get_current_member().id)
    db.session.commit()
    return jsonify(payment_to_dict(payment)), 200


@bank_bp.post("/payments/<int:payment_id>/confirm")
@permission_required("payments", "import", "Import bank files")
def confirm_payment(payment_id: int):
    payment = BankImportService.confirm(payment_id, get_current_member().id)
    db.session.commit()
    return jsonify(payment_to_dict(payment)), 200


@bank_bp.post("/payments/<int:payment_id>/book")
@permission_required("payments", "import", "Import bank files")
def book_payment(payment_id: int):
    body = request.get_json(silent=True) or {}
    category_id = body.get("category_id")
    if not isinstance(category_id, int):
        return api_error("VALIDATION_ERROR", "category_id is required", 400)
    description = body.get("description")
    if description is not None and not isinstance(description, str):
        return api_error("VALIDATION_ERROR", "description must be text", 400)
    payment = BankImportService.book(
        payment_id, category_id, description, get_current_member().id
    )
    db.session.commit()
    return jsonify(payment_to_dict(payment)), 200


@bank_bp.post("/payments/<int:payment_id>/ignore")
@permission_required("payments", "import", "Import bank files")
def ignore_payment(payment_id: int):
    payment = BankImportService.ignore(payment_id, get_current_member().id)
    db.session.commit()
    return jsonify(payment_to_dict(payment)), 200


@bank_bp.get("/rules")
@permission_required("payments", "read", "View bank payments")
def list_rules():
    return jsonify([rule_to_dict(r) for r in RuleService.list()]), 200


@bank_bp.post("/rules")
@permission_required("payments", "import", "Import bank files")
def create_rule():
    rule = RuleService.create(request.get_json(silent=True) or {})
    db.session.commit()
    return jsonify(rule_to_dict(rule)), 201


@bank_bp.patch("/rules/<int:rule_id>")
@permission_required("payments", "import", "Import bank files")
def update_rule(rule_id: int):
    rule = RuleService.update(rule_id, request.get_json(silent=True) or {})
    db.session.commit()
    return jsonify(rule_to_dict(rule)), 200


@bank_bp.delete("/rules/<int:rule_id>")
@permission_required("payments", "import", "Import bank files")
def delete_rule(rule_id: int):
    RuleService.delete(rule_id)
    db.session.commit()
    return "", 204
