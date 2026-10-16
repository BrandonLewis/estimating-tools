"""Map a CanonicalQuote to a BidSheet.ai work-package-quote plan. Pure and
host-agnostic: no BidSheet.ai/Django/MCP/network.

(schedule_name, item_number) on each line/ref are LOOKUP keys — the capture-quote
skill resolves them per-schedule to project_bid_item_id and then to
work_package_item_id before the MCP call.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from estimating_tools.quotes.model import CanonicalQuote


@dataclass
class QuotePlan:
    """- work_package_name: find-or-create name for the work package
    - quote_header: kwargs for create_work_package_quote (None optionals omitted)
    - bid_item_refs: distinct [{schedule_name, item_number}] (first-seen order)
    - lines: per-line payloads for create/update_work_package_quote_line_item
    """

    work_package_name: str = ""
    quote_header: dict = field(default_factory=dict)
    bid_item_refs: list[dict] = field(default_factory=list)
    lines: list[dict] = field(default_factory=list)


def plan_quote(canonical: CanonicalQuote) -> QuotePlan:
    """Field-map a CanonicalQuote into a QuotePlan (no live calls)."""
    header = {"vendor_name": canonical.vendor_name, "is_dbe": canonical.is_dbe}
    for key in ("amount", "vendor_id", "notes", "contact_info"):
        value = getattr(canonical, key)
        if value is not None:
            header[key] = value

    refs: list[dict] = []
    seen: set[tuple[str, str]] = set()
    lines: list[dict] = []
    for line in canonical.lines:
        pair = (line.schedule_name, line.item_number)
        if pair not in seen:
            seen.add(pair)
            refs.append({"schedule_name": line.schedule_name, "item_number": line.item_number})
        payload = {
            "schedule_name": line.schedule_name,
            "item_number": line.item_number,
            "is_included": line.is_included,
        }
        for key in ("unit_price", "amount", "quantity", "exclusion_notes"):
            value = getattr(line, key)
            if value is not None:
                payload[key] = value
        lines.append(payload)

    return QuotePlan(work_package_name=canonical.work_package_name,
                     quote_header=header, bid_item_refs=refs, lines=lines)


# ---------- render (Phase 3) ----------

from estimating_tools.artifacts import format_money, format_qty, md_table


def _dash(value) -> str:
    return "-" if value is None or value == "" else str(value)


def render_quote_plan(plan: QuotePlan) -> str:
    """Render a QuotePlan as a read-only review artifact per the Phase 3 convention."""
    lines_count = len(plan.lines)
    refs_count = len(plan.bid_item_refs)
    summary = (
        f"{lines_count} line item{'s' if lines_count != 1 else ''} "
        f"across {refs_count} bid item{'s' if refs_count != 1 else ''}."
    )

    # Work package + quote header: a single-row kv table combining the two.
    header = plan.quote_header
    hdr_headers = ["work_package_name", "vendor_name", "is_dbe", "amount",
                   "vendor_id", "notes", "contact_info"]
    hdr_row = [
        _dash(plan.work_package_name),
        _dash(header.get("vendor_name")),
        _dash(header.get("is_dbe")),
        format_money(header.get("amount")) if header.get("amount") is not None else "-",
        _dash(header.get("vendor_id")),
        _dash(header.get("notes")),
        _dash(header.get("contact_info")),
    ]
    hdr_table = md_table(hdr_headers, [hdr_row])

    refs_headers = ["schedule_name", "item_number"]
    refs_rows = [[_dash(r.get("schedule_name")), _dash(r.get("item_number"))]
                 for r in plan.bid_item_refs]
    refs_table = md_table(refs_headers, refs_rows)

    lines_headers = ["schedule_name", "item_number", "is_included", "unit_price",
                     "amount", "quantity", "exclusion_notes"]
    lines_rows = [
        [
            _dash(ln.get("schedule_name")),
            _dash(ln.get("item_number")),
            _dash(ln.get("is_included")),
            format_money(ln.get("unit_price")) if ln.get("unit_price") is not None else "-",
            format_money(ln.get("amount")) if ln.get("amount") is not None else "-",
            format_qty(ln.get("quantity")) if ln.get("quantity") is not None else "-",
            _dash(ln.get("exclusion_notes")),
        ]
        for ln in plan.lines
    ]
    lines_table = md_table(lines_headers, lines_rows)

    return (
        f"# Quote plan\n\n"
        f"{summary}\n\n"
        f"## Work package + quote header\n\n{hdr_table}\n\n"
        f"## Bid item refs\n\n{refs_table}\n\n"
        f"## Line items\n\n{lines_table}\n\n"
        f"Confirm to write to BidSheet.ai."
    )
