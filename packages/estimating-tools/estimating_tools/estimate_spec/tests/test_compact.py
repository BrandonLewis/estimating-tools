"""Tests for the compact task-view render (Phase 3b).

`render_compact(spec) -> str` produces a whole-spec markdown table with one
row per item. Read-only, no parse side; column derivation is documented in
docs/superpowers/specs/2026-07-09-editable-live-artifacts-phase3b-compact-task-view-design.md
"""
from __future__ import annotations

import pytest

from estimating_tools.artifact_common import split_pipes
from estimating_tools.estimate_spec.compact import render_compact


@pytest.fixture(autouse=True)
def _bundled_pack_is_legacy_demo(monkeypatch):
    """compact's grammar is generic: a new row's stub (`pack or
    bundled_pack()`) is shaped by the legacy_demo fixture here unless a test
    names its own pack, so no test in this file depends on whichever pack
    format_pack.py bundles (fieldbook's stub is tested in
    test_fieldbook_compat.py)."""
    import estimating_tools.estimate_spec.compact as compact_mod
    from estimating_tools.estimate_spec.format_pack import ENGINE_DIR, load_pack

    legacy = load_pack(ENGINE_DIR / "tests" / "fixtures" / "packs" / "legacy_demo")
    monkeypatch.setattr(compact_mod, "bundled_pack", lambda: legacy)


_COLUMN_HEADER_LINE = (
    "| id | wbs | cost_code | category | item_no | task_name | crew_id "
    "| duration | qty | uom | cost |"
)
_SEPARATOR_LINE = (
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
)


def _data_rows(out: str) -> list[list[str]]:
    """Return the table body rows as lists of cell strings.

    Excludes the heading line, the column header row, and the separator row.
    Uses `split_pipes` (from `artifact_common`) so cells containing escaped
    pipes (`\\|` from `md_table`) are parsed as one cell, not two, then
    unescapes `\\|` back to `|` per cell — mirroring the split_pipes + pipe-
    unescape pattern in `assemblies/artifact.py`. This is a structural
    (pipe-delimiter) unescape only, not the JSON-style `escape_string_field`
    content escape, so cells like `"line1\\nline2"` stay as the escaped
    two-character sequence (assertions on those go through this helper too).
    """
    body_rows = []
    for ln in out.splitlines():
        if not ln.startswith("|"):
            continue
        if ln == _COLUMN_HEADER_LINE or ln == _SEPARATOR_LINE:
            continue
        stripped = ln.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        body_rows.append(
            [c.strip().replace("\\|", "|") for c in split_pipes(stripped)]
        )
    return body_rows


def _row_for(out: str, item_no: str) -> list[str]:
    """Return the parsed cells of the row whose item_no cell equals `item_no`.

    Item order is preserved by `_data_rows`; equality (not substring) match
    prevents `"Item # 1"` from matching `"Item # 14"`.
    """
    for row in _data_rows(out):
        if row[4] == item_no:                                 # column index 4 = item_no
            return row
    raise AssertionError(f"row for item_no {item_no!r} not found")


def _spec(items=None, project="Sample", rate_table=None):
    """Minimal well-formed spec. Callers supply items and (optionally) a rate_table."""
    return {
        "project": project,
        "markup": 100,
        "rate_table": rate_table or [{"trade": "FORE", "rate": 150}],
        "items": items or [],
    }


def test_empty_items_renders_header_and_empty_table():
    out = render_compact(_spec(items=[]))
    assert out == (
        f"## Task view — Sample\n\n"
        f"{_COLUMN_HEADER_LINE}\n"
        f"{_SEPARATOR_LINE}"
    )


def test_output_has_no_trailing_newline():
    out = render_compact(_spec(items=[]))
    assert not out.endswith("\n")


def test_project_name_in_heading():
    out = render_compact(_spec(items=[], project="Sunset Blvd Widening"))
    assert out.startswith("## Task view — Sunset Blvd Widening\n\n")


def test_project_name_with_newline_is_escaped():
    """Unconstrained spec['project'] must not be able to corrupt the markdown."""
    out = render_compact(_spec(items=[], project="Line 1\nLine 2"))
    # `escape_string_field` applies JSON-style backslash escape: `\n` -> literal `\` + `n`.
    assert "Line 1\\nLine 2" in out
    # Only one heading line in the output — no second `## ` from the raw newline.
    assert out.count("## Task view — ") == 1


# ---- Task 2: string columns ------------------------------------------------

def _mob_item(**overrides):
    """Minimal mob_item: only required fields + no labor."""
    base = {"item_no": "Item # 1", "recipe": "mob_item", "sheet": "MOB",
            "description": "Mobilization", "qty": 1, "uom": "LS", "labor": []}
    base.update(overrides)
    return base


def test_row_uses_item_no_and_description_and_uom():
    out = render_compact(_spec(items=[_mob_item()]))
    cells = _row_for(out, "Item # 1")
    # 11 columns in _COLUMNS order:
    # id, wbs, cost_code, category, item_no, task_name, crew_id, duration, qty, uom, cost
    assert cells[4] == "Item # 1"
    assert cells[5] == "Mobilization"
    assert cells[9] == "LS"


def test_optional_string_fields_default_to_dash():
    out = render_compact(_spec(items=[_mob_item()]))
    cells = _row_for(out, "Item # 1")
    assert cells[1] == "-"                                    # wbs
    assert cells[2] == "-"                                    # cost_code
    assert cells[3] == "-"                                    # category (always)
    assert cells[6] == "-"                                    # crew_id


def test_optional_string_fields_populate_when_set():
    item = _mob_item(wbs="1.2.3", cost_code="02-110", crew_id="crew_lab_2")
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[1] == "1.2.3"
    assert cells[2] == "02-110"
    assert cells[3] == "-"                                    # category still deferred
    assert cells[6] == "crew_lab_2"


def test_category_column_is_always_dash():
    """Deferred until profile-side cost-code resolution lands."""
    item = _mob_item(cost_code="02-110")
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[3] == "-"


def test_optional_string_empty_string_renders_dash():
    item = _mob_item(wbs="")
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[1] == "-"


def test_optional_string_none_renders_dash():
    item = _mob_item(wbs=None)
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[1] == "-"


def test_multiple_items_render_in_author_order():
    items = [_mob_item(item_no="Item # 1", description="Mob"),
             _mob_item(item_no="Item # 42", description="Concrete Outfall")]
    out = render_compact(_spec(items=items))
    rows = _data_rows(out)
    item_nos = [row[4] for row in rows]
    assert item_nos == ["Item # 1", "Item # 42"]


def test_pipe_in_description_is_escaped():
    item = _mob_item(description="left|right")
    out = render_compact(_spec(items=[item]))
    # md_table escapes `|` as `\|`; the escaped form should appear in the output.
    assert "left\\|right" in out


# ---- Task 3: qty column ----------------------------------------------------

def test_qty_integer_renders_without_decimal():
    out = render_compact(_spec(items=[_mob_item(qty=240)]))
    cells = _row_for(out, "Item # 1")
    assert cells[8] == "240"


def test_qty_float_trims_trailing_zeros():
    out = render_compact(_spec(items=[_mob_item(qty=1.5)]))
    cells = _row_for(out, "Item # 1")
    assert cells[8] == "1.5"


def test_qty_formula_renders_tilde_sentinel():
    """Formulas like '={ref:takeoff.ftg_cy}' cannot be resolved without a workbook
    context, so we surface 'computed at build time' via the ~ sentinel."""
    out = render_compact(_spec(items=[_mob_item(qty="={ref:takeoff.ftg_cy}")]))
    cells = _row_for(out, "Item # 1")
    assert cells[8] == "~"


def test_qty_absent_renders_dash():
    item = _mob_item()
    del item["qty"]
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[8] == "-"


def test_qty_none_renders_dash():
    item = _mob_item(qty=None)
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[8] == "-"


def test_qty_non_formula_string_raises_type_error():
    """A non-formula string in the qty slot is a spec-authoring error; the compact
    renderer surfaces it loudly rather than silently rendering wrong."""
    with pytest.raises(TypeError, match="expected number-or-formula"):
        render_compact(_spec(items=[_mob_item(qty="oops")]))


# ---- Task 4: duration column -----------------------------------------------

def _std_item(**overrides):
    """Minimal standard_item shaped to accept labor blocks."""
    base = {"item_no": "Item # 42", "recipe": "standard_item", "sheet": "S42",
            "description": "Concrete Outfall", "qty": 240, "uom": "CY",
            "takeoff": {"kind": "geometry", "lines": [
                {"label": "L1", "length": 10.0, "ftg_cy": 1.0, "ftg_cf": 27.0,
                 "wall_cy": 1.0, "wall_cf": 27.0}]},
            "labor": []}
    base.update(overrides)
    return base


def test_duration_no_labor_blocks_renders_dash():
    out = render_compact(_spec(items=[_std_item(labor=[])]))
    cells = _row_for(out, "Item # 42")
    assert cells[7] == "-"


def test_duration_single_labor_block_sums_days_times_count():
    """One block, one crew row: FORE for 2 days × 1 count = 2."""
    item = _std_item(labor=[{
        "slot": "A", "description": "Placement",
        "crew": [{"trade": "FORE", "count": 1, "days": 2}],
    }])
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 42")
    assert cells[7] == "2"


def test_duration_multi_row_block_sums():
    """One block, three crew rows: 2×1 + 2×1 + 2×1 = 6."""
    item = _std_item(labor=[{
        "slot": "A", "description": "Placement",
        "crew": [
            {"trade": "FORE", "count": 1, "days": 2},
            {"trade": "OPER", "count": 1, "days": 2},
            {"trade": "LAB",  "count": 1, "days": 2},
        ],
    }])
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 42")
    assert cells[7] == "6"


def test_duration_multi_block_sums_across_blocks():
    """Two blocks each with one row: 2 + 3 = 5."""
    item = _std_item(labor=[
        {"slot": "A", "description": "Prep", "crew": [{"trade": "FORE", "count": 1, "days": 2}]},
        {"slot": "B", "description": "Placement", "crew": [{"trade": "FORE", "count": 1, "days": 3}]},
    ])
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 42")
    assert cells[7] == "5"


def test_duration_count_defaults_to_1_when_absent():
    """Schema allows count omitted; units.yaml default is 1."""
    item = _std_item(labor=[{
        "slot": "A", "description": "Prep",
        "crew": [{"trade": "FORE", "days": 4}],                # no count
    }])
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 42")
    assert cells[7] == "4"


def test_duration_count_zero_contributes_zero():
    item = _std_item(labor=[{
        "slot": "A", "description": "Prep",
        "crew": [{"trade": "FORE", "count": 0, "days": 4}],
    }])
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 42")
    assert cells[7] == "0"


def test_duration_days_formula_renders_tilde():
    item = _std_item(labor=[{
        "slot": "A", "description": "Prep",
        "crew": [{"trade": "FORE", "count": 1, "days": "={p.driver}"}],
    }])
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 42")
    assert cells[7] == "~"


def test_duration_float_trims_trailing_zeros():
    item = _std_item(labor=[{
        "slot": "A", "description": "Prep",
        "crew": [{"trade": "FORE", "count": 1, "days": 1.5}],
    }])
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 42")
    assert cells[7] == "1.5"


# ---- Task 5: cost column ---------------------------------------------------

def test_cost_no_labor_renders_dash():
    out = render_compact(_spec(items=[_std_item(labor=[])]))
    cells = _row_for(out, "Item # 42")
    assert cells[10] == "-"


def test_cost_single_row_uses_rate_table_lookup():
    """FORE at $150/day × 2 days × 1 count = $300."""
    item = _std_item(labor=[{
        "slot": "A", "description": "Prep",
        "crew": [{"trade": "FORE", "count": 1, "days": 2}],
    }])
    out = render_compact(_spec(
        items=[item],
        rate_table=[{"trade": "FORE", "rate": 150}],
    ))
    cells = _row_for(out, "Item # 42")
    assert cells[10] == "300.00"


def test_cost_sums_across_crew_rows():
    """FORE 150 × 2 × 1  +  LAB 95 × 2 × 2  =  300 + 380 = 680."""
    item = _std_item(labor=[{
        "slot": "A", "description": "Placement",
        "crew": [
            {"trade": "FORE", "count": 1, "days": 2},
            {"trade": "LAB",  "count": 2, "days": 2},
        ],
    }])
    out = render_compact(_spec(
        items=[item],
        rate_table=[{"trade": "FORE", "rate": 150},
                    {"trade": "LAB",  "rate": 95}],
    ))
    cells = _row_for(out, "Item # 42")
    assert cells[10] == "680.00"


def test_cost_sums_across_labor_blocks():
    """Two blocks: FORE 150×2 + FORE 150×3 = 300 + 450 = 750."""
    item = _std_item(labor=[
        {"slot": "A", "description": "Prep",
         "crew": [{"trade": "FORE", "count": 1, "days": 2}]},
        {"slot": "B", "description": "Placement",
         "crew": [{"trade": "FORE", "count": 1, "days": 3}]},
    ])
    out = render_compact(_spec(
        items=[item],
        rate_table=[{"trade": "FORE", "rate": 150}],
    ))
    cells = _row_for(out, "Item # 42")
    assert cells[10] == "750.00"


def test_cost_days_formula_renders_tilde():
    item = _std_item(labor=[{
        "slot": "A", "description": "Prep",
        "crew": [{"trade": "FORE", "count": 1, "days": "={p.driver}"}],
    }])
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 42")
    assert cells[10] == "~"


def test_cost_unknown_trade_renders_dash():
    """A labor row referencing a trade absent from rate_table can't be priced.
    Cost renders `-` (validate.py doesn't cover this path — it checks the
    top-level crews[] table, not per-item labor[].crew[] rows)."""
    item = _std_item(labor=[{
        "slot": "A", "description": "Prep",
        "crew": [{"trade": "PLUMB", "count": 1, "days": 2}],
    }])
    out = render_compact(_spec(
        items=[item],
        rate_table=[{"trade": "FORE", "rate": 150}],          # PLUMB not present
    ))
    cells = _row_for(out, "Item # 42")
    assert cells[10] == "-"


def test_cost_count_defaults_to_1():
    """FORE 150 × 4 days × (count omitted → 1) = 600."""
    item = _std_item(labor=[{
        "slot": "A", "description": "Prep",
        "crew": [{"trade": "FORE", "days": 4}],
    }])
    out = render_compact(_spec(
        items=[item],
        rate_table=[{"trade": "FORE", "rate": 150}],
    ))
    cells = _row_for(out, "Item # 42")
    assert cells[10] == "600.00"


def test_cost_missing_rate_table_renders_dash():
    """A spec without rate_table can't price any labor; cost falls back to `-`.
    Exercises the `rate_table = spec.get("rate_table") or []` branch in render_compact."""
    item = _std_item(labor=[{
        "slot": "A", "description": "Prep",
        "crew": [{"trade": "FORE", "count": 1, "days": 2}],
    }])
    # Construct spec without a rate_table entry:
    spec = {"project": "Sample", "markup": 100, "items": [item]}
    out = render_compact(spec)
    cells = _row_for(out, "Item # 42")
    assert cells[10] == "-"


def test_cost_duplicate_trade_in_rate_table_last_wins():
    """Duplicate trade in rate_table: dict comprehension takes insertion order,
    so the last entry wins. Lock in this deterministic behavior."""
    item = _std_item(labor=[{
        "slot": "A", "description": "Prep",
        "crew": [{"trade": "FORE", "count": 1, "days": 1}],
    }])
    out = render_compact(_spec(
        items=[item],
        rate_table=[{"trade": "FORE", "rate": 100},
                    {"trade": "FORE", "rate": 200}],           # duplicate — last wins
    ))
    cells = _row_for(out, "Item # 42")
    assert cells[10] == "200.00"


# ---- Task 6: end-to-end fixture --------------------------------------------

from pathlib import Path

ALT_DIR = Path(__file__).resolve().parent / "fixtures" / "packs" / "alt"
ALT_SAMPLE = ALT_DIR / "examples" / "sample.estimate.yaml"


@pytest.fixture(scope="module")
def alt_pack():
    from estimating_tools.estimate_spec.format_pack import load_pack
    return load_pack(ALT_DIR)


def test_render_compact_on_the_alt_pack_fixture():
    """Sanity: the alt pack's own example renders without raising and
    contains all three items."""
    import yaml

    spec = yaml.safe_load(ALT_SAMPLE.read_text(encoding="utf-8"))
    out = render_compact(spec)

    assert out.startswith("## Task view — Alt Pack Duct Package\n\n")
    # All three items present via _data_rows helper (parses cells; item_no is index 4):
    rows = _data_rows(out)
    assert [row[4] for row in rows] == ["Item 1", "Item 2", "Item 3"]
    # No trailing newline (md_table contract):
    assert not out.endswith("\n")


# ---- Phase 3c: id column render ---------------------------------------------

def test_id_column_renders_integer_when_estimate_item_id_present():
    """A synced item with estimate_item_id renders it as the plain integer."""
    item = _mob_item(estimate_item_id=12345)
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[0] == "12345"


def test_id_column_renders_dash_when_estimate_item_id_absent():
    """A draft item (no BM id yet) renders `-` in the id column."""
    item = _mob_item()                                        # no estimate_item_id
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[0] == "-"


def test_id_column_renders_dash_when_estimate_item_id_is_none():
    item = _mob_item(estimate_item_id=None)
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[0] == "-"


def test_id_column_renders_dash_when_estimate_item_id_is_bool():
    """A bool sneaking in (bool is int-subclass) should degrade to `-`,
    not silently render as '1'/'0'."""
    item = _mob_item(estimate_item_id=True)
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[0] == "-"


def test_id_column_renders_dash_when_estimate_item_id_is_float():
    """A float in the id slot is malformed pre-validation data — degrade to `-`."""
    item = _mob_item(estimate_item_id=1.5)
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[0] == "-"


def test_id_column_renders_dash_when_estimate_item_id_is_string():
    """A string in the id slot is malformed pre-validation data — degrade to `-`."""
    item = _mob_item(estimate_item_id="12345")
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[0] == "-"


# ---- Post-review fixes: cell escaping, saw_any semantics, split_pipes helper ---

def test_description_with_newline_is_escape_encoded():
    """A description containing '\\n' should JSON-escape into the cell — no bare newline
    that could split the row into two lines and corrupt the table."""
    item = _mob_item(description="line1\nline2")
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[5] == "line1\\nline2"
    # And the total row count is still exactly 1 body row + 1 header + 1 separator
    assert len(_data_rows(out)) == 1


def test_duration_all_missing_days_renders_dash():
    """A draft-shape spec where every crew row is missing `days` renders `-`, not `0`."""
    item = _std_item(labor=[{
        "slot": "A", "description": "Prep",
        "crew": [{"trade": "FORE", "count": 1}],              # no days
    }])
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 42")
    assert cells[7] == "-"


def test_cost_all_missing_days_renders_dash():
    """A draft-shape spec where every crew row is missing `days` renders cost `-`, not `0.00`."""
    item = _std_item(labor=[{
        "slot": "A", "description": "Prep",
        "crew": [{"trade": "FORE", "count": 1}],              # no days
    }])
    out = render_compact(_spec(
        items=[item],
        rate_table=[{"trade": "FORE", "rate": 150}],
    ))
    cells = _row_for(out, "Item # 42")
    assert cells[10] == "-"


def test_duration_non_list_labor_returns_dash():
    """Type-defensive: malformed labor shape doesn't raise."""
    item = _std_item()
    item["labor"] = "oops"                                    # not a list
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 42")
    assert cells[7] == "-"


def test_data_rows_parses_escaped_pipe_as_one_cell():
    """`_data_rows` must respect md_table's `\\|` escape so cells with pipes
    don't fake-split into extra columns."""
    item = _mob_item(description="left|right")
    out = render_compact(_spec(items=[item]))
    rows = _data_rows(out)
    assert len(rows) == 1
    # 11-column row, description at index 5:
    assert len(rows[0]) == 11
    # After split_pipes + unescape, we should see the original single cell content:
    assert rows[0][5] == "left|right"


# ---- Phase 3c: parse_compact scaffolding -----------------------------------

from estimating_tools.estimate_spec.compact import parse_compact


def test_parse_compact_empty_items_round_trips_to_empty_items():
    spec = _spec(items=[])
    text = render_compact(spec)
    parsed = parse_compact(text, base_spec=spec)
    assert parsed["items"] == []


def test_parse_compact_preserves_top_level_project_from_base_spec():
    """The heading uses spec['project']; parser drops that field from output
    and pulls it from base_spec instead (base_spec is the source of truth)."""
    spec = _spec(items=[], project="Sample")
    text = render_compact(spec)
    parsed = parse_compact(text, base_spec=spec)
    assert parsed["project"] == "Sample"


def test_parse_compact_preserves_top_level_rate_table_and_markup():
    spec = _spec(items=[])
    text = render_compact(spec)
    parsed = parse_compact(text, base_spec=spec)
    assert parsed["rate_table"] == spec["rate_table"]
    assert parsed["markup"] == spec["markup"]


def test_parse_compact_missing_base_spec_raises_type_error():
    text = render_compact(_spec(items=[]))
    with pytest.raises(TypeError):
        parse_compact(text)                                   # missing keyword-only kwarg


def test_parse_compact_malformed_heading_raises():
    """A non-heading first line (or missing heading) is a hard parse error."""
    text = "not a heading\n\n| id | wbs | ...|"
    with pytest.raises(ValueError, match="heading"):
        parse_compact(text, base_spec=_spec(items=[]))


def test_parse_compact_body_row_with_leading_whitespace_is_parsed():
    """A body row prefixed with whitespace must be recognized (regression
    guard: silent drop would be indistinguishable from intentional delete
    once Task 4's delete-via-omission lands)."""
    text = render_compact(_spec(items=[]))
    # Manually construct a well-formed but whitespace-indented body row.
    # It won't match a base item so _apply_rows_to_base (still a stub) will
    # discard it — but the important thing here is that _parse_body_rows does
    # NOT silently drop it upstream. To observe that, we bypass parse_compact
    # and call _parse_body_rows directly.
    from estimating_tools.estimate_spec.compact import _parse_body_rows
    indented_row = "  | 1 | - | - | - | Item # 1 | Mob | - | - | 1 | LS | - |"
    text_with_row = text + "\n" + indented_row
    rows = _parse_body_rows(text_with_row)
    assert len(rows) == 1                                     # row was seen, not dropped
    assert rows[0]["item_no"] == "Item # 1"


def test_parse_compact_header_derived_from_md_table():
    """Regression guard: the header/separator recognition strings come from
    md_table, so a change to md_table's formatting propagates automatically."""
    from estimating_tools.estimate_spec.compact import _parse_body_rows
    # A well-formed empty compact render should yield zero body rows —
    # both the header and separator lines are recognized and skipped.
    text = render_compact(_spec(items=[]))
    rows = _parse_body_rows(text)
    assert rows == []


# ---- Phase 3c: parse join, delete, reorder ---------------------------------

def _synced_item(estimate_item_id: int, **overrides):
    """Minimal mob_item with a BM id set."""
    return _mob_item(estimate_item_id=estimate_item_id, **overrides)


def test_parse_compact_round_trip_single_synced_item():
    """A single item with an id round-trips byte-identical."""
    spec = _spec(items=[_synced_item(estimate_item_id=100, item_no="Item # 1")])
    text = render_compact(spec)
    parsed = parse_compact(text, base_spec=spec)
    assert parsed["items"] == spec["items"]


def test_parse_compact_round_trip_multi_synced_items():
    spec = _spec(items=[
        _synced_item(estimate_item_id=100, item_no="Item # 1"),
        _synced_item(estimate_item_id=200, item_no="Item # 2"),
        _synced_item(estimate_item_id=300, item_no="Item # 3"),
    ])
    text = render_compact(spec)
    parsed = parse_compact(text, base_spec=spec)
    assert parsed["items"] == spec["items"]


def test_parse_compact_round_trip_fallback_matches_by_item_no():
    """An item without estimate_item_id (draft) is matched by item_no."""
    spec = _spec(items=[_mob_item(item_no="Item # 1")])         # no id
    text = render_compact(spec)
    parsed = parse_compact(text, base_spec=spec)
    assert parsed["items"] == spec["items"]


def test_parse_compact_preserves_full_item_body_on_round_trip():
    """Fields not in the compact table (labor, spreads, takeoff, notes) come
    from base_spec unchanged. This is the whole point of the base_spec param."""
    item = _synced_item(estimate_item_id=42, item_no="Item # 42")
    item["notes"] = ["scope note 1", "scope note 2"]
    spec = _spec(items=[item])
    text = render_compact(spec)
    parsed = parse_compact(text, base_spec=spec)
    assert parsed["items"][0]["notes"] == ["scope note 1", "scope note 2"]


def test_parse_compact_delete_via_omission_by_id():
    """A synced item whose row is omitted from the edited text is deleted."""
    spec = _spec(items=[
        _synced_item(estimate_item_id=100, item_no="Item # 1"),
        _synced_item(estimate_item_id=200, item_no="Item # 2"),
    ])
    text = render_compact(spec)
    # Remove the row for Item # 2 from the text:
    edited = "\n".join(ln for ln in text.splitlines() if "Item # 2" not in ln)
    parsed = parse_compact(edited, base_spec=spec)
    assert [it["item_no"] for it in parsed["items"]] == ["Item # 1"]


def test_parse_compact_delete_via_omission_by_item_no_fallback():
    """A draft (no id) can also be deleted by omission — matcher falls back
    to item_no."""
    spec = _spec(items=[
        _mob_item(item_no="Item # 1"),                        # no id
        _mob_item(item_no="Item # 2"),                        # no id
    ])
    text = render_compact(spec)
    edited = "\n".join(ln for ln in text.splitlines() if "Item # 2" not in ln)
    parsed = parse_compact(edited, base_spec=spec)
    assert [it["item_no"] for it in parsed["items"]] == ["Item # 1"]


def test_parse_compact_reorder_rows_reorders_spec_items():
    """Output row order determines new spec['items'] order."""
    spec = _spec(items=[
        _synced_item(estimate_item_id=100, item_no="Item # 1"),
        _synced_item(estimate_item_id=200, item_no="Item # 2"),
        _synced_item(estimate_item_id=300, item_no="Item # 3"),
    ])
    text = render_compact(spec)
    lines = text.splitlines()
    # Swap the last two body rows manually. Find their indexes:
    row_2_idx = next(i for i, ln in enumerate(lines) if "Item # 2" in ln)
    row_3_idx = next(i for i, ln in enumerate(lines) if "Item # 3" in ln)
    lines[row_2_idx], lines[row_3_idx] = lines[row_3_idx], lines[row_2_idx]
    edited = "\n".join(lines)
    parsed = parse_compact(edited, base_spec=spec)
    assert [it["item_no"] for it in parsed["items"]] == [
        "Item # 1", "Item # 3", "Item # 2",
    ]


def test_parse_compact_unknown_id_in_row_raises_locator_error():
    """A numeric id in the parsed text that doesn't exist in base_spec is a
    hard error — the agent shouldn't invent ids."""
    spec = _spec(items=[_synced_item(estimate_item_id=100, item_no="Item # 1")])
    text = render_compact(spec)
    # Replace the id 100 with 999 (not in base):
    edited = text.replace("| 100 |", "| 999 |")
    with pytest.raises(ValueError, match=r"999.*not in base"):
        parse_compact(edited, base_spec=spec)


def test_parse_compact_duplicate_id_across_rows_raises():
    """Two rows can't claim the same id."""
    spec = _spec(items=[
        _synced_item(estimate_item_id=100, item_no="Item # 1"),
        _synced_item(estimate_item_id=200, item_no="Item # 2"),
    ])
    text = render_compact(spec)
    # Force a duplicate: replace 200's id cell with 100:
    edited = text.replace("| 200 |", "| 100 |")
    with pytest.raises(ValueError, match=r"duplicate id 100"):
        parse_compact(edited, base_spec=spec)


def test_parse_compact_base_spec_with_duplicate_item_no_unsynced_raises():
    """Two un-synced base items sharing item_no is a hard error — the fallback
    matching would silently drop one otherwise."""
    spec = _spec(items=[
        _mob_item(item_no="Item # 1", description="Task A"),
        _mob_item(item_no="Item # 1", description="Task B"),
    ])
    text = render_compact(spec)
    with pytest.raises(ValueError, match=r"un-synced.*Item # 1"):
        parse_compact(text, base_spec=spec)


def test_parse_compact_base_spec_with_duplicate_item_no_but_ids_ok():
    """Duplicate item_no is OK when both items have distinct ids — they're
    disambiguated by the id path."""
    spec = _spec(items=[
        _synced_item(estimate_item_id=100, item_no="Item # 1", description="Task A"),
        _synced_item(estimate_item_id=200, item_no="Item # 1", description="Task B"),
    ])
    text = render_compact(spec)
    parsed = parse_compact(text, base_spec=spec)
    assert len(parsed["items"]) == 2
    assert parsed["items"][0]["description"] == "Task A"
    assert parsed["items"][1]["description"] == "Task B"


def test_parse_compact_duplicate_item_no_across_rows_fallback_raises():
    """Two rows via item_no fallback claiming the same item_no is an error."""
    spec = _spec(items=[_mob_item(item_no="Item # 1")])
    text = render_compact(spec)
    # Duplicate the row by appending it a second time:
    body_row = next(ln for ln in text.splitlines() if "Item # 1" in ln)
    edited = text + "\n" + body_row
    with pytest.raises(ValueError, match=r"duplicate item_no.*Item # 1"):
        parse_compact(edited, base_spec=spec)


def test_parse_compact_malformed_id_cell_raises_with_row_locator():
    """Non-integer, non-`-` id cell surfaces with a row locator."""
    spec = _spec(items=[_synced_item(estimate_item_id=100, item_no="Item # 1")])
    text = render_compact(spec)
    # Corrupt the id cell (100 → abc):
    edited = text.replace("| 100 |", "| abc |")
    with pytest.raises(ValueError, match=r"row 1.*id cell 'abc'"):
        parse_compact(edited, base_spec=spec)


# ---- Phase 3c: cell edit semantics -----------------------------------------

def test_parse_compact_edits_wbs_on_existing_row():
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1")])
    text = render_compact(spec)
    # The wbs cell for Item # 1 is column 1. Replace `-` with `1.2.3`:
    edited = text.replace("| 1 | - |", "| 1 | 1.2.3 |")
    parsed = parse_compact(edited, base_spec=spec)
    assert parsed["items"][0]["wbs"] == "1.2.3"


def test_parse_compact_edits_cost_code_on_existing_row():
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1")])
    text = render_compact(spec)
    # Insert cost_code into column 2. The compact for a minimal synced item
    # renders `| 1 | - | - | - | Item # 1 | ...`. Change cost_code (index 2)
    # from `-` to `02-110` by manipulating the specific cells:
    edited = text.replace("| 1 | - | - | -", "| 1 | - | 02-110 | -")
    parsed = parse_compact(edited, base_spec=spec)
    assert parsed["items"][0]["cost_code"] == "02-110"


def test_parse_compact_dash_on_optional_string_drops_key():
    """Editing wbs from '1.2.3' back to '-' removes the key from the item dict."""
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1",
                                     wbs="1.2.3")])
    text = render_compact(spec)
    edited = text.replace("| 1 | 1.2.3 |", "| 1 | - |")
    parsed = parse_compact(edited, base_spec=spec)
    assert "wbs" not in parsed["items"][0]


def test_parse_compact_edits_task_name_updates_description():
    """task_name column parses back into item['description']."""
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1",
                                     description="Mobilization")])
    text = render_compact(spec)
    edited = text.replace("Mobilization", "Mobilization (revised)")
    parsed = parse_compact(edited, base_spec=spec)
    assert parsed["items"][0]["description"] == "Mobilization (revised)"


def test_parse_compact_edits_qty_numeric():
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1",
                                     qty=1)])
    text = render_compact(spec)
    # qty column is index 8 in the 11-column layout.
    # Replace `| 1 | LS |` (qty=1 followed by uom=LS) with `| 240 | LS |`:
    edited = text.replace("| 1 | LS |", "| 240 | LS |")
    parsed = parse_compact(edited, base_spec=spec)
    assert parsed["items"][0]["qty"] == 240


def test_parse_compact_qty_tilde_preserves_base_formula():
    """A `~` in qty means 'unchanged' — preserve the base's original value,
    even if that value is a formula string."""
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1",
                                     qty="={ref:takeoff.ftg_cy}")])
    text = render_compact(spec)
    # Renderer emits `~` for a formula; parser should preserve base value.
    parsed = parse_compact(text, base_spec=spec)
    assert parsed["items"][0]["qty"] == "={ref:takeoff.ftg_cy}"


def test_parse_compact_edits_uom():
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1",
                                     uom="LS")])
    text = render_compact(spec)
    edited = text.replace("| LS |", "| EA |")
    parsed = parse_compact(edited, base_spec=spec)
    assert parsed["items"][0]["uom"] == "EA"


def test_parse_compact_edits_crew_id():
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1")])
    text = render_compact(spec)
    # crew_id is index 6, sits between task_name and duration. Row starts
    # `| 1 | - | - | - | Item # 1 | Mobilization | - | - | 1 | LS | - |`.
    # Change the fifth `-` (crew_id) to `crew_lab_2`.
    edited = text.replace(
        "| Item # 1 | Mobilization | - |",
        "| Item # 1 | Mobilization | crew_lab_2 |",
    )
    parsed = parse_compact(edited, base_spec=spec)
    assert parsed["items"][0]["crew_id"] == "crew_lab_2"


def test_parse_compact_rename_item_no_with_id_preserves_body():
    """Renaming item_no is safe when id is present — labor/notes round-trip."""
    item = _synced_item(estimate_item_id=1, item_no="Item # 1")
    item["notes"] = ["important scope note"]
    spec = _spec(items=[item])
    text = render_compact(spec)
    edited = text.replace("Item # 1", "Item # 1A")
    parsed = parse_compact(edited, base_spec=spec)
    assert parsed["items"][0]["item_no"] == "Item # 1A"
    assert parsed["items"][0]["notes"] == ["important scope note"]


def test_parse_compact_blank_item_no_raises_locator_error():
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1")])
    text = render_compact(spec)
    # Blank the item_no cell (column 4):
    edited = text.replace("| Item # 1 |", "| - |")
    with pytest.raises(ValueError, match=r"row 1.*item_no.*required"):
        parse_compact(edited, base_spec=spec)


def test_parse_compact_blank_task_name_raises_locator_error():
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1",
                                     description="Mobilization")])
    text = render_compact(spec)
    edited = text.replace("| Mobilization |", "| - |")
    with pytest.raises(ValueError, match=r"row 1.*task_name.*required"):
        parse_compact(edited, base_spec=spec)


def test_parse_compact_blank_uom_raises_locator_error():
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1",
                                     uom="LS")])
    text = render_compact(spec)
    edited = text.replace("| LS |", "| - |")
    with pytest.raises(ValueError, match=r"row 1.*uom.*required"):
        parse_compact(edited, base_spec=spec)


def test_parse_compact_non_numeric_qty_raises_locator_error():
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1",
                                     qty=1)])
    text = render_compact(spec)
    edited = text.replace("| 1 | LS |", "| oops | LS |")
    with pytest.raises(ValueError, match=r"row 1.*qty.*'oops'"):
        parse_compact(edited, base_spec=spec)


def test_parse_compact_qty_precision_preserved_on_untouched_round_trip():
    """A large-precision qty that `format_qty`'s `:g` rounds off must NOT be
    silently truncated on an unedited round-trip. Detected by comparing the
    cell text to the base value's rendered form."""
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1",
                                     qty=123456.78)])
    text = render_compact(spec)
    parsed = parse_compact(text, base_spec=spec)
    assert parsed["items"][0]["qty"] == 123456.78


def test_parse_compact_qty_scientific_notation_parses_as_integer_when_integral():
    """`5000000` renders via format_qty as `5e+06`. If an agent later types
    that back verbatim, the parser should coerce it to a plain integer."""
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1",
                                     qty=1)])
    text = render_compact(spec)
    # Replace the qty cell with scientific notation:
    edited = text.replace("| 1 | LS |", "| 5e+06 | LS |")
    parsed = parse_compact(edited, base_spec=spec)
    assert parsed["items"][0]["qty"] == 5000000


def test_parse_compact_blank_optional_cell_drops_key_same_as_dash():
    """A user blanking (not typing `-`) an optional cell should behave the
    same as the `-` sentinel — the key gets dropped from the item dict."""
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1",
                                     wbs="1.2.3")])
    text = render_compact(spec)
    # Replace the wbs cell with a blank (a single space between pipes):
    edited = text.replace("| 1 | 1.2.3 |", "| 1 |  |")
    parsed = parse_compact(edited, base_spec=spec)
    assert "wbs" not in parsed["items"][0]


# ---- Phase 3c: add semantics (new-row stub) --------------------------------

def test_parse_compact_new_row_creates_stub_with_defaults(demo_pack):
    """A row with id=- and item_no not in base_spec creates a new item stub.

    `pack=demo_pack` is explicit — the stub's default recipe/sheet come from
    whichever pack is passed (`seed.scaffold.rate_host_recipe`), never a
    hardcoded literal; see test_compact_stub_uses_pack_default_recipe for
    the property proven generically across two packs."""
    spec = _spec(items=[])
    text = render_compact(spec)
    # Manually construct a new row and inject it before the trailing newlines:
    new_row = "| - | 1.2 | 02-110 | - | Item # 42 | Concrete Outfall | crew_lab_2 | - | 240 | CY | - |"
    edited = text + "\n" + new_row
    parsed = parse_compact(edited, base_spec=spec, pack=demo_pack)
    assert len(parsed["items"]) == 1
    new_item = parsed["items"][0]
    assert new_item["item_no"] == "Item # 42"
    assert new_item["description"] == "Concrete Outfall"
    assert new_item["uom"] == "CY"
    assert new_item["qty"] == 240
    assert new_item["wbs"] == "1.2"
    assert new_item["cost_code"] == "02-110"
    assert new_item["crew_id"] == "crew_lab_2"
    # Defaults, from the demo pack's own scaffold roles:
    assert new_item["recipe"] == "setup"
    assert new_item["sheet"] == "Item # 42"
    assert new_item["labor"] == []
    # No id yet (populated on next sync):
    assert "estimate_item_id" not in new_item


def test_parse_compact_new_row_with_dash_qty_defaults_to_1():
    """New items need a qty for schema validity; `-` in the qty cell defaults to 1."""
    spec = _spec(items=[])
    text = render_compact(spec)
    new_row = "| - | - | - | - | Item # 99 | Something | - | - | - | LS | - |"
    edited = text + "\n" + new_row
    parsed = parse_compact(edited, base_spec=spec)
    assert parsed["items"][0]["qty"] == 1


def test_parse_compact_new_row_with_no_optional_fields_omits_them():
    """New item stubs skip the Phase 4.5 optional fields when the row has `-`."""
    spec = _spec(items=[])
    text = render_compact(spec)
    new_row = "| - | - | - | - | Item # 99 | Something | - | - | - | LS | - |"
    edited = text + "\n" + new_row
    parsed = parse_compact(edited, base_spec=spec)
    stub = parsed["items"][0]
    assert "wbs" not in stub
    assert "cost_code" not in stub
    assert "crew_id" not in stub


# ---- pack-driven stub recipe (Plan C Task 5) --------------------------------

from estimating_tools.estimate_spec.compact import _stub_new_item
from estimating_tools.estimate_spec.format_pack import ENGINE_DIR, load_pack

LEGACY_DIR = ENGINE_DIR / "tests" / "fixtures" / "packs" / "legacy_demo"


@pytest.fixture(scope="module")
def demo_pack():
    return load_pack(LEGACY_DIR)


def test_compact_stub_uses_pack_default_recipe(demo_pack, monkeypatch):
    """Omitting `pack` falls back to `bundled_pack()` — proven generically by
    redirecting the bundled pack to the demo pack rather than depending on
    whichever pack format_pack.py bundles today. The demo pack's rate-host
    recipe is `setup`: a hardcoded literal (e.g. a reference-pack name) would
    fail this."""
    import estimating_tools.estimate_spec.compact as compact_mod
    monkeypatch.setattr(compact_mod, "bundled_pack", lambda: demo_pack)

    row = {"item_no": "7", "task_name": "New Task", "uom": "EA",
           "qty": "-", "wbs": "-", "cost_code": "-", "crew_id": "-"}
    ref_item = _stub_new_item(row, 1)
    assert ref_item["recipe"] == "setup"
    assert "takeoff" not in ref_item

    demo_item = _stub_new_item(row, 1, demo_pack)
    assert demo_item["recipe"] == "setup"
    assert "takeoff" not in demo_item


def test_parse_compact_new_row_uses_demo_pack_recipe(demo_pack):
    """End-to-end through parse_compact: the pack threads down to the stub."""
    spec = _spec(items=[])
    text = render_compact(spec)
    new_row = "| - | - | - | - | Item # 1 | Trench | - | - | 100 | LF | - |"
    edited = text + "\n" + new_row
    parsed = parse_compact(edited, base_spec=spec, pack=demo_pack)
    assert parsed["items"][0]["recipe"] == "setup"


def test_parse_compact_add_and_edit_together():
    """Combined: existing item edited + new item added in one parse."""
    spec = _spec(items=[_synced_item(estimate_item_id=1, item_no="Item # 1",
                                     wbs="0.1")])
    text = render_compact(spec)
    # Edit Item # 1's wbs from 0.1 → 0.2:
    edited = text.replace("| 1 | 0.1 |", "| 1 | 0.2 |")
    # Append a new row:
    new_row = "| - | - | - | - | Item # 2 | New task | - | - | 1 | LS | - |"
    edited = edited + "\n" + new_row
    parsed = parse_compact(edited, base_spec=spec)
    assert len(parsed["items"]) == 2
    assert parsed["items"][0]["wbs"] == "0.2"
    assert parsed["items"][1]["item_no"] == "Item # 2"


def test_parse_compact_new_row_blank_optional_cell_omits_key():
    """A blanked (rather than `-`) optional cell on a new row should behave
    the same as `-` — key omitted. Matches the edit-path convention."""
    spec = _spec(items=[])
    text = render_compact(spec)
    # wbs is a blank cell (two spaces between pipes), cost_code and crew_id are `-`:
    new_row = "| - |  | - | - | Item # 50 | Task | - | - | 1 | EA | - |"
    edited = text + "\n" + new_row
    parsed = parse_compact(edited, base_spec=spec)
    stub = parsed["items"][0]
    assert "wbs" not in stub


def test_parse_compact_new_row_missing_item_no_raises_with_row_locator():
    """Required-field errors on the add path carry a row locator."""
    spec = _spec(items=[])
    text = render_compact(spec)
    new_row = "| - | - | - | - | - | Something | - | - | 1 | LS | - |"
    edited = text + "\n" + new_row
    with pytest.raises(ValueError, match=r"row 1.*item_no"):
        parse_compact(edited, base_spec=spec)


def test_parse_compact_new_row_missing_task_name_raises_with_row_locator():
    spec = _spec(items=[])
    text = render_compact(spec)
    new_row = "| - | - | - | - | Item # 99 | - | - | - | 1 | LS | - |"
    edited = text + "\n" + new_row
    with pytest.raises(ValueError, match=r"row 1.*task_name"):
        parse_compact(edited, base_spec=spec)


def test_parse_compact_new_row_missing_uom_raises_with_row_locator():
    spec = _spec(items=[])
    text = render_compact(spec)
    new_row = "| - | - | - | - | Item # 99 | Task | - | - | 1 | - | - |"
    edited = text + "\n" + new_row
    with pytest.raises(ValueError, match=r"row 1.*uom"):
        parse_compact(edited, base_spec=spec)


def test_parse_compact_multi_new_row_error_reports_correct_row_locator():
    """When two new rows are added and the SECOND has a malformed qty,
    the error message should say 'row 2', not 'row 1'."""
    spec = _spec(items=[])
    text = render_compact(spec)
    ok_row = "| - | - | - | - | Item # 1 | Task A | - | - | 1 | LS | - |"
    bad_row = "| - | - | - | - | Item # 2 | Task B | - | - | oops | LS | - |"
    edited = text + "\n" + ok_row + "\n" + bad_row
    with pytest.raises(ValueError, match=r"row 2.*qty.*'oops'"):
        parse_compact(edited, base_spec=spec)


# ---- Phase 3c: mixed-edits integration test on the alt pack fixture -------

def test_parse_compact_mixed_edits_on_the_alt_pack_fixture(alt_pack):
    """Real-fixture stress test: rename via id, tweak wbs, add a new item,
    delete an item, and confirm the resulting spec is coherent.

    The alt pack's own example has three items:
      - Item 1 (preamble, LS, no wbs/cost_code)
      - Item 2 (24-inch duct run, CY, wbs=3.1, cost_code=10-210,
                crew_id=DUCT-CREW, geometry takeoff + labor)
      - Item 3 (spring hangers, subcontractor takeoff)

    Neither item has estimate_item_id in the on-disk YAML. For this test we
    populate ids on the loaded dict so the id join path is exercised.
    """
    import yaml

    spec = yaml.safe_load(ALT_SAMPLE.read_text(encoding="utf-8"))
    # Assign synthetic ids to exercise the id join path:
    for i, item in enumerate(spec["items"], start=1):
        item["estimate_item_id"] = i * 100                    # 100, 200, 300

    text = render_compact(spec)
    # Edit 1: rename Item 2 → Item 2A (via the id-anchored path):
    edited = text.replace("Item 2", "Item 2A")
    # Edit 2: change wbs from 3.1 → 3.2:
    edited = edited.replace("| 3.1 |", "| 3.2 |")
    # Edit 3: delete Item 1 by dropping its row (find and remove it):
    lines = edited.splitlines()
    lines = [ln for ln in lines if "Item 1" not in ln]
    edited = "\n".join(lines)
    # Edit 4: add a new item at the end:
    new_row = "| - | 5.0 | - | - | Item 9 | Punchlist | - | - | 1 | LS | - |"
    edited = edited + "\n" + new_row

    parsed = parse_compact(edited, base_spec=spec, pack=alt_pack)

    # 3 items in output: the renamed/tweaked #2A, the untouched #3, and #9.
    assert len(parsed["items"]) == 3

    # Item 2A: labor/takeoff/spreads/cost_details round-tripped, name and
    # wbs changed.
    duct_run = parsed["items"][0]
    assert duct_run["item_no"] == "Item 2A"
    assert duct_run["wbs"] == "3.2"
    assert duct_run["cost_code"] == "10-210"
    assert duct_run["crew_id"] == "DUCT-CREW"
    # Body round-tripped byte-for-byte except item_no/wbs/estimate_item_id:
    unchanged = yaml.safe_load(ALT_SAMPLE.read_text(encoding="utf-8"))["items"][1]
    for key, value in unchanged.items():
        if key not in ("item_no", "wbs"):
            assert duct_run[key] == value, key
    assert duct_run["recipe"] == "work_item"
    assert duct_run["takeoff"]["kind"] == "geometry"
    assert len(duct_run["labor"]) == 2
    assert duct_run["labor"][0]["slot"] == "AA"

    # Item 3: untouched, still present, its own id preserved.
    hangers = parsed["items"][1]
    assert hangers["item_no"] == "Item 3"
    assert hangers["estimate_item_id"] == 300

    # Item 9: new stub
    punchlist = parsed["items"][2]
    assert punchlist["item_no"] == "Item 9"
    assert punchlist["description"] == "Punchlist"
    assert punchlist["uom"] == "LS"
    assert punchlist["qty"] == 1
    assert punchlist["wbs"] == "5.0"
    assert punchlist["recipe"] == "preamble"                 # stub default: alt's rate-host recipe
    assert punchlist["sheet"] == "Item 9"                    # stub default
    assert punchlist["labor"] == []                           # stub default
    # No id yet on new items:
    assert "estimate_item_id" not in punchlist

    # Top-level fields preserved:
    assert parsed["project"] == "Alt Pack Duct Package"
    assert parsed["rate_table"] == spec["rate_table"]
    assert parsed["crews"] == spec["crews"]


# ---- Phase 3c: id-clear guard (Critical finding from final review) --------

def test_parse_compact_dash_id_row_matching_synced_item_no_raises():
    """Silent data loss guard: if an agent clears the id cell but leaves
    item_no matching a synced base item, refuse the parse with a clear error
    naming both the item_no and the id the agent probably meant to keep."""
    spec = _spec(items=[_synced_item(estimate_item_id=100, item_no="Item # 42")])
    text = render_compact(spec)
    # Simulate the mistake: clear the id cell (100 → -). item_no untouched.
    edited = text.replace("| 100 |", "| - |")
    with pytest.raises(ValueError,
                       match=r"row 1.*Item # 42.*synced.*estimate_item_id=100"):
        parse_compact(edited, base_spec=spec)


def test_parse_compact_new_row_colliding_with_synced_item_no_raises():
    """Symmetric case: appending a new row (id=-) whose item_no happens to
    collide with a synced item's item_no also raises."""
    spec = _spec(items=[_synced_item(estimate_item_id=100, item_no="Item # 42")])
    text = render_compact(spec)
    # Append a new row that reuses the synced item's item_no:
    new_row = "| - | - | - | - | Item # 42 | Different Task | - | - | 1 | LS | - |"
    edited = text + "\n" + new_row
    with pytest.raises(ValueError,
                       match=r"Item # 42.*synced.*estimate_item_id=100"):
        parse_compact(edited, base_spec=spec)


# ---- Phase 3c: id validation consistency (Copilot review) ------------------

def test_id_cell_renders_dash_when_estimate_item_id_is_zero():
    """Schema requires estimate_item_id >= 1; 0 is malformed → render `-`."""
    item = _mob_item(estimate_item_id=0)
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[0] == "-"


def test_id_cell_renders_dash_when_estimate_item_id_is_negative():
    item = _mob_item(estimate_item_id=-5)
    out = render_compact(_spec(items=[item]))
    cells = _row_for(out, "Item # 1")
    assert cells[0] == "-"


def test_parse_compact_rejects_zero_id_cell_with_row_locator():
    """Parser refuses non-positive id cells (schema minimum 1)."""
    spec = _spec(items=[])
    text = render_compact(spec)
    new_row = "| 0 | - | - | - | Item # 99 | Task | - | - | 1 | LS | - |"
    edited = text + "\n" + new_row
    with pytest.raises(ValueError, match=r"row 1.*id 0.*minimum = 1"):
        parse_compact(edited, base_spec=spec)


def test_parse_compact_rejects_negative_id_cell_with_row_locator():
    spec = _spec(items=[])
    text = render_compact(spec)
    new_row = "| -5 | - | - | - | Item # 99 | Task | - | - | 1 | LS | - |"
    edited = text + "\n" + new_row
    with pytest.raises(ValueError, match=r"row 1.*id -5.*minimum = 1"):
        parse_compact(edited, base_spec=spec)


def test_parse_compact_base_spec_with_malformed_id_treats_item_as_unsynced():
    """A base item with a malformed estimate_item_id (e.g. bool, float, 0)
    renders as `-` and must be treated as un-synced by the parser — so an
    id-clear guard doesn't incorrectly fire against it."""
    spec = _spec(items=[_mob_item(estimate_item_id=True, item_no="Item # 1")])
    text = render_compact(spec)
    # An unedited round-trip must succeed — the malformed id renders `-`,
    # so the row's `-` id is consistent with the base item being un-synced.
    parsed = parse_compact(text, base_spec=spec)
    assert len(parsed["items"]) == 1
    # The malformed estimate_item_id is NOT stripped from the returned dict
    # (parse_compact preserves the base item's fields on round-trip) —
    # only the synced/un-synced classification changes.
    assert parsed["items"][0]["item_no"] == "Item # 1"


def test_parse_compact_base_spec_with_duplicate_estimate_item_id_raises():
    """Two base items sharing an estimate_item_id is a hard error — the
    by_id lookup would silently prefer the last one otherwise, joining rows
    to the wrong base item."""
    spec = _spec(items=[
        _synced_item(estimate_item_id=100, item_no="Item # A"),
        _synced_item(estimate_item_id=100, item_no="Item # B"),
    ])
    text = render_compact(spec)
    with pytest.raises(ValueError, match=r"estimate_item_id 100.*ambiguous"):
        parse_compact(text, base_spec=spec)
