"""Bank import blueprint: /api/v1/bank."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from hubra.api.auth.helpers import get_current_member
from hubra.api.permissions import permission_required
from hubra.core.errors import api_error
from hubra.core.extensions import db

from .camt import CamtError, parse
from .models import PAYMENT_STATUSES
from .services import BankImportService, payment_to_dict

bank_bp = Blueprint("bank_bp", __name__)


@bank_bp.post("/camt054")
@permission_required("payments", "import", "Import bank files")
def import_camt054():
    """Upload a camt.054 file (multipart field ``file``, or the raw XML).

    ``?dry_run=1`` shows what would happen without booking anything.
    """
    upload = request.files.get("file")
    data = upload.read() if upload else request.get_data()
    if not data:
        return api_error("VALIDATION_ERROR", "Upload a camt.054 file", 400)
    try:
        credits = parse(data)
    except CamtError as exc:
        return api_error("INVALID_FILE", str(exc), 400)
    dry_run = request.args.get("dry_run") in ("1", "true")
    result = BankImportService.import_credits(
        credits,
        upload.filename if upload else None,
        get_current_member().id,
        dry_run=dry_run,
    )
    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()
    return jsonify(result), 200


@bank_bp.get("/payments")
@permission_required("payments", "read", "View bank payments")
def list_payments():
    status = request.args.get("status")
    if status and status not in PAYMENT_STATUSES:
        return api_error("VALIDATION_ERROR", "Unknown status", 400)
    return jsonify([payment_to_dict(p) for p in BankImportService.list(status)]), 200


@bank_bp.post("/payments/<int:payment_id>/assign")
@permission_required("payments", "import", "Import bank files")
def assign_payment(payment_id: int):
    invoice_id = (request.get_json(silent=True) or {}).get("invoice_id")
    if not isinstance(invoice_id, int):
        return api_error("VALIDATION_ERROR", "invoice_id is required", 400)
    payment = BankImportService.assign(payment_id, invoice_id, get_current_member().id)
    db.session.commit()
    return jsonify(payment_to_dict(payment)), 200
