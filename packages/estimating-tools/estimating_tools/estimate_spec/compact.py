"""Compact task-view render for the estimate spec (Phase 3b).

`render_compact(spec) -> str` emits a whole-spec markdown table with one row
per item — a task/WBS-style scan view using Phase 4.5's optional metadata
(wbs, cost_code, crew_id). Read-only; no parse side. Pure; no I/O.

Derivation rules and design rationale in
`docs/superpowers/specs/2026-07-09-editable-live-artifacts-phase3b-compact-task-view-design.md`.
"""
from __future__ import annotations

from estimating_tools.artifact_common import (
    escape_string_field,
    split_pipes,
    unescape_string_field,
)
from estimating_tools.artifacts import format_money, format_qty, md_table
from estimating_tools.estimate_spec._shared import _is_valid_id
from estimating_tools.estimate_spec.format_pack import bundled_pack
from estimating_tools.estimate_spec.scaffold import _skeleton_labor, placeholder_takeoff


_COLUMNS = (
    "id", "wbs", "cost_code", "category", "item_no", "task_name", "crew_id",
    "duration", "qty", "uom", "cost",
)


def render_compact(spec: dict) -> str:
    """Render the whole-spec compact task-view table. No trailing newline."""
    heading = f"## Task view — {escape_string_field(spec['project'])}"
    rate_table = spec.get("rate_table") or []
    rows = [_render_row(item, rate_table) for item in spec.get("items", [])]
    return heading + "\n\n" + md_table(list(_COLUMNS), rows)


def _render_row(item: dict, rate_table: list[dict]) -> list[str]:
    """Compute the 11-column row for one item. Column order matches `_COLUMNS`."""
    return [
        _id_cell(item.get("estimate_item_id")),
        _cell(item.get("wbs")),
        _cell(item.get("cost_code")),
        "-",                                                  # category — deferred
        escape_string_field(item["item_no"]),
        escape_string_field(item["description"]),
        _cell(item.get("crew_id")),
        _derive_duration(item.get("labor") or []),
        _format_num_or_formula(item.get("qty")),
        escape_string_field(item["uom"]),
        _derive_cost(item.get("labor") or [], rate_table),
    ]


def _cell(value) -> str:
    """Sentinel `-` for absent/None/empty; otherwise escape_string_field(str(value)).

    Escaping preserves newlines and backslashes across the markdown boundary so
    a description like "left\nright" or "1\\2" doesn't corrupt the surrounding
    table shape. md_table adds the pipe (`|` → `\\|`) escape on top.
    """
    if value is None or value == "":
        return "-"
    return escape_string_field(str(value))


def _id_cell(value) -> str:
    """Sentinel `-` for None/absent and for any value that isn't a valid id.

    id is system-owned (BM's EstimateItem.pk mirror) and expected to be either
    absent or a positive integer (schema: minimum 1). But this module's other
    cell helpers fall back to `-` on malformed pre-validation data rather than
    raise (see `_derive_duration`/`_derive_cost`), so we keep that invariant
    here too. Delegates to `_is_valid_id` so render and parse agree on what
    counts as a synced id.
    """
    if not _is_valid_id(value):
        return "-"
    return str(value)


def _format_num_or_formula(value) -> str:
    """Render a schema `numOrFormula` cell for the compact view.

    - None or absent → `-`
    - str starting with `=` → `~` (formula — resolved at build time, not here)
    - numeric → format_qty (trims trailing zeros: 240, 1.5)
    """
    if value is None:
        return "-"
    if isinstance(value, str):
        if value.startswith("="):
            return "~"
        # A non-formula string in a numOrFormula slot is a spec-authoring error;
        # let it surface loudly rather than silently rendering wrong.
        raise TypeError(
            f"expected number-or-formula, got string {value!r}"
        )
    return format_qty(value)


def _derive_duration(labor) -> str:
    """Sum (crew_row.days × crew_row.count) across all labor blocks.

    Returns '-' if no crew row supplied a numeric days value (empty labor, or
    only rows with missing/None days), '~' if any days value is a formula,
    otherwise format_qty(total). count defaults to 1 (matches units.yaml).

    Defensive: non-list `labor`, non-dict blocks, and non-list `crew` all map
    to '-' rather than raising. The compact renderer is a read-only scan
    surface that may be called on drafts before schema validation.
    """
    if not isinstance(labor, list):
        return "-"
    total = 0.0
    saw_any = False
    for block in labor:
        if not isinstance(block, dict):
            continue
        crew = block.get("crew")
        if not isinstance(crew, list):
            continue
        for row in crew:
            if not isinstance(row, dict):
                continue
            days = row.get("days")
            if isinstance(days, str) and days.startswith("="):
                return "~"
            if days is None:
                continue
            count = row.get("count", 1)
            total += float(days) * float(count)
            saw_any = True
    if not saw_any:
        return "-"
    return format_qty(total)


def _derive_cost(labor, rate_table) -> str:
    """Sum (rate × days × count) across labor blocks, where rate = rate_table[trade].

    Returns '-' if no crew row supplied a priceable value (no labor rows, all
    rows have missing days, or any crew row's trade is missing from rate_table),
    '~' if any days value is a formula, otherwise format_money(total).

    Defensive: non-list `labor`/`rate_table`, non-dict blocks, and non-list
    `crew` all map to '-' rather than raising.
    """
    if not isinstance(labor, list):
        return "-"
    if not isinstance(rate_table, list):
        rate_table = []
    rates = {}
    for row in rate_table:
        if isinstance(row, dict) and "trade" in row and "rate" in row:
            rates[row["trade"]] = row["rate"]
    total = 0.0
    saw_any = False
    for block in labor:
        if not isinstance(block, dict):
            continue
        crew = block.get("crew")
        if not isinstance(crew, list):
            continue
        for row in crew:
            if not isinstance(row, dict):
                continue
            days = row.get("days")
            if isinstance(days, str) and days.startswith("="):
                return "~"
            trade = row.get("trade")
            if trade not in rates:
                # No rate for this trade — cost can't be computed. Reachable in
                # practice: validate.py checks crews[].members[].trade (Phase 4.5),
                # not per-item labor[].crew[].trade, so a schema-valid spec can
                # still land a labor row whose trade isn't in rate_table.
                return "-"
            if days is None:
                continue
            count = row.get("count", 1)
            total += rates[trade] * float(days) * float(count)
            saw_any = True
    if not saw_any:
        return "-"
    return format_money(total)


# ---------- parse ----------


def parse_compact(text: str, *, base_spec: dict, pack=None) -> dict:
    """Parse a compact task-view artifact back into an estimate spec.

    `text` is the (possibly-edited) output of `render_compact(base_spec)`.
    `base_spec` supplies fields not in the compact table (labor, spreads,
    takeoff, cost_details, notes, recipe, sheet), so those round-trip
    unchanged for existing items. `pack` shapes a brand-new row's stub (see
    `_stub_new_item`); defaults to the bundled pack.

    Returns a NEW spec dict (does not mutate base_spec). See the Phase 3c
    design doc for row-identity, cell semantics, and CRUD rules.
    """
    _check_heading(text)
    rows = _parse_body_rows(text)
    items = _apply_rows_to_base(rows, base_spec, pack)
    # Preserve every top-level field from base_spec except `items`.
    result = {k: v for k, v in base_spec.items() if k != "items"}
    result["items"] = items
    return result


def _check_heading(text: str) -> None:
    """First non-blank line must be `## Task view — <anything>`."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("## Task view —"):
            raise ValueError(
                f"parse_compact: expected first heading `## Task view — …`, got {line!r}"
            )
        return
    raise ValueError("parse_compact: no `## Task view — …` heading found")


def _parse_body_rows(text: str) -> list[dict]:
    """Extract table body rows as `dict` keyed by column name.

    Skips the heading, the column-header row, and the separator row.
    Cells are unescaped via `unescape_string_field` after splitting on pipes.
    Returns an empty list if there are no body rows.

    Line handling uses `.strip()` (not just `.rstrip()`) so a body row with
    leading whitespace is still recognized — silently dropping such a row
    would be indistinguishable from an intentional delete once
    `_apply_rows_to_base` gains delete-via-omission semantics.
    """
    # Derive the header/separator lines from md_table itself so we don't
    # duplicate its formatting rules. Single source of truth.
    reference = md_table(list(_COLUMNS), []).splitlines()
    header_line = reference[0]
    separator_line = reference[1]
    body_rows: list[dict] = []
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln.startswith("|"):
            continue
        if ln == header_line or ln == separator_line:
            continue
        # Strip leading/trailing pipe, then split-with-pipe-escape:
        inner = ln
        if inner.startswith("|"):
            inner = inner[1:]
        if inner.endswith("|"):
            inner = inner[:-1]
        cells = [c.strip() for c in split_pipes(inner)]
        if len(cells) != len(_COLUMNS):
            raise ValueError(
                f"parse_compact: row {len(body_rows) + 1} has {len(cells)} cells, "
                f"expected {len(_COLUMNS)}"
            )
        # Unescape `\|` → `|` (md_table's pipe escape) and JSON-style backslash
        # escapes (from `escape_string_field`) via `unescape_string_field`.
        row = {}
        for col, cell in zip(_COLUMNS, cells):
            unescaped_pipe = cell.replace("\\|", "|")
            row[col] = unescape_string_field(unescaped_pipe)
        body_rows.append(row)
    return body_rows


def _apply_rows_to_base(rows: list[dict], base_spec: dict, pack=None) -> list[dict]:
    """Match each parsed row to a base item (by estimate_item_id primary, then
    item_no fallback), preserve unedited body fields, and return items in row
    order. Base items whose join keys don't appear in `rows` are dropped
    (delete via omission). New rows are handled by `_stub_new_item` (Task 6).

    Ambiguity is a hard error, not silent data loss:
      - Two rows claiming the same id → ValueError.
      - Two rows claiming the same item_no via fallback → ValueError.
      - Two base items sharing item_no without ids → ValueError at index build
        (fallback matching would silently drop one of them otherwise).
    """
    base_items = base_spec.get("items", [])
    by_id: dict[int, dict] = {}
    synced_item_nos: dict[str, int] = {}                      # item_no → its id
    for it in base_items:
        eid = it.get("estimate_item_id")
        # Only treat items with a schema-valid id as "synced." This keeps
        # render (_id_cell) and parse in agreement: if _id_cell renders `-`
        # for a malformed base value, we must not later insist that base
        # value was a synced anchor.
        if not _is_valid_id(eid):
            continue
        if eid in by_id:
            raise ValueError(
                f"parse_compact: base_spec has two items with "
                f"estimate_item_id {eid} — ambiguous id anchor"
            )
        by_id[eid] = it
        synced_item_nos[it["item_no"]] = eid
    # Only index un-synced items by item_no (synced items are matched by id).
    # Duplicate item_no among un-synced items is an ambiguity we cannot resolve.
    by_item_no: dict[str, dict] = {}
    for it in base_items:
        if _is_valid_id(it.get("estimate_item_id")):
            continue
        item_no = it["item_no"]
        if item_no in by_item_no:
            raise ValueError(
                f"parse_compact: base_spec has two un-synced items with "
                f"item_no {item_no!r} — cannot match by item_no fallback"
            )
        by_item_no[item_no] = it
    seen_ids: set[int] = set()
    seen_item_nos: set[str] = set()

    result: list[dict] = []
    for row_idx, row in enumerate(rows, start=1):
        row_id = _parse_id_cell(row["id"], row_idx)
        if row_id is not None:
            if row_id in seen_ids:
                raise ValueError(
                    f"parse_compact: row {row_idx}: duplicate id {row_id}"
                )
            seen_ids.add(row_id)
            base = by_id.get(row_id)
            if base is None:
                raise ValueError(
                    f"parse_compact: row {row_idx}: id {row_id} not in base_spec"
                )
        else:
            item_no = row["item_no"]
            if item_no in seen_item_nos:
                raise ValueError(
                    f"parse_compact: row {row_idx}: duplicate item_no "
                    f"{item_no!r} in fallback match"
                )
            seen_item_nos.add(item_no)
            # If item_no belongs to a synced base item, an id-cleared row is
            # almost certainly an agent mistake ("-" means "no change" for
            # every other column, but for id it means "no id"). Refusing this
            # loudly is much safer than silently creating a stub + deleting
            # the synced item's body content on the next round.
            if item_no in synced_item_nos:
                raise ValueError(
                    f"parse_compact: row {row_idx}: item_no {item_no!r} "
                    f"belongs to synced base item (estimate_item_id="
                    f"{synced_item_nos[item_no]}). If you meant to keep it, "
                    f"restore its id in the id cell. If you meant to add a "
                    f"new item, use a different item_no."
                )
            base = by_item_no.get(item_no)
            if base is None:
                # New item (add path) — Task 6 fleshes this out.
                result.append(_stub_new_item(row, row_idx, pack))
                continue
        # Existing item — shallow copy of the base, then apply cell edits.
        # Safe as a shallow copy because _apply_row_edits reassigns top-level
        # scalar keys and never mutates nested containers in place. Deep copy
        # would be needed if a future edit path modifies item["labor"] /
        # item["notes"] in place.
        result.append(_apply_row_edits(dict(base), row, row_idx))
    return result


def _apply_row_edits(item: dict, row: dict, row_idx: int) -> dict:
    """Apply per-cell parse rules to `item` (mutates + returns). Read-only
    cells (id, category, duration, cost) are ignored — they don't round-trip
    into item fields.
    """
    # Required string cells:
    for field in ("item_no", "task_name", "uom"):
        cell = row[field]
        target = "description" if field == "task_name" else field
        if cell == "-" or cell == "":
            raise ValueError(
                f"parse_compact: row {row_idx}: {field!r} is required (got {cell!r})"
            )
        item[target] = cell
    # Optional string cells — treat both the `-` sentinel and blank input as
    # "clear this field" so a user blanking the cell (rather than typing `-`)
    # doesn't leave a stray "" that renders back to `-` and hides the change.
    for field in ("wbs", "cost_code", "crew_id"):
        cell = row[field]
        if cell in ("-", ""):
            item.pop(field, None)
        else:
            item[field] = cell
    # qty — numOrFormula with `~` preservation:
    qty_cell = row["qty"]
    base_qty = item.get("qty")
    if qty_cell == "-":
        item.pop("qty", None)
    elif qty_cell == "~":
        # Preserve base's original qty (already in `item` from the base copy).
        pass
    elif qty_cell == _format_num_or_formula(base_qty):
        # No-op edit: the cell text matches what the base value would render
        # as. Leave the base value untouched — protects against `format_qty`'s
        # `:g` precision loss silently corrupting large or fractional numbers
        # on an unedited round-trip (e.g. base 123456.78 → render "123457" →
        # naive re-parse would drop the fraction and yield int 123457).
        pass
    else:
        item["qty"] = _parse_qty_cell(qty_cell, row_idx)
    return item


def _parse_qty_cell(cell: str, row_idx: int):
    """Parse a numeric-or-formula qty cell. `~` is handled by caller.

    Parses via `float()` first (handles scientific notation like "5e+06"),
    then narrows to `int` when the value is integral — so "240" → 240, "1.5"
    → 1.5, "1e5" → 100000, "5e+06" → 5000000 (all correctly typed).
    """
    if cell.startswith("="):
        return cell                                           # explicit formula string
    try:
        parsed = float(cell)
    except ValueError:
        raise ValueError(
            f"parse_compact: row {row_idx}: qty {cell!r} is not `-`, `~`, a number, or a formula"
        )
    if parsed.is_integer():
        return int(parsed)
    return parsed


def _parse_id_cell(cell: str, row_idx: int) -> int | None:
    """Return the integer id, or None for the `-` sentinel.

    Schema requires estimate_item_id >= 1; reject 0 and negatives so a
    malformed cell doesn't create a stub join key.
    """
    if cell == "-":
        return None
    try:
        value = int(cell)
    except ValueError:
        raise ValueError(
            f"parse_compact: row {row_idx}: id cell {cell!r} is not `-` or an integer"
        )
    if value < 1:
        raise ValueError(
            f"parse_compact: row {row_idx}: id {value} is not >= 1 "
            f"(schema requires estimate_item_id.minimum = 1)"
        )
    return value


def _recipe_needs_takeoff(pack, recipe: str) -> bool:
    """True when the pack's vocabulary requires `takeoff` for `recipe`, via
    the `if: {properties: {recipe: {const: ...}}} then: {required: [...]}`
    item_rules convention every format pack's vocabulary.yaml uses."""
    rules = (pack.vocabulary or {}).get("item_rules") or []
    for rule in rules:
        cond = ((rule.get("if") or {}).get("properties") or {}).get("recipe") or {}
        if cond.get("const") != recipe:
            continue
        if "takeoff" in ((rule.get("then") or {}).get("required") or []):
            return True
    return False


def _labor_required(pack) -> bool:
    """True when the pack's vocabulary requires every item to carry `labor`
    -- an unconditional item_rules entry (no `if:`) listing it in `required`,
    as fieldbook's "every item has at least one task" rule does."""
    rules = (pack.vocabulary or {}).get("item_rules") or []
    return any("if" not in rule and "labor" in (rule.get("required") or [])
               for rule in rules)


def _stub_new_item(row: dict, row_idx: int, pack=None) -> dict:
    """Produce a new item stub from a row with no id and no matching base.

    Defaults chosen so the stub is schema-valid without hand-supplied
    takeoff data: the pack's rate-host recipe (`seed.scaffold.
    rate_host_recipe`) when its schema requires no takeoff — the same
    reasoning that makes it a safe placeholder in scaffold.py — else the
    pack's default item recipe (`seed.scaffold.default_item_recipe`) plus a
    zeroed placeholder takeoff. Its `labor` is empty, unless the pack requires
    every item to carry a task (`_labor_required`): then it is scaffold's own
    skeleton task (`seed.scaffold.first_slot` / `first_cost_code`, the seed's
    `default_crew`), so the stub still validates. Either way the agent reshapes
    the item (recipe, takeoff, labor) via `render_item` after adding the row
    through compact.
    """
    pack = pack or bundled_pack()
    sc = pack.seed["scaffold"]
    item_no = row["item_no"]
    if item_no in ("-", ""):
        raise ValueError(
            f"parse_compact: row {row_idx}: new row has no item_no (got {item_no!r})"
        )
    task_name = row["task_name"]
    if task_name in ("-", ""):
        raise ValueError(
            f"parse_compact: row {row_idx}: new row for item_no {item_no!r}: "
            f"task_name is required"
        )
    uom = row["uom"]
    if uom in ("-", ""):
        raise ValueError(
            f"parse_compact: row {row_idx}: new row for item_no {item_no!r}: "
            f"uom is required"
        )
    if _recipe_needs_takeoff(pack, sc["rate_host_recipe"]):
        recipe = sc["default_item_recipe"]
        takeoff = placeholder_takeoff(sc.get("placeholder_takeoff"))
    else:
        recipe = sc["rate_host_recipe"]
        takeoff = None
    stub: dict = {
        "item_no":     item_no,
        "recipe":      recipe,
        "sheet":       item_no,
        "description": task_name,
        "uom":         uom,
        "labor":       _skeleton_labor(pack) if _labor_required(pack) else [],
    }
    if takeoff is not None:
        stub["takeoff"] = takeoff
    # qty: `-` → 1 (new items need a qty for schema validity), `~` → 1
    # (a fresh row shouldn't be a formula placeholder), else parse numeric.
    qty_cell = row["qty"]
    if qty_cell in ("-", "~"):
        stub["qty"] = 1
    else:
        stub["qty"] = _parse_qty_cell(qty_cell, row_idx)
    # Optional Phase 4.5 fields: include only when the cell has a real value.
    # Treat `-` and blank identically (matches the edit path in
    # _apply_row_edits) so an agent blanking a cell doesn't leave a stray "".
    for field in ("wbs", "cost_code", "crew_id"):
        cell = row[field]
        if cell not in ("-", ""):
            stub[field] = cell
    return stub
