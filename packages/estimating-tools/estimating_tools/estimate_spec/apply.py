"""Bridge 2: CanonicalTakeoff -> estimate-spec quantities + takeoff geometry.

`apply_takeoff` matches measured takeoff rows onto spec items — (schedule,
item_number) primary, cost_code secondary, the same precedence as the BM push
path (takeoff/push.py) — then sets the item `qty` to the measured quantity and
rebuilds the item's takeoff from `row.elements`: CY = L*W*H/27, routed onto
the pack's `seed.takeoff_mapping` — its `section_types` map a CanonicalTakeoff
`section_type` to the {cy, cf} field pair it writes (an optional
`label_prefix` decorates the line's label, e.g. reference's DECK-prefixed
deck elements). Elements without full dimensions, or whose section_type the
pack doesn't map, become labeled zero lines plus an item note — visible, not
silent.

Non-destructive by default: an item whose qty or takeoff was hand-edited since
scaffold (scaffold_meta content hashes, scaffold.py) is skipped unless
`force=True`; items without scaffold_meta count as hand-authored. Every real
application appends a provenance note (`qty 104.44 from takeoff <ref> <date>`)
and re-running with the same takeoff is a no-op.

Pure: stdlib only. The CLI surface lives in cli.py (`est-estimate apply-takeoff`).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date as _date

from estimating_tools.estimate_spec.format_pack import RATE_HOST_SOURCE, bundled_pack, is_rate_host
from estimating_tools.estimate_spec.scaffold import content_hash, is_hand_edited


@dataclass
class ApplyResult:
    """The applied spec plus the honesty report (mirrors the push plan):
    matched (old->new qty), unchanged (no-op re-runs), skipped (hand-edited),
    unmatched rows, unmatched items, and per-item official-vs-measured deltas
    riding the matched/unchanged entries."""
    spec: dict
    matched: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    unmatched_rows: list = field(default_factory=list)
    unmatched_items: list = field(default_factory=list)


def _item_schedule(item: dict):
    meta = item.get("scaffold_meta")
    return meta.get("schedule") if isinstance(meta, dict) else None


def _match_item(row, items: list):
    """(schedule, item_number) primary; cost_code secondary (unique-only) —
    the push-path precedence. Schedules match exactly first (None == None,
    like takeoff/push.py's _match_existing); an item without a recorded
    schedule (hand-authored, no scaffold_meta) is only a fallback, and only
    when unique — a schedule-less item never steals a row from an exact
    scheduled match, and an ambiguous fallback stays unmatched."""
    def _fallback(candidates):
        loose = [it for it in candidates
                 if (_item_schedule(it) is None) != (row.schedule is None)]
        return loose[0] if len(loose) == 1 else None

    if row.item_number:
        candidates = [it for it in items if it.get("item_no") == row.item_number]
        exact = [it for it in candidates if _item_schedule(it) == row.schedule]
        if exact:
            return exact[0]
        return _fallback(candidates)
    if row.cost_code:
        candidates = [it for it in items if it.get("cost_code") == row.cost_code]
        exact = [it for it in candidates if _item_schedule(it) == row.schedule]
        if len(exact) == 1:
            return exact[0]
        if not exact:
            return _fallback(candidates)
    return None


def element_to_line(el: dict, pack=None) -> tuple[dict, str | None]:
    """One takeoff element -> one geometry line (+ a note when the element
    cannot carry CY). Dimensions are FEET; CY = L*W*H/27 (x count).

    Column routing comes from the pack's ``seed.takeoff_mapping``:
    ``section_types`` maps a CanonicalTakeoff ``section_type`` to the
    {cy, cf} field pair it writes (plus an optional ``label_prefix``);
    ``line_fields`` is zero-initialised on every line so the shape is
    uniform whether or not this element routes."""
    tm = (pack or bundled_pack()).seed["takeoff_mapping"]
    section_types = tm["section_types"]
    name = el.get("name") or "(unnamed)"
    stype = el.get("section_type") or "other"
    count = max(int(el.get("count") or 1), 1)
    entry = section_types.get(stype)
    prefix = entry.get("label_prefix") if entry else None
    label = f"{prefix} {name}" if prefix else name
    if count > 1:
        label += f" x{count}"
    length = el.get("length_ft")
    width = el.get("width_ft")
    height = el.get("height_ft")

    line = {"label": label,
            "length": round(length, 4) if length is not None else 0,
            "height": round(height, 4) if height is not None else 0,
            **{f: 0 for f in tm["line_fields"]}}

    complete = None not in (length, width, height)
    if not complete:
        missing = [d for d, v in (("length", length), ("width", width),
                                  ("height", height)) if v is None]
        return line, (f"{name}: missing {'/'.join(missing)} — zero CY line "
                      "(measure by hand)")
    if entry is None:
        return line, (f"{name}: section_type {stype!r} has no CY column — "
                      "zero CY line (measure by hand)")

    cf = length * width * height * count
    cy = cf / 27.0
    line[entry["cy"]] = round(cy, 4)
    line[entry["cf"]] = round(cf, 2)
    return line, None


def build_geometry(elements: list, pack=None) -> tuple[dict, list]:
    """row.elements -> a geometry takeoff block + notes for zero-CY lines."""
    tm = (pack or bundled_pack()).seed["takeoff_mapping"]
    lines, notes = [], []
    for el in elements:
        line, note = element_to_line(el, pack)
        lines.append(line)
        if note:
            notes.append(f"apply-takeoff: {note}")
    return {"kind": tm["kind"], "lines": lines}, notes


def apply_takeoff(spec: dict, takeoff, *, pack=None, force: bool = False,
                  today: str | None = None) -> ApplyResult:
    """Apply a CanonicalTakeoff to an estimate spec. Returns a new spec (the
    input is not mutated) plus the report. Idempotent: re-running with the
    same takeoff changes nothing and appends no notes."""
    pack = pack or bundled_pack()
    rate_host_recipe = pack.seed["scaffold"]["rate_host_recipe"]
    new_spec = copy.deepcopy(spec)
    items = new_spec.get("items", [])
    result = ApplyResult(spec=new_spec)
    stamp = today or _date.today().isoformat()
    ref = getattr(takeoff, "project_ref", None) or "takeoff"
    hit: set = set()

    for row in takeoff.rows:
        if row.kind != "quantity":
            result.unmatched_rows.append({
                "item_number": row.item_number, "schedule": row.schedule,
                "description": row.description, "quantity": row.quantity,
                "unit": row.unit, "reason": f"unsupported row kind {row.kind!r}"})
            continue
        item = _match_item(row, items)
        if item is None:
            result.unmatched_rows.append({
                "item_number": row.item_number, "schedule": row.schedule,
                "description": row.description, "quantity": row.quantity,
                "unit": row.unit, "reason": "no spec item matches"})
            continue
        if id(item) in hit:
            # issue #106 addendum: two rows sharing (schedule, item_number)
            # must never silently last-wins the item's qty — flag, don't clobber
            result.unmatched_rows.append({
                "item_number": row.item_number, "schedule": row.schedule,
                "description": row.description, "quantity": row.quantity,
                "unit": row.unit,
                "reason": "item already matched by another takeoff row (rows "
                          "share schedule/item_number) — resolve in the "
                          "takeoff map"})
            continue
        hit.add(id(item))
        item_meta = item.get("scaffold_meta")
        entry = {
            "item_no": item.get("item_no"),
            "schedule": row.schedule,
            "old_qty": item.get("qty"),
            "new_qty": round(float(row.quantity), 2),
            "official_qty": (item_meta.get("official_qty")
                             if isinstance(item_meta, dict) else None),
            "measured_qty": row.quantity,
            "unit": row.unit,
        }
        new_qty = entry["new_qty"]
        new_takeoff, geo_notes = (build_geometry(row.elements, pack)
                                  if row.elements else (None, []))
        unchanged = (item.get("qty") == new_qty
                     and (new_takeoff is None or item.get("takeoff") == new_takeoff))
        if unchanged:
            result.unchanged.append(entry)
            continue
        if not force and is_hand_edited(item):
            meta = item.get("scaffold_meta")
            reason = ("no scaffold_meta (hand-authored spec)" if not meta
                      else "qty/takeoff hand-edited since scaffold")
            result.skipped.append({"item_no": item.get("item_no"),
                                   "reason": f"{reason} — re-run with --force to overwrite"})
            continue

        item["qty"] = new_qty
        if new_takeoff is not None and item.get("recipe") != rate_host_recipe:
            item["takeoff"] = new_takeoff
        notes = list(item.get("notes") or [])
        notes.append(f"qty {new_qty:.2f} from takeoff {ref} {stamp}")
        notes.extend(n for n in geo_notes if n not in notes)
        item["notes"] = notes

        meta = item.get("scaffold_meta")
        if not isinstance(meta, dict):
            meta = {"source": f"apply:{ref}", "schedule": row.schedule,
                    "official_qty": None, "field_hashes": {}}
            item["scaffold_meta"] = meta
        hashes = dict(meta.get("field_hashes") or {})
        hashes["qty"] = content_hash(item.get("qty"))
        if "takeoff" in item:
            hashes["takeoff"] = content_hash(item["takeoff"])
        meta["field_hashes"] = hashes
        result.matched.append(entry)

    for item in items:
        # The rate host is never a takeoff target (format_pack.is_rate_host:
        # every rate-host-recipe item, or only the injected host for a pack
        # whose host recipe is also a bid-item recipe, e.g. fieldbook's
        # lump_sum -- its real lump-sum items are listed when unmatched).
        if id(item) in hit or is_rate_host(item, pack):
            continue
        meta = item.get("scaffold_meta") or {}
        if meta.get("source") == RATE_HOST_SOURCE:
            continue
        result.unmatched_items.append({"item_no": item.get("item_no"),
                                       "description": item.get("description", "")})
    return result


# ---------- report render ----------

def _fmt(value) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".") if value % 1 else f"{value:,.0f}"
    return str(value)


def render_apply_report(result: ApplyResult) -> str:
    """Markdown report mirroring the push plan's honesty: matched (old->new),
    unmatched both directions, skipped-as-hand-edited, and the official vs
    measured delta per item (the advisory check, workbook-side)."""
    from estimating_tools.artifacts import md_table

    applied = result.matched
    lines = ["# Apply-takeoff report", "",
             (f"{len(applied)} applied, {len(result.unchanged)} unchanged, "
              f"{len(result.skipped)} skipped, "
              f"{len(result.unmatched_rows)} unmatched rows, "
              f"{len(result.unmatched_items)} unmatched items."), ""]

    rows = [[_fmt(e["item_no"]), _fmt(e["schedule"]), _fmt(e["old_qty"]),
             _fmt(e["new_qty"]), _fmt(e["unit"])]
            for e in applied + result.unchanged]
    lines += ["## Matched (old -> new qty)", "",
              md_table(["item_no", "schedule", "old_qty", "new_qty", "unit"], rows), ""]

    adv = []
    for e in applied + result.unchanged:
        official = e.get("official_qty")
        measured = e.get("measured_qty")
        delta = (measured - official) if (official is not None and measured is not None) else None
        adv.append([_fmt(e["item_no"]), _fmt(official), _fmt(measured),
                    _fmt(delta), _fmt(e["unit"])])
    lines += ["## Official vs measured (advisory — official quantities are "
              "never overwritten in BidSheet.ai; BM #984)", "",
              md_table(["item_no", "official_qty", "measured_qty", "delta", "unit"], adv), ""]

    lines += ["## Skipped (hand-edited since scaffold)", "",
              md_table(["item_no", "reason"],
                       [[_fmt(s["item_no"]), _fmt(s["reason"])] for s in result.skipped]), ""]
    lines += ["## Unmatched takeoff rows", "",
              md_table(["item_number", "schedule", "description", "quantity", "unit", "reason"],
                       [[_fmt(r["item_number"]), _fmt(r["schedule"]), _fmt(r["description"]),
                         _fmt(r["quantity"]), _fmt(r["unit"]), _fmt(r["reason"])]
                        for r in result.unmatched_rows]), ""]
    lines += ["## Spec items with no takeoff row", "",
              md_table(["item_no", "description"],
                       [[_fmt(i["item_no"]), _fmt(i["description"])]
                        for i in result.unmatched_items]), ""]
    return "\n".join(lines)
