"""Bank import: read camt.054 files and mark QR-bill invoices as paid."""

from hubra.core.modules import Blueprint, Module

module = Module(
    code="finance.bank",
    name="Bank file import",
    description="Import camt.054 files from your bank; QR-bill payments are matched to invoices by reference",
    default_enabled=False,
    depends_on=("finance",),
    blueprints=(
        Blueprint(
            "hubra_bank.routes",
            "bank_bp",
            "/api/v1/bank",
            v2=(("/api/v2/tenants/bank", "bank_bp_v2"),),
        ),
    ),
    tables=("bank_payments",),
)
