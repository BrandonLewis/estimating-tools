"""Decide whether a captured quote differs from the current revision's lines.
Pure: stdlib only (no BidSheet.ai/Django/MCP/network).

Used by capture-quote to choose: no-op (identical) vs create a new revision
(changed/added lines). Decimal-string fields are normalized so "10" vs 10.0 is not
a spurious change.
"""
from __future__ import annotations

from dataclasses import dataclass, field

_COMPARE_NUMERIC = ("unit_price", "quantity", "amount")


@dataclass
class QuoteLineDiff:
    unchanged: bool = True
    changed: list[dict] = field(default_factory=list)
    added: list[dict] = field(default_factory=list)


def _num(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _differs(planned: dict, existing: dict) -> bool:
    for key in _COMPARE_NUMERIC:
        planned_value = _num(planned.get(key))
        if planned_value is not None and planned_value != _num(existing.get(key)):
            return True
    if bool(planned.get("is_included", True)) != bool(existing.get("is_included", True)):
        return True
    if (planned.get("exclusion_notes") or "") != (existing.get("exclusion_notes") or ""):
        return True
    return False


def diff_quote_lines(planned_lines, existing_lines) -> QuoteLineDiff:
    """Classify each planned line against the current revision's existing lines."""
    existing_by_item = {e["work_package_item_id"]: e for e in existing_lines}
    changed: list[dict] = []
    added: list[dict] = []
    for p in planned_lines:
        existing = existing_by_item.get(p["work_package_item_id"])
        if existing is None:
            added.append(dict(p))
            continue
        if _differs(p, existing):
            entry = dict(p)
            entry["existing_line_id"] = existing.get("id")
            changed.append(entry)
    return QuoteLineDiff(unchanged=(not changed and not added),
                         changed=changed, added=added)
