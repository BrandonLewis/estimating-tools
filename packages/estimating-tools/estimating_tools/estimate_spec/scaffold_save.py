"""Priced estimate-spec items → BidItemScaffold save payloads (Phase 5 slice 3).

The reverse of Phase 4's scaffold-from-template: after an estimate is
priced and confirmed, each item's reusable structure (name, org cost
codes, production defaults) becomes a create_bid_item_scaffold payload.
assembly_ids are BM-side template ids the extractor cannot know — the
save-scaffolds skill proposes them. Pure logic, no MCP (house pattern).
"""
from __future__ import annotations

from estimating_tools.estimate_spec.format_pack import bundled_pack, is_rate_host

RATE_HOST_SKIP_REASON = "rate-host item (no scaffold value)"


def _numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _production(item) -> dict | None:
    """qty per crew-day across the labor sequence, or None.

    duration = sum over blocks of max(crew days); emitted only when qty
    and every days value are numeric and duration > 0 — a formula
    anywhere means no production default (never invent).
    """
    qty = item.get("qty")
    blocks = item.get("labor") or []
    if not (_numeric(qty) and qty > 0 and blocks):
        return None
    duration = 0.0
    for block in blocks:
        days = [row.get("days") for row in block.get("crew") or []]
        if not days or not all(_numeric(d) for d in days):
            return None
        duration += max(days)
    if duration <= 0:
        return None
    return {"rate": round(qty / duration, 2),
            "rate_unit": f"{item.get('uom', '')}/day"}


def extract_scaffold_saves(spec: dict, *, agency: str = "",
                           project_ref: str = "", saved_on: str = "",
                           code_map: dict | None = None,
                           pack=None) -> tuple[list, list]:
    """(saves, skipped) — create_bid_item_scaffold kwargs per priced item.

    bid_item_code resolution mirrors historicals.estimates:
    code_map["<schedule>::<item_no>"] -> code_map["<item_no>"] ->
    item.cost_code (the agency code when the spec came from a bid frame;
    supply code_map when cost_code holds the org code instead).

    `source_item_no` on each save is preview provenance for the skill —
    not a create_bid_item_scaffold kwarg; drop it before the MCP call.

    The pack's rate-table host carries no reusable scaffold value and is
    always skipped (`format_pack.is_rate_host`): every item of
    `seed.scaffold.rate_host_recipe` by default (e.g. the legacy_demo
    fixture's `setup`, whose sheet holds the rate table), or -- for a pack
    whose host recipe is also a bid-item recipe
    (`seed.scaffold.rate_host_is_bid_recipe: true`, as fieldbook's `lump_sum`
    is) -- only the scaffold-injected host (item_no RATES), so the pack's
    real lump-sum bid items, mobilization among them, are saved.
    """
    pack = pack or bundled_pack()
    code_map = code_map or {}
    # The schema's `project` is plain text; a `{name: ...}` mapping is
    # accepted too.
    project = spec.get("project")
    ref = project_ref or (project.get("name", "") if isinstance(project, dict)
                          else str(project or ""))
    saves, skipped = [], []
    for item in spec.get("items") or []:
        item_no = str(item.get("item_no", ""))
        if is_rate_host(item, pack):
            skipped.append({"item_no": item_no, "reason": RATE_HOST_SKIP_REASON})
            continue
        schedule = (item.get("scaffold_meta") or {}).get("schedule", "")
        cost_code = item.get("cost_code", "")
        code = code_map.get(f"{schedule}::{item_no}",
                            code_map.get(item_no, cost_code))
        if not code:
            skipped.append({"item_no": item_no, "reason": "no bid_item_code"})
            continue
        if not item.get("description"):
            skipped.append({"item_no": item_no, "reason": "no description"})
            continue
        notes = f"saved from {ref} item {item_no}"
        if saved_on:
            notes += f" on {saved_on}"
        save = {
            "bid_item_code": str(code),
            "agency": agency,
            "name": item["description"],
            "cost_codes": ([str(cost_code)]
                           if cost_code and str(cost_code) != str(code)
                           else []),
            "notes": notes,
            "source_item_no": item_no,
        }
        production = _production(item)
        if production:
            save["default_production"] = production
        saves.append(save)
    return saves, skipped
