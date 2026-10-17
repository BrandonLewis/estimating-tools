"""Bridge 1 + Bridge 3: briefing outputs -> estimate-spec skeleton.

`scaffold_spec` turns the intake contract (manifest.json's bid frame +
Briefing/structures.yaml rollups) into a schema-valid ``*.estimate.yaml``
config: one item per selected bid-frame entry, the pack's rate-host recipe
(``seed.scaffold.rate_host_recipe``) for mobilization-class items (org-profile
item codes, description-regex fallback), the pack's default item recipe
(``seed.scaffold.default_item_recipe``, carrying a pack-shaped placeholder
takeoff when the pack declares one) otherwise. Labor /
crews / cost_details prefill resolves scaffold-from-template precedence:
BM bid-item scaffolds (scaffolds.json, fetched by the agent) > org profile
``estimate_scaffolds.yaml`` > blank skeleton — provenance recorded per item in
``scaffold_meta`` (source + content hash per scaffold-owned field, plus the
bid frame's schedule and official quantity for Bridge 2).

Pure logic: stdlib + pyyaml (+ jsonschema for spec/scaffold validation).
No MCP, no network — the agent supplies fetched context as files (house
pattern). The CLI surface lives in cli.py (``est-estimate scaffold``).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from estimating_tools.estimate_spec.format_pack import bundled_pack

# Fallback mobilization classifier when the org profile declares no
# estimating.mob_item_codes: LS items whose description says mobilization.
MOB_DESC_RE = re.compile(r"mobili[sz]ation", re.IGNORECASE)

# Fields the scaffold owns (hashes recorded in scaffold_meta.field_hashes).
# apply-takeoff treats a hash mismatch on qty/takeoff as a hand edit.
SCAFFOLD_OWNED_FIELDS = ("description", "uom", "qty", "takeoff", "labor")

PLACEHOLDER_GEOMETRY_LABEL = "placeholder (apply-takeoff fills real geometry)"

_EXCEL_SHEET_BAD = re.compile(r"[\[\]:*?/\\]")


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

def content_hash(value) -> str:
    """Stable content hash of a spec field value (canonical-JSON sha256)."""
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def field_hashes(item: dict) -> dict:
    """Hash every scaffold-owned field present on `item`."""
    return {f: content_hash(item[f]) for f in SCAFFOLD_OWNED_FIELDS if f in item}


def is_hand_edited(item: dict, fields=("qty", "takeoff")) -> bool:
    """True when any of `fields` no longer matches its scaffold_meta hash.

    Items without scaffold_meta count as hand-edited (hand-authored specs are
    never silently rewritten). Fields outside scaffold_meta.field_hashes never
    block (the spec's rule: edits outside scaffold-owned fields don't count).
    """
    meta = item.get("scaffold_meta")
    if not isinstance(meta, dict):
        return True
    hashes = meta.get("field_hashes") or {}
    for f in fields:
        if f in hashes and content_hash(item.get(f)) != hashes[f]:
            return True
    return False


# ---------------------------------------------------------------------------
# scaffold entries (Bridge 3): scaffolds.json / profile estimate_scaffolds.yaml
# ---------------------------------------------------------------------------

PROFILE_SCAFFOLDS_FILENAME = "estimate_scaffolds.yaml"


def _entry_schema(pack=None) -> dict:
    """The scaffolds.json entry schema — fragments of the pack's estimate-spec
    item schema itself (labor_block / crews / cost_detail), so prefill is splice-in."""
    root = (pack or bundled_pack()).schema
    defs = root["$defs"]
    return {
        "$defs": defs,
        "type": "object",
        "additionalProperties": False,
        "required": ["item_code", "source"],
        "properties": {
            "item_code": {"type": "string", "minLength": 1},
            "source": {"type": "string", "minLength": 1},
            "labor": {"type": "array", "minItems": 1,
                      "items": {"$ref": "#/$defs/labor_block"}},
            "crews": root["properties"]["crews"],
            "cost_details": {"type": "array",
                             "items": {"$ref": "#/$defs/cost_detail"}},
        },
    }


def validate_scaffold_entries(entries, *, where: str = "scaffolds", pack=None) -> None:
    """Validate a list of scaffold entries against OUR entry schema (the CLI
    validates our schema; server-shape drift surfaces here, loudly)."""
    import jsonschema

    if not isinstance(entries, list):
        raise ValueError(f"{where}: expected a list of scaffold entries, "
                         f"got {type(entries).__name__}")
    schema = _entry_schema(pack)
    for i, entry in enumerate(entries):
        try:
            jsonschema.validate(entry, schema)
        except jsonschema.ValidationError as exc:
            path = "$" + "".join(f"[{p!r}]" for p in exc.absolute_path)
            raise ValueError(
                f"{where}[{i}]: invalid scaffold entry at {path}: {exc.message}"
            ) from exc


def load_scaffolds_file(path: Path, *, pack=None) -> dict:
    """Load + validate scaffolds.json -> {item_code: entry}."""
    entries = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_scaffold_entries(entries, where=str(path), pack=pack)
    return {e["item_code"]: e for e in entries}


def load_profile_scaffolds(profile_dirs, *, pack=None) -> dict:
    """Load `estimate_scaffolds.yaml` from profile source dirs (cascade order,
    later dirs win per key). Entries default their `source` to the profile file."""
    import yaml

    out: dict = {}
    for d in profile_dirs:
        f = Path(d) / PROFILE_SCAFFOLDS_FILENAME
        if not f.is_file():
            continue
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        entries = doc.get("scaffolds", []) if isinstance(doc, dict) else []
        for e in entries:
            if isinstance(e, dict) and "source" not in e:
                e["source"] = f"profile:{PROFILE_SCAFFOLDS_FILENAME}"
        validate_scaffold_entries(entries, where=str(f), pack=pack)
        out.update({e["item_code"]: e for e in entries})
    return out


# ---------------------------------------------------------------------------
# item selection + classification
# ---------------------------------------------------------------------------

def _frame_get(entry, key, default=None):
    """Bid-frame entries arrive as BidFrameItem dataclasses or plain dicts."""
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def is_mob_item(entry, mob_codes=()) -> bool:
    """mob_item classification: org-profile item codes first, then the
    description regex — LS-unit items only (mobilization-class = lump sum)."""
    unit = (str(_frame_get(entry, "unit") or "")).strip().upper()
    if unit != "LS":
        return False
    code = _frame_get(entry, "item_code")
    if mob_codes and code and code in set(mob_codes):
        return True
    return bool(MOB_DESC_RE.search(str(_frame_get(entry, "description") or "")))


def structure_rollup_index(structures: list) -> dict:
    """structures.yaml -> {(schedule|None, item_number): structure_id}.

    A rollup bid_items entry is `{item_number, schedule?}` (briefing.py's
    frontmatter contract) or a bare item-number string. First structure wins
    on collision — an item pays one owning structure's sheet."""
    index: dict = {}
    for s in structures or []:
        sid = s.get("id")
        for bi in s.get("bid_items") or []:
            if isinstance(bi, dict):
                key = (bi.get("schedule"), str(bi.get("item_number")))
            else:
                key = (None, str(bi))
            index.setdefault(key, sid)
    return index


def _owning_structure(entry, index: dict):
    number = str(_frame_get(entry, "item_number"))
    return (index.get((_frame_get(entry, "schedule"), number))
            or index.get((None, number)))


def select_items(bid_frame: list, structures: list, selection: str = "structures",
                 mob_codes=()) -> list:
    """Pick bid-frame entries per --items. Returns [(entry, structure_id|None)].

    - "structures" (default): rollup-referenced items + mob items — the
      self-perform frame.
    - "all": the whole schedule.
    - CSV of item_numbers: cherry-pick (mob items are still included — the
      mob sheet hosts the workbook's rate table, so a spec without one
      cannot render).
    """
    index = structure_rollup_index(structures)
    wanted: set | None = None
    if selection not in ("structures", "all"):
        wanted = {t.strip() for t in selection.split(",") if t.strip()}
        if not wanted:
            raise ValueError(f"--items {selection!r} selects nothing")
    picked = []
    seen_numbers: set = set()
    for entry in bid_frame:
        number = str(_frame_get(entry, "item_number"))
        sid = _owning_structure(entry, index)
        mob = is_mob_item(entry, mob_codes)
        if selection == "all":
            keep = True
        elif selection == "structures":
            keep = mob or sid is not None
        else:
            keep = mob or number in wanted
        if keep:
            picked.append((entry, sid))
            seen_numbers.add(number)
    if wanted is not None:
        missing = wanted - seen_numbers
        if missing:
            raise ValueError(
                f"--items selected item_numbers not in the bid frame: "
                f"{', '.join(sorted(missing))}")
    return picked


# ---------------------------------------------------------------------------
# item construction
# ---------------------------------------------------------------------------

def sheet_name(entry, structure_id, *, mob: bool, pack) -> str:
    """Excel sheet name (<=31 chars, no []:*?/\\): derived from the owning
    structure's id, the pack's rate-host prefix for the rate-host item,
    the pack's default prefix otherwise."""
    sc = pack.seed["scaffold"]
    number = str(_frame_get(entry, "item_number"))
    prefix = sc["rate_host_prefix"] if mob else (structure_id or sc["default_prefix"])
    name = _EXCEL_SHEET_BAD.sub("-", f"{prefix} {number}").strip()
    return name[:31]


def _skeleton_labor(pack) -> list:
    sc = pack.seed["scaffold"]
    block = {
        "slot": sc["first_slot"],
        "description": "(fill in)",
        "crew": copy.deepcopy((pack.seed or {}).get("default_crew", [])),
    }
    # A pack whose vocabulary requires a cost code on every labor block
    # (fieldbook) names the skeleton task's code; every other pack's
    # skeleton is unchanged.
    if sc.get("first_cost_code"):
        block["cost_code"] = sc["first_cost_code"]
    return [block]


def placeholder_takeoff(spec: dict | None) -> dict | None:
    """Zeroed takeoff block, shaped by the pack's
    ``seed.scaffold.placeholder_takeoff``, so the default item recipe
    validates and renders; Bridge 2 (apply-takeoff) replaces it with real
    per-element geometry. `None` when the pack declares no placeholder shape
    (its default item recipe carries its own takeoff)."""
    if not spec:
        return None
    line = {"label": PLACEHOLDER_GEOMETRY_LABEL, "length": 0, "height": 0}
    for f in spec.get("fields") or []:
        line[f] = 0
    return {"kind": spec["kind"], "lines": [line]}


def _build_item(entry, structure_id, scaffold_entry, mob: bool,
                generated_at: str | None, pack) -> dict:
    sc = pack.seed["scaffold"]
    number = str(_frame_get(entry, "item_number"))
    qty = _frame_get(entry, "estimated_quantity")
    item: dict = {
        "recipe": sc["rate_host_recipe"] if mob else sc["default_item_recipe"],
        "sheet": sheet_name(entry, structure_id, mob=mob, pack=pack),
        "item_no": number,
        "description": _frame_get(entry, "description") or "",
        "uom": _frame_get(entry, "unit") or "",
    }
    if qty is not None:
        item["qty"] = qty
        # The agency figure, stated in the workbook: measured quantities
        # arrive via apply-takeoff, never by editing this number blindly.
        item["notes"] = [
            f"qty {qty:g} is the OFFICIAL agency schedule quantity "
            "(measured takeoff arrives via est-estimate apply-takeoff)"]
    wbs = _frame_get(entry, "wbs")
    if wbs:
        item["wbs"] = str(wbs)
    code = _frame_get(entry, "item_code")
    if code:
        item["cost_code"] = str(code)
    if not mob:
        takeoff = placeholder_takeoff(sc.get("placeholder_takeoff"))
        if takeoff is not None:
            item["takeoff"] = takeoff

    source = "bid_frame"
    if scaffold_entry:
        source = scaffold_entry["source"]
        item["labor"] = [dict(b) for b in scaffold_entry.get("labor") or []] \
            or _skeleton_labor(pack)
        if scaffold_entry.get("cost_details"):
            item["cost_details"] = [dict(d) for d in scaffold_entry["cost_details"]]
    else:
        item["labor"] = _skeleton_labor(pack)

    meta = {
        "source": source,
        "schedule": _frame_get(entry, "schedule"),
        "official_qty": qty,
        "field_hashes": field_hashes(item),
    }
    if generated_at:
        meta["generated_at"] = generated_at
    item["scaffold_meta"] = meta
    return item


# ---------------------------------------------------------------------------
# spec construction
# ---------------------------------------------------------------------------

@dataclass
class ScaffoldResult:
    spec: dict
    selected: list = field(default_factory=list)      # item_no strings
    prefilled: list = field(default_factory=list)     # (item_no, source)
    injected_rate_host: bool = False


def scaffold_spec(manifest, structures: list | None = None, *,
                  items: str = "structures", scaffold_entries: dict | None = None,
                  mob_codes=(), generated_at: str | None = None,
                  pack=None) -> ScaffoldResult:
    """Build a schema-valid estimate config from a manifest's bid frame.

    `manifest` is an intake ProjectManifest (or any object/dict with name,
    bid_date and a bid_frame list). `structures` is structures.yaml's list.
    `scaffold_entries` maps item_code -> validated scaffold entry (already
    precedence-resolved: scaffolds.json over profile).
    """
    pack = pack or bundled_pack()
    bid_frame = _frame_get(manifest, "bid_frame") or []
    if not bid_frame:
        raise ValueError("manifest has no bid frame — run 'est-intake bid-frame' first")
    selected = select_items(bid_frame, structures or [], items, mob_codes)

    result = ScaffoldResult(spec={})
    entries_by_code = scaffold_entries or {}
    spec_items = []
    has_mob = False
    for entry, sid in selected:
        mob = is_mob_item(entry, mob_codes)
        has_mob = has_mob or mob
        code = _frame_get(entry, "item_code")
        scaffold_entry = entries_by_code.get(code) if code else None
        item = _build_item(entry, sid, scaffold_entry, mob, generated_at, pack)
        spec_items.append(item)
        result.selected.append(item["item_no"])
        if scaffold_entry:
            result.prefilled.append((item["item_no"], scaffold_entry["source"]))

    sc = pack.seed["scaffold"]
    if not has_mob:
        # The rate-host sheet hosts the master rate table every crew row
        # VLOOKUPs — without one the workbook cannot render. Inject a
        # rate-host sheet (NOT a bid item) and say so on its face.
        host = {
            "recipe": sc["rate_host_recipe"],
            "sheet": sc["rate_host_sheet"],
            "item_no": "RATES",
            "description": "Rate table host (no mobilization item selected)",
            "qty": 0,
            "uom": "LS",
            "notes": ["Scaffold-injected rate-table host — not a bid item; "
                      "re-scaffold with the mobilization item included."],
            "labor": _skeleton_labor(pack),
        }
        host["scaffold_meta"] = {"source": "scaffold:rate_host", "schedule": None,
                                 "official_qty": None,
                                 "field_hashes": field_hashes(host)}
        if generated_at:
            host["scaffold_meta"]["generated_at"] = generated_at
        spec_items.insert(0, host)
        result.injected_rate_host = True

    # rate-host items first: the reader meets the rate table where it lives.
    spec_items.sort(key=lambda it: 0 if it["recipe"] == sc["rate_host_recipe"] else 1)

    spec: dict = {"project": _frame_get(manifest, "name") or "Untitled"}
    bid_date = _frame_get(manifest, "bid_date")
    if bid_date:
        spec["bid_date"] = str(bid_date)
    # A pack whose vocabulary requires markup by cost type (markup_by_type:
    # required, e.g. fieldbook) names a valid empty-ish markup object
    # (seed.scaffold.default_markup) instead of the plain 0 every other
    # pack's skeleton keeps.
    spec["markup"] = copy.deepcopy(sc.get("default_markup", 0))
    spec["rate_table"] = [{"trade": t, "rate": 0}
                          for t in (pack.seed or {}).get("rate_table_trades", [])]
    spec["items"] = spec_items

    crews = _collect_crews(entries_by_code, spec_items) or copy.deepcopy(
        (pack.seed or {}).get("crews") or [])
    if crews:
        spec["crews"] = crews
    result.spec = spec
    return result


def _collect_crews(entries_by_code: dict, spec_items: list) -> list:
    """Splice scaffold-entry crews used by the selected items into the
    top-level crews table (dedupe by id, first wins)."""
    used_codes = {it.get("cost_code") for it in spec_items if it.get("cost_code")}
    crews: list = []
    seen: set = set()
    for code, entry in entries_by_code.items():
        if code not in used_codes:
            continue
        for crew in entry.get("crews") or []:
            if crew["id"] not in seen:
                crews.append(dict(crew))
                seen.add(crew["id"])
    return crews


# ---------------------------------------------------------------------------
# validation + merge
# ---------------------------------------------------------------------------

def validate_spec(spec: dict, *, pack=None) -> None:
    """Full-document jsonschema validation + build-time cross references.
    A scaffold that won't validate (or render) is a bug — call before writing."""
    import jsonschema

    root = (pack or bundled_pack()).schema
    try:
        jsonschema.validate(spec, root)
    except jsonschema.ValidationError as exc:
        path = "$" + "".join(f"[{p!r}]" for p in exc.absolute_path)
        raise ValueError(f"schema violation: {path}: {exc.message}") from exc
    from estimating_tools.estimate_spec.validate import validate_cross_references
    validate_cross_references(spec)


@dataclass
class MergeReport:
    updated: list = field(default_factory=list)   # (item_no, [fields])
    skipped: list = field(default_factory=list)   # (item_no, reason)
    added: list = field(default_factory=list)     # item_no
    kept: list = field(default_factory=list)      # item_no (existing, no fresh match)


def merge_scaffold(existing: dict, fresh: dict) -> tuple[dict, MergeReport]:
    """--merge semantics: update only scaffold-owned fields on items whose
    item_no matches AND whose field is still scaffold-owned (content hash
    matches scaffold_meta) — hand-edited fields, labor/pricing edits, and all
    top-level values (rate_table, markup, crews) are never touched. Items new
    in `fresh` are appended; existing items never deleted."""
    report = MergeReport()
    merged = dict(existing)
    merged_items = [dict(it) for it in existing.get("items", [])]
    by_no = {it.get("item_no"): it for it in merged_items}

    for fresh_item in fresh.get("items", []):
        item_no = fresh_item.get("item_no")
        cur = by_no.get(item_no)
        if cur is None:
            merged_items.append(fresh_item)
            report.added.append(item_no)
            continue
        meta = cur.get("scaffold_meta")
        if not isinstance(meta, dict):
            report.skipped.append((item_no, "no scaffold_meta (hand-authored)"))
            continue
        hashes = meta.get("field_hashes") or {}
        new_hashes = dict(hashes)
        changed = []
        for f in SCAFFOLD_OWNED_FIELDS:
            if f not in fresh_item:
                continue
            if f in hashes and content_hash(cur.get(f)) != hashes[f]:
                # hand-edited: leave the value AND its old hash, so
                # apply-takeoff keeps seeing this field as hand-edited.
                report.skipped.append((item_no, f"{f} hand-edited"))
                continue
            if cur.get(f) != fresh_item[f]:
                cur[f] = fresh_item[f]
                changed.append(f)
            new_hashes[f] = content_hash(cur[f])
        new_meta = dict(fresh_item.get("scaffold_meta") or meta)
        new_meta["field_hashes"] = new_hashes
        cur["scaffold_meta"] = new_meta
        if changed:
            report.updated.append((item_no, changed))
    fresh_nos = {it.get("item_no") for it in fresh.get("items", [])}
    report.kept = [n for n in by_no if n not in fresh_nos]
    merged["items"] = merged_items
    return merged, report
