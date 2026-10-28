"""Bank import: read bank statements, mark invoices paid, book the rest."""

from hubra.core.modules import Blueprint, Module

module = Module(
    code="finance.bank",
    name="Bank file import",
    description="Import bank statements (camt.053/054, MT940, CSV); payments are matched to invoices and other bookings go into the books",
    default_enabled=False,
    depends_on=("finance",),
    blueprints=(
        Blueprint(
            "hubra_bank.routes",
            "bank_bp",
            "/api/v1/bank",
        ),
    ),
    tables=("bank_rules", "bank_payments", "bank_csv_profiles"),
)
