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

Merge rule (issue #376). One bid item can be measured by more than one
takeoff: rebar in a bridge model and in an approach-slab model, each taken
off and applied on its own. Lines and quantity are therefore OWNED by the
takeoff that wrote them, recorded per item in `scaffold_meta.takeoffs`: an
ordered list of {source, name, qty, unit, lines, lines_hash[, global_ids,
element_names]}, each entry owning `lines` consecutive lines at the end of
`takeoff.lines`, in list order, whose content hash is `lines_hash`.

- Identity: a takeoff is `--source-id` when given, else its own
  `source_id`, else the NAME of its file (the stem; the CLI passes it).
  Never its element GlobalIds (per-structure models of one project derive
  them from one namespace, so two structures can share one) and never its
  project_ref (every takeoff of a project shares it). So: name per-structure
  takeoff files distinctly, and keep the same name when re-measuring a
  structure. A generic stem (`takeoff`, `rebar`, `schedule`, ... —
  GENERIC_TAKEOFF_NAMES) with no source_id names no structure, so its rows
  are REFUSED: `bridge/takeoff.json` then `approach/takeoff.json` would
  otherwise replace each other.
- Applying takeoff B to an item that holds takeoff A's lines keeps A's lines
  and quantity and appends B's; the item `qty` is the sum of every
  contributor's quantity. Re-applying a takeoff of the same identity
  replaces only its own lines and quantity, in place, and re-sums
  (idempotent: the same takeoff twice is a no-op).
- Element GlobalIds and names are recorded per contributor only to WARN:
  "possible double count" when two identities share GlobalIds, or when one's
  element names all appear in the other's (what a federated takeoff looks
  like beside a per-structure one: federation re-namespaces GlobalIds, and
  the takeoff JSON carries no federation marker); and when a takeoff
  replaces its own earlier lines but shares no GlobalId with them (two
  structures given one file name?). Federated and per-structure takeoffs
  must not be mixed on one spec: their quantities add.
- Units: each contributor records its unit (compared upper-cased, without
  dots or spaces, with the long spellings folded: C.Y. = CY, SQ FT = SF,
  TN = TON). A row whose unit differs from the item's `uom`, or from the
  unit other takeoffs gave the item, is REFUSED: the item is left as it was
  and the report lists it.
- Integrity: if a contributor's block no longer hashes to its `lines_hash`
  (lines added, removed or edited by hand, then --force), nothing is sliced:
  every existing line is kept, owned by no takeoff, with a warning; the
  quantities stay per contributor.
- Older specs (a `qty ... from takeoff` note, no `takeoffs` record): if the
  takeoff being applied writes exactly the lines already there, it is the
  takeoff that wrote them — it takes ownership (replace, no sum, no
  warning). Otherwise the row is REFUSED (who owns those lines is unknown;
  summing could double count, replacing could drop a structure): re-apply
  with --adopt-legacy (`adopt_legacy=True`) to make this takeoff the owner
  of such items — it replaces their lines and qty with its own, no sum —
  or apply the takeoff that wrote them. `--adopt-legacy` touches ONLY items
  with no ownership record; items that record owners merge as usual. An
  item with no
  record and no earlier apply, or an empty record (`takeoffs: []`, written
  by `scaffold --merge` when it puts the scaffold geometry back), is owned
  by no takeoff: a row with elements replaces the scaffold geometry.
- `replace=True` (`--replace`) is the blunt escape hatch: this takeoff's
  rows replace everything on EVERY item they match, merged items included
  (the behaviour before #376), dropping other takeoffs' lines and quantity
  there, with a warning naming each contributor dropped. To take over
  legacy items without touching merged ones, use --adopt-legacy.

The report lists each item more than one takeoff contributed to ("item 61:
2 takeoffs contributed (bridge, approach-slabs)"), every warning, and every
refused row.

Pure: stdlib only. The CLI surface lives in cli.py (`est-estimate apply-takeoff`).
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import date as _date

from estimating_tools.estimate_spec.format_pack import RATE_HOST_SOURCE, bundled_pack, is_rate_host
from estimating_tools.estimate_spec.scaffold import (
    PLACEHOLDER_GEOMETRY_LABEL, content_hash, is_hand_edited)

#: the provenance note an apply writes; on an item with no `takeoffs` record
#: it marks lines written by an apply that predates ownership (#376)
_PRIOR_APPLY_NOTE = re.compile(r"^qty \S+ from takeoff ")
UNNAMED_SOURCE = "(unnamed)"
#: file stems that name no structure: a takeoff whose identity would fall
#: back to one of these (no source_id) is refused, since two structures'
#: `takeoff.json` would replace each other
GENERIC_TAKEOFF_NAMES = frozenset({
    "takeoff", "takeoffs", "rebar", "schedule", "quantities", "quantity",
    "bars", "bar-schedule", "model", "export"})
GENERIC_NAME_REFUSAL = ("the takeoff has no name of its own — name the "
                        "takeoff: --source-id or a per-structure file name")
LEGACY_REFUSAL = ("this item's lines predate takeoff ownership; re-apply with "
                  "--adopt-legacy to make this takeoff their owner (it "
                  "replaces this item's lines and qty; items other takeoffs "
                  "already share are left to the normal merge), or apply the "
                  "takeoff that wrote them")


class _Refused(Exception):
    """A row that must not be applied; the message is the report reason."""


@dataclass
class ApplyResult:
    """The applied spec plus the honesty report (mirrors the push plan):
    matched (old->new qty), unchanged (no-op re-runs), skipped (hand-edited),
    unmatched rows, unmatched items, and per-item official-vs-measured deltas
    riding the matched/unchanged entries. `merged` lists the items more than
    one takeoff contributed to ({item_no, schedule, takeoffs: [names]});
    `warnings` the kept-unowned / replaced / possible-double-count lines;
    `refused` the rows not applied ({item_no, schedule, reason}: a generic
    takeoff name, a unit that would not add up, lines that predate
    ownership; the item is left as it was) — issue #376."""
    spec: dict
    matched: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    unmatched_rows: list = field(default_factory=list)
    unmatched_items: list = field(default_factory=list)
    merged: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    refused: list = field(default_factory=list)


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


_UNIT_ALIASES = {"CUYD": "CY", "CUFT": "CF", "SQFT": "SF", "SQYD": "SY",
                 "LNFT": "LF", "LINFT": "LF", "LBS": "LB", "POUND": "LB",
                 "POUNDS": "LB", "TONS": "TON", "TN": "TON", "EACH": "EA",
                 "LUMPSUM": "LS"}


def _unit(value) -> str:
    """A unit compared across takeoffs and the item's uom: upper-cased, with
    the long spellings the packs accept folded onto the short ones."""
    u = str(value or "").upper().replace(".", "").replace(" ", "")
    return _UNIT_ALIASES.get(u, u)


def _row_global_ids(row) -> list:
    """The IFC GlobalIds behind a row's elements, sorted and unique."""
    return sorted({str(el["global_id"]) for el in row.elements or ()
                   if isinstance(el, dict) and el.get("global_id")})


def _row_element_names(row) -> list:
    return sorted({str(el["name"]) for el in row.elements or ()
                   if isinstance(el, dict) and el.get("name")})


def _applied_before(item: dict) -> bool:
    """An apply that predates ownership records left its provenance note
    (or created the item's scaffold_meta) but no `takeoffs` record."""
    meta = item.get("scaffold_meta")
    if isinstance(meta, dict) and str(meta.get("source", "")).startswith("apply:"):
        return True
    return any(isinstance(n, str) and _PRIOR_APPLY_NOTE.match(n)
               for n in item.get("notes") or ())


def _placeholder_line(pack) -> dict:
    """A zeroed line in the pack's takeoff line shape (as element_to_line
    writes it), labelled as the scaffold placeholder so real lines replace
    it when they arrive."""
    tm = pack.seed["takeoff_mapping"]
    return {"label": PLACEHOLDER_GEOMETRY_LABEL, "length": 0, "height": 0,
            **{f: 0 for f in tm["line_fields"]}}


def _contributor_name(contributor: dict) -> str:
    return contributor.get("name") or contributor.get("source") or "takeoff"


def _overlap(mine: dict, other: dict) -> str | None:
    """Why two contributors of different identity may measure the same
    elements (a warning, never a merge decision): shared GlobalIds, or one's
    element names all among the other's — what a federated takeoff looks
    like next to a per-structure one (federation re-namespaces GlobalIds)."""
    shared = set(mine.get("global_ids") or ()) & set(other.get("global_ids") or ())
    if shared:
        return f"{len(shared)} shared element GlobalId(s)"
    a = set(mine.get("element_names") or ())
    b = set(other.get("element_names") or ())
    if a and b and (a <= b or b <= a):
        return ("the element names of one all appear in the other "
                "(a federated takeoff next to a per-structure one?)")
    return None


def _merge_item(item: dict, *, mine: dict, own_lines: list,
                takeoff_kind: str, replace: bool,
                adopt_legacy: bool = False) -> tuple[list, list, list]:
    """The item's contributors after `mine` is applied, the merged takeoff
    lines, and any warnings (the merge rule, module docstring). Pure: reads
    `item`, never mutates it."""
    item_no = item.get("item_no")
    name = mine["name"]
    warnings: list = []
    meta = item.get("scaffold_meta")
    record = meta.get("takeoffs") if isinstance(meta, dict) else None
    existing = item.get("takeoff")
    mergeable = (isinstance(existing, dict) and existing.get("kind") == takeoff_kind
                 and isinstance(existing.get("lines"), list))
    cur_lines = list(existing["lines"]) if mergeable else []

    if not isinstance(record, list) or not record:
        if record is None and _applied_before(item) and not replace:
            # lines from an apply that recorded no owner: they are this
            # takeoff's only if this takeoff writes exactly them
            # (or the caller said this takeoff adopts unowned legacy items)
            if not adopt_legacy and not (
                    own_lines and content_hash(own_lines) == content_hash(cur_lines)):
                raise _Refused(LEGACY_REFUSAL)
        # no takeoff owns anything here (never applied, adopted above, or
        # scaffold --merge put the scaffold geometry back): real lines
        # replace the scaffold's
        record = []
        if own_lines:
            cur_lines = []
    elif not mergeable:
        if isinstance(existing, dict) and any(int(c.get("lines") or 0) for c in record):
            warnings.append(
                f"item {item_no}: its takeoff is kind {existing.get('kind')!r}, "
                f"not this format's {takeoff_kind!r} — "
                + ("replaced by this takeoff's lines" if own_lines
                   else "left as it is")
                + "; the other takeoffs' quantities are kept")
    record = [dict(c) for c in record]
    if not mergeable:
        for c in record:
            c["lines"], c["lines_hash"] = 0, content_hash([])

    # each contributor's block, verified against the hash it recorded
    owned = sum(int(c.get("lines") or 0) for c in record)
    intact = owned <= len(cur_lines)
    if intact:
        pos = len(cur_lines) - owned
        prefix, blocks = cur_lines[:pos], []
        for c in record:
            block = cur_lines[pos:pos + int(c.get("lines") or 0)]
            pos += len(block)
            blocks.append(block)
            if c.get("lines_hash") != content_hash(block):
                intact = False
    if not intact:
        warnings.append(
            f"item {item_no}: the takeoff lines no longer match what the "
            "recorded takeoffs wrote (edited by hand?) — all "
            f"{len(cur_lines)} existing line(s) are kept, owned by no takeoff; "
            "check them for duplicates")
        prefix, blocks = cur_lines, [[] for _ in record]
        for c in record:
            c["lines"], c["lines_hash"] = 0, content_hash([])

    new_record, new_blocks, dropped, placed = [], [], [], False
    for c, block in zip(record, blocks):
        if c.get("source") == mine["source"]:
            if not placed:
                new_record.append(mine)
                new_blocks.append(own_lines)
                placed = True
            continue
        if replace:
            dropped.append(_contributor_name(c))
            continue
        why = _overlap(mine, c)
        if why:
            warnings.append(
                f"item {item_no}: possible double count — {name} and "
                f"{_contributor_name(c)} may measure the same elements ({why})")
        new_record.append(c)
        new_blocks.append(block)
    if not placed:
        new_record.append(mine)
        new_blocks.append(own_lines)
    if own_lines:
        prefix = [ln for ln in prefix
                  if not (isinstance(ln, dict)
                          and ln.get("label") == PLACEHOLDER_GEOMETRY_LABEL)]
    if replace and prefix:
        dropped.append(f"{len(prefix)} unowned line(s)")
        prefix = []
    if dropped:
        warnings.append(f"item {item_no}: {name} replaced lines it did not own "
                        f"({', '.join(dropped)}) — --replace")
    lines = prefix + [ln for block in new_blocks for ln in block]
    return new_record, lines, warnings


def apply_takeoff(spec: dict, takeoff, *, pack=None, force: bool = False,
                  replace: bool = False, adopt_legacy: bool = False,
                  source_name: str | None = None,
                  source_id: str | None = None,
                  today: str | None = None) -> ApplyResult:
    """Apply a CanonicalTakeoff to an estimate spec. Returns a new spec (the
    input is not mutated) plus the report. Idempotent: re-running with the
    same takeoff changes nothing and appends no notes. Takeoffs applied in
    sequence merge into the items they share (module docstring); `replace`
    restores last-wins for this takeoff's items. A takeoff's identity is its
    `source_id` argument (`--source-id`), else the takeoff's own
    `source_id`, else `source_name` (the CLI passes the takeoff file's
    stem; a generic stem such as `takeoff` is refused); a library caller
    that passes none applies one `(unnamed)` takeoff, which every later
    unnamed apply replaces."""
    pack = pack or bundled_pack()
    rate_host_recipe = pack.seed["scaffold"]["rate_host_recipe"]
    takeoff_kind = pack.seed["takeoff_mapping"]["kind"]
    new_spec = copy.deepcopy(spec)
    items = new_spec.get("items", [])
    result = ApplyResult(spec=new_spec)
    stamp = today or _date.today().isoformat()
    named = source_id or getattr(takeoff, "source_id", None)
    identity = named or source_name or UNNAMED_SOURCE
    generic_name = (not named and bool(source_name)
                    and source_name.strip().lower() in GENERIC_TAKEOFF_NAMES)
    ref = (identity if identity != UNNAMED_SOURCE
           else getattr(takeoff, "project_ref", None) or "takeoff")
    hit: set = set()
    # A takeoff that replaces what its identity wrote before, yet shares no
    # element GlobalId with any of it, may be another structure under the
    # same file name. Judged over the whole takeoff, not per row: a revised
    # model whose wall element was replaced still shares its footing (#441).
    before_gids = {g for it in items
                   for c in ((it.get("scaffold_meta") or {}).get("takeoffs") or ())
                   if isinstance(c, dict) and c.get("source") == identity
                   for g in c.get("global_ids") or ()}
    takeoff_gids = {g for row in takeoff.rows for g in _row_global_ids(row)}

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
        record_now = (item_meta.get("takeoffs")
                      if isinstance(item_meta, dict) else None)

        if generic_name:
            result.refused.append({"item_no": item.get("item_no"),
                                   "schedule": row.schedule,
                                   "reason": f"{GENERIC_NAME_REFUSAL} "
                                             f"(file name {source_name!r}) — not applied"})
            continue
        # units: a quantity never adds across units (refused, item untouched)
        row_unit = _unit(row.unit)
        if row_unit:
            uom = _unit(item.get("uom"))
            others = sorted({_unit(c.get("unit")) for c in record_now or ()
                             if isinstance(c, dict) and c.get("unit")
                             and c.get("source") != identity} - {row_unit})
            reason = None
            if uom and uom != row_unit:
                reason = (f"takeoff unit {row.unit} does not match the item's "
                          f"uom {item.get('uom')}")
            elif others and not replace:
                reason = (f"takeoff unit {row.unit} does not match the unit "
                          f"other takeoffs gave this item ({', '.join(others)})")
            if reason:
                result.refused.append({"item_no": item.get("item_no"),
                                       "schedule": row.schedule,
                                       "reason": f"{reason} — not applied"})
                continue

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
        new_takeoff, geo_notes = (build_geometry(row.elements, pack)
                                  if row.elements else (None, []))
        is_host = item.get("recipe") == rate_host_recipe
        own_lines = new_takeoff["lines"] if (new_takeoff and not is_host) else []
        mine = {"source": identity, "name": identity,
                "qty": round(float(row.quantity), 4),
                "lines": len(own_lines), "lines_hash": content_hash(own_lines)}
        if row_unit:
            mine["unit"] = row_unit
        gids, names = _row_global_ids(row), _row_element_names(row)
        if gids:
            mine["global_ids"] = gids
        if names:
            mine["element_names"] = names

        try:
            record, lines, warnings = _merge_item(
                item, mine=mine, own_lines=own_lines,
                takeoff_kind=takeoff_kind, replace=replace,
                adopt_legacy=adopt_legacy)
        except _Refused as exc:
            result.refused.append({"item_no": item.get("item_no"),
                                   "schedule": row.schedule,
                                   "reason": f"{exc} — not applied"})
            continue
        total = sum(float(c.get("qty") or 0) for c in record)
        new_qty = round(total, 2)
        entry["new_qty"] = new_qty
        entry["measured_qty"] = round(total, 4)
        item_takeoff = item.get("takeoff")
        if lines and not is_host:
            item_takeoff = {"kind": takeoff_kind, "lines": lines}
        elif (not is_host and isinstance(item_takeoff, dict)
              and item_takeoff.get("kind") == takeoff_kind
              and item_takeoff.get("lines")):
            # every line was dropped (a takeoff with no elements replaced
            # the only lines there): keep the takeoff schema-valid with an
            # unowned placeholder line, never the dropped geometry (#441)
            item_takeoff = {"kind": takeoff_kind,
                            "lines": [_placeholder_line(pack)]}
        merged = ({"item_no": item.get("item_no"), "schedule": row.schedule,
                   "takeoffs": [_contributor_name(c) for c in record]}
                  if len(record) > 1 else None)

        if (item.get("qty") == new_qty and item.get("takeoff") == item_takeoff
                and record_now == record):
            result.unchanged.append(entry)
            if merged:
                result.merged.append(merged)
            continue
        if not force and is_hand_edited(item):
            meta = item.get("scaffold_meta")
            reason = ("no scaffold_meta (hand-authored spec)" if not meta
                      else "qty/takeoff hand-edited since scaffold")
            result.skipped.append({"item_no": item.get("item_no"),
                                   "reason": f"{reason} — re-run with --force to overwrite"})
            continue

        item["qty"] = new_qty
        if item_takeoff is not None:
            item["takeoff"] = item_takeoff
        notes = list(item.get("notes") or [])
        note = f"qty {new_qty:.2f} from takeoff {ref} {stamp}"
        if merged:
            note += (f" (sum of {len(record)} takeoffs: "
                     f"{', '.join(merged['takeoffs'])})")
        notes.append(note)
        notes.extend(n for n in geo_notes if n not in notes)
        item["notes"] = notes

        meta = item.get("scaffold_meta")
        if not isinstance(meta, dict):
            meta = {"source": f"apply:{ref}", "schedule": row.schedule,
                    "official_qty": None, "field_hashes": {}}
            item["scaffold_meta"] = meta
        meta["takeoffs"] = record
        hashes = dict(meta.get("field_hashes") or {})
        hashes["qty"] = content_hash(item.get("qty"))
        if "takeoff" in item:
            hashes["takeoff"] = content_hash(item["takeoff"])
        meta["field_hashes"] = hashes
        result.matched.append(entry)
        result.warnings.extend(warnings)
        if merged:
            result.merged.append(merged)

    if (result.matched and before_gids and takeoff_gids
            and not before_gids & takeoff_gids):
        result.warnings.append(
            f"takeoff {identity}: replaced its earlier lines but shares no "
            "element GlobalId with them — if these are different structures, "
            "give each takeoff file its own name (or source_id)")

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
              f"{len(result.unmatched_items)} unmatched items"
              + (f", {len(result.refused)} refused" if result.refused else "")
              + "."), ""]

    if result.merged:
        # issue #376: a reviewer sees which items more than one takeoff fed
        lines += ["## Items more than one takeoff contributed to", ""]
        lines += [f"- item {m['item_no']}: {len(m['takeoffs'])} takeoffs "
                  f"contributed ({', '.join(m['takeoffs'])})"
                  for m in result.merged]
        lines += ["", "Quantities from different takeoffs ADD: a federated "
                  "takeoff and the per-structure takeoffs it combines must "
                  "not both be applied to one spec.", ""]
    if result.refused:
        lines += ["## Refused (not applied — item left as it was)", ""]
        lines += [f"- item {r['item_no']}: {r['reason']}" for r in result.refused]
        lines.append("")
    if result.warnings:
        lines += ["## Warnings", ""]
        lines += [f"- {w}" for w in result.warnings]
        lines.append("")

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
