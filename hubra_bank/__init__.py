"""Bank import: read bank statements, mark invoices paid, book the rest."""

from hubra.core.contracts import widget_contract
from hubra.core.modules import Blueprint, Module

module = Module(
    code="finance.bank",
    # Access the standard roles get when a club first switches it on
    # (docs/roles.md in hubra-app/hubra).
    role_defaults={"board": "view", "treasurer": "all"},
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
    # Hubra's features it uses, through contracts (docs/contracts.md in hubra).
    consumes={
        "finance.invoice.set_status": ">=1,<2",
    },
    # Dashboard widget (hubra_bank/widgets.py).
    provides=(
        widget_contract(
            "finance.bank.open",
            "hubra_bank.widgets:open_payments",
            label="bank.widget.open",
            description="bank.widget.openHint",
            size="s",
            view="stat",
            perm="bank.payments.read",
        ),
    ),
)
