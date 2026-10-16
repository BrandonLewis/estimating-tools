"""CanonicalEstimate → HistoricalRecord fan-out (Phase 5 slice 2).

Own-estimate deposits: after pricing (outcome="estimated", price into
unit_cost_estimated) and after bid submission (outcome="bid", price into
unit_price_bid) — mirroring suggest.record_price()'s read side. Tab
outcomes (awarded/competitor_bid) come from tabs.py; actualized comes
from job cost. Pure function of its inputs; MCP traffic stays at the
skill layer.
"""
from __future__ import annotations

from estimating_tools.historicals.model import HistoricalRecord
from estimating_tools.importers.model import CanonicalEstimate

OWN_OUTCOMES = ("estimated", "bid")

_BREAKDOWN_KEYS = (("labor", "labor"), ("equipment", "equipment"),
                   ("material", "material"), ("subcontractor", "sub"),
                   ("sub", "sub"), ("other", "other"))


def _breakdown(item) -> list[dict] | None:
    """Flat LineItem.breakdown dict → keying-spec list-of-one entry.

    {"labor": …, "subcontractor": …} becomes [{"cost_code": <org cost
    code>, "labor": …, "sub": …}] — the canonical model carries one org
    cost code per line item, so the list has one entry.
    """
    if not item.breakdown:
        return None
    # No org cost code on the line item (e.g. a blank HCSS cost-code
    # column): the cost split is still a real observation — keep the
    # entry, omit the key rather than emitting cost_code: "".
    entry = {"cost_code": item.item_code} if item.item_code else {}
    for src, dst in _BREAKDOWN_KEYS:
        if src in item.breakdown and item.breakdown[src] is not None:
            entry[dst] = item.breakdown[src]
    return [entry]


def estimate_to_records(est: CanonicalEstimate, *, outcome: str = "estimated",
                        agency: str = "", region: str = "", bidder: str = "",
                        project_ref: str = "",
                        code_map: dict | None = None) -> list[HistoricalRecord]:
    """One record per priced line item (unit_price present; $0 kept).

    bid_item_code resolution: code_map["<schedule>::<item_number>"], then
    code_map["<item_number>"], then item.item_code — the fallback covers
    imports whose code column already holds the agency code; supply
    code_map when it holds org cost codes instead.
    """
    if outcome not in OWN_OUTCOMES:
        raise ValueError(
            f"own-estimate outcome must be one of {OWN_OUTCOMES}, got {outcome!r}")
    code_map = code_map or {}
    project = est.project or {}
    ref = project_ref or project.get("name", "")
    records = []
    for schedule in est.schedules:
        for item in schedule.items:
            if item.unit_price is None:
                continue
            code = code_map.get(f"{schedule.name}::{item.item_number}",
                                code_map.get(item.item_number,
                                             item.item_code or ""))
            records.append(HistoricalRecord(
                outcome=outcome,
                agency=agency,
                bid_item_code=code,
                project_ref=ref,
                bid_date=project.get("bid_date"),
                region=region,
                bidder=bidder,
                bid_item={"item_number": item.item_number,
                          "schedule": schedule.name,
                          "description": item.description},
                quantity=item.quantity,
                unit=item.unit,
                unit_price_bid=item.unit_price if outcome == "bid" else None,
                unit_cost_estimated=(item.unit_price if outcome == "estimated"
                                     else None),
                breakdown=_breakdown(item),
                source={"kind": "own_estimate",
                        "ref": project.get("source") or ref},
            ))
    return records
