"""Contract-vs-estimate reconciliation (#206).

Generalizes a hard-coded contract-vs-estimate one-off (two dicts pasted in)
into a deterministic diff: match an executed contract's line items
against the BM estimate and report, per item, margin $ and %, an effective
markup on cost, and scope gaps (in contract not estimate = add; in estimate not
contract = remove/zero). Pure stdlib.

Org-agnostic: the diff is mechanical and any markup / flag threshold is a
PARAMETER, not baked (the 13% target in the Work one-off is org-specific and
stays in Work). The SKILL that pulls the BM side live (list_estimate_items /
export_estimate_snapshot) and maps the messy contract lines sits over this.
"""
from estimating_tools.reconcile.diff import (
    LineItem, ReconLine, Reconciliation, reconcile_contract_vs_estimate,
    to_markdown, to_rows,
)

__all__ = [
    "LineItem", "ReconLine", "Reconciliation",
    "reconcile_contract_vs_estimate", "to_rows", "to_markdown",
]
