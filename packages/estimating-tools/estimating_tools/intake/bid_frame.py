"""Normalize BidSheet.ai bid items into the manifest's bid frame, and seed the
calc-bim takeoff_map so BIM takeoff rows land on real bid items.

Pure: stdlib + pyyaml. The (schedule, item_number) keys written here are the
join keys the estimate-structures takeoff push resolves estimate items by
and price-estimate prices on.
"""
from __future__ import annotations

from collections import Counter

import yaml

from estimating_tools.intake.manifest import BidFrameItem

_MEASURE_BY_UNIT = {
    "M3": "GrossVolume", "CY": "GrossVolume", "CF": "GrossVolume",
    "M2": "GrossArea", "SF": "GrossArea", "SY": "GrossArea",
    "M": "Length", "LF": "Length", "YD": "Length",
    "EA": "Count", "LS": "Count",
}


def infer_measure(unit: str) -> str | None:
    """Map a pay unit to the Qto measure est-bim sums, or None if unknown."""
    return _MEASURE_BY_UNIT.get((unit or "").strip().upper())


def normalize_bid_items(raw_items: list) -> list:
    """Accept list_bid_items output (tolerant of id/project_bid_item_id,
    schedule/schedule_name, item_code/cost_code spellings) -> [BidFrameItem]."""
    items = []
    for r in raw_items:
        item_number = r.get("item_number")
        if item_number is None or item_number == "":
            raise ValueError(f"bid item missing item_number: {r!r}")
        qty = r.get("estimated_quantity")
        if qty is None:
            qty = r.get("quantity")   # live list_bid_items field (string form)
        pbi = r.get("project_bid_item_id")
        if pbi is None:
            pbi = r.get("id")
        items.append(BidFrameItem(
            item_number=str(item_number),
            schedule=r.get("schedule_name") or r.get("schedule"),
            item_code=r.get("item_code") or r.get("cost_code"),
            description=r.get("description", ""),
            unit=r.get("unit", ""),
            project_bid_item_id=pbi,
            estimated_quantity=float(qty) if qty is not None else None,
        ))
    return items


def _one_line(text: str) -> str:
    """Collapse whitespace/newlines so comment lines stay comments."""
    return " ".join(str(text).split())


def takeoff_map_skeleton(items: list, *, organization_id: int,
                         project_ref: str | None = None) -> str:
    """Emit a takeoff_map.yaml seed (see bim/examples/takeoff_map.example.yaml):
    one codes: entry per bid item that carries an item_code, measure inferred
    from the pay unit. Code-less items are listed in a trailing comment block —
    they need a cost code (or manual mapping) before BIM rollup can hit them."""
    schedules = Counter(i.schedule for i in items if i.schedule)
    default_schedule = schedules.most_common(1)[0][0] if schedules else None

    codes: dict = {}
    unmapped = []
    collisions = []
    unconvertible = []
    for i in items:
        if not i.item_code:
            unmapped.append(i)
            continue
        measure = infer_measure(i.unit)
        if measure is None:
            unconvertible.append(i)
            continue
        if i.item_code in codes:
            collisions.append(i)   # first entry wins; surface the rest
            continue
        entry = {"measure": measure,
                 "unit": i.unit.strip(),
                 "item_number": i.item_number}
        if i.schedule:
            # A present-but-null key would override est-bim's defaults.schedule
            # (cfg.get("schedule", default)) — omit it so the default applies.
            entry["schedule"] = i.schedule
        codes[i.item_code] = entry

    doc: dict = {"organization_id": organization_id}
    if project_ref:
        doc["project_ref"] = project_ref
    if default_schedule:
        doc["defaults"] = {"schedule": default_schedule}
    doc["codes"] = codes

    text = (
        "# takeoff_map skeleton — seeded from the project's bid frame at intake.\n"
        "# Review each measure (inferred from the pay unit),\n"
        "# then use with: est-bim takeoff <model.ifc> --map <this file>\n"
        + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    )
    if unmapped:
        text += "\n# Bid items with no cost code — add codes: entries by hand:\n"
        for i in unmapped:
            text += (f"#   {i.item_number} ({i.schedule or '-'}): "
                     f"{_one_line(i.description)} [{i.unit}]\n")
    if collisions:
        text += ("\n# Bid items sharing an already-mapped cost code — "
                 "split codes by hand:\n")
        for i in collisions:
            text += (f"#   {i.item_number} ({i.schedule or '-'}): "
                     f"{_one_line(i.description)} [{i.unit}] "
                     f"(code {i.item_code} taken)\n")
    if unconvertible:
        text += ("\n# Bid items whose pay unit est-bim cannot convert — "
                 "choose a measurable proxy unit or take off by hand:\n")
        for i in unconvertible:
            text += (f"#   {i.item_number} ({i.schedule or '-'}): "
                     f"{_one_line(i.description)} [{i.unit}]\n")
    return text
