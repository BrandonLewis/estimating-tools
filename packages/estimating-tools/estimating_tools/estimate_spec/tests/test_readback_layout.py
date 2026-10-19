"""The read-back's picture of the fieldbook grid is the pack's own.

`readback/layout.py` restates where fieldbook puts each input and formula;
every test here reads a pack's `units.yaml` and fails the moment a pack edit
moves a column the reader still looks for.

It runs against EVERY pack read-back would read: the bundled fieldbook, any
pack in the repo whose `readback_family` is fieldbook (`derived_from:
fieldbook`), and a generated fieldbook fork -- so a derived pack cannot drift
the columns silently. An org can run the same checks against its own pack by
setting EST_READBACK_LAYOUT_PACKS to its pack directories (os.pathsep-separated).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from estimating_tools.estimate_spec import format_pack as fp
from estimating_tools.estimate_spec.readback import layout as L
from estimating_tools.estimate_spec.tests._fieldbook import DERIVED_NAME, derived_pack_dir

FIXTURE_PACKS = Path(__file__).resolve().parent / "fixtures" / "packs"
TAKEOFF_UNITS = {"takeoff_linear": "linear", "takeoff_count": "count",
                 "takeoff_measured": "measured"}
_GENERATED = f"{DERIVED_NAME} (generated)"


def _family_packs() -> dict:
    """{id: pack directory} for every committed pack read-back reads, plus
    EVERY pack named in EST_READBACK_LAYOUT_PACKS -- one there outside the
    fieldbook family fails the contract rather than being skipped (an org
    asked for it to be checked)."""
    roots = [d for base in (fp.ENGINE_DIR / "packs", FIXTURE_PACKS)
             for d in sorted(base.iterdir()) if (d / fp.MANIFEST).is_file()]
    out = {}
    for root in roots:
        pack = fp.load_pack(root)
        if fp.readback_family(pack) == L.FAMILY:
            out[f"{pack.name}@{root.name}"] = root
    for d in os.environ.get("EST_READBACK_LAYOUT_PACKS", "").split(os.pathsep):
        if d:
            out[f"env:{d}"] = Path(d)
    return out


PACKS = _family_packs()


@pytest.fixture(scope="module", params=[*PACKS, _GENERATED])
def pack_dir(request, tmp_path_factory) -> Path:
    if request.param == _GENERATED:
        return derived_pack_dir(tmp_path_factory.mktemp("derived"))
    return PACKS[request.param]


@pytest.fixture(scope="module")
def units(pack_dir) -> dict:
    return fp.load_pack(pack_dir).units


@pytest.fixture(scope="module")
def recipes(pack_dir) -> dict:
    return fp.load_pack(pack_dir).recipes


def test_the_contract_covers_fieldbook_and_every_pack_derived_from_it(pack_dir):
    assert "fieldbook" in {fp.load_pack(d).name for d in PACKS.values()}
    pack = fp.load_pack(pack_dir)
    assert fp.readback_family(pack) == L.FAMILY
    assert pack.name == L.FAMILY or pack.derived_from == L.FAMILY


def _tagged_rows(units):
    """(unit name, kind tag, cells) for every unit row that writes a kind tag."""
    for name, unit in units.items():
        for row in unit.get("rows") or []:
            cells = row.get("cells") or {}
            kind = (cells.get(L.KIND_COL) or {}).get("value")
            if kind:
                yield name, kind, cells


def _is_input(cell: dict) -> bool:
    return str(cell.get("style", "")).startswith(("input_", "band_input"))


def test_the_reader_knows_every_kind_tag(units):
    assert {kind for _, kind, _ in _tagged_rows(units)} == L.KINDS


def test_formula_columns_are_the_packs(units):
    # An input written through `formula:` (crew days, a line's qty and price,
    # the bid qty -- a number, or a formula the spec itself carries) is an
    # input, not a formula a literal could be typed over.
    for name, kind, cells in _tagged_rows(units):
        got = {c for c, cell in cells.items() if "formula" in cell and not _is_input(cell)}
        want = set(L.formula_columns(kind, label=(cells.get("A") or {}).get("value"),
                                     in_task=name == "task", takeoff_kind=TAKEOFF_UNITS.get(name)))
        assert got == want, (name, kind)


def test_input_columns_are_the_packs(units):
    for name, kind, cells in _tagged_rows(units):
        got = {c for c, cell in cells.items() if _is_input(cell)}
        assert got == set(L.INPUT_COLS.get((kind, TAKEOFF_UNITS.get(name)), "")), (name, kind)


def _cell(units, unit: str, kind: str, col: str) -> str:
    (cells,) = [c for n, k, c in _tagged_rows(units) if n == unit and k == kind]
    cell = cells.get(col) or {}            # a moved field fails the comparison, not a lookup
    return cell.get("value", cell.get("formula"))


def test_each_field_is_read_from_the_column_the_pack_writes_it_to(units):
    assert _cell(units, "task", "TASK", L.TASK_CODE) == "{p.cost_code}"
    assert _cell(units, "task", "TASK", L.TASK_DESC) == "{p.description}"
    assert [_cell(units, "task", "CREW", c) for c in (L.CREW_TRADE, L.CREW_COUNT, L.CREW_DAYS)] == [
        "{it.trade}", "{it.count}", "{it.days}"]
    assert [_cell(units, "task", "LINE", c) for c in (
        L.LINE_NAME, L.LINE_QTY, L.LINE_UOM, L.LINE_PRICE, L.LINE_TYPE, L.LINE_SOURCE,
        L.LINE_VENDOR)] == ["{it.name}", "{it.qty}", "{it.uom}", "{it.unit_price}",
                            "{p.type_{it.cost_type}}", "{p.src_{it.source}}", "{it.vendor}"]
    assert _cell(units, "item_header", "ITEM", L.ITEM_QTY) == "{p.qty}"
    for unit, kind in TAKEOFF_UNITS.items():
        for key, col, _ in L.TAKEOFF_FIELDS[kind]:
            assert _cell(units, unit, "TAKEOFF", col) == f"{{it.{key}}}", (unit, key)


def test_the_rate_table_columns_are_the_packs(units):
    (repeat,) = [r for r in units["rates"]["rows"] if r.get("repeat") == "p.rates"]
    cells = {c: v.get("value", v.get("formula")) for c, v in repeat["cells"].items()}
    assert [cells[c] for c in (L.RATE_NAME, L.RATE_KIND, L.RATE_BASE, L.RATE_BURDEN,
                               L.RATE_FRINGE, L.RATE_OPERATOR, L.RATE_FLAT)] == [
        "{it.trade}", "{p.kind_{it.kind}}", "{it.base}", "{it.burden_pct}", "{it.fringe}",
        "{p.op_{it.includes_operator}}", "{it.rate}"]
    assert "formula" in repeat["cells"][L.RATE_HOURLY]


def test_the_markup_grid_columns_are_the_packs(units):
    (repeat,) = [r for r in units["markup_grid"]["rows"] if r.get("repeat") == "p.rows"]
    assert [repeat["cells"][c]["value"] for c, _ in L.MARKUP_COLS] == [
        f"{{it.{key}}}" for _, key in L.MARKUP_COLS]


def test_dropdown_labels_are_the_packs_defaults(units):
    task = units["task"]["params"]
    rates = units["rates"]["params"]
    assert {task[f"type_{v}"]["default"]: v for v in L.LINE_TYPES.values()} == L.LINE_TYPES
    assert {task[f"src_{v}"]["default"]: v for v in L.LINE_SOURCES.values()} == L.LINE_SOURCES
    assert {rates[f"kind_{v}"]["default"]: v for v in L.RATE_KINDS.values()} == L.RATE_KINDS
    assert {rates[f"op_{v}"]["default"]: v for v in L.OPERATOR.values()} == L.OPERATOR


def _unit_cell(units, unit: str, col: str, *, index: int = None, mark: str = None):
    """A book-sheet unit's own cell (by fixed position, or by its `mark`),
    the way `_cell` pins an item-sheet field to its kind tag -- so a label
    moved to another column, or renamed on the wrong row, fails here."""
    rows = units[unit]["rows"]
    row = rows[index] if mark is None else next(r for r in rows if r.get("mark") == mark)
    cell = row["cells"][col]
    return cell.get("value", cell.get("formula"))


def test_book_sheet_labels_are_pinned_to_their_unit_and_column(units):
    assert _unit_cell(units, "rates", "A", index=0) == L.RATES_HEAD
    assert _unit_cell(units, "rates", "A", mark="end") == L.RATES_MARKER
    assert _unit_cell(units, "rates_shift", "A", mark="shift") == L.SHIFT_LABEL
    assert _unit_cell(units, "rates_shift", "B", mark="shift") == "{p.shift_hours}"
    assert _unit_cell(units, "markup_grid", "A", index=1) == L.MARKUP_HEAD
    assert _unit_cell(units, "markup_grid", "A", mark="total") == L.MARKUP_TOTAL
    assert _unit_cell(units, "markup_grid", "A", mark="bond") == L.BOND_LABEL
    assert _unit_cell(units, "markup_grid", "B", mark="bond") == "{p.bond}"
    assert _unit_cell(units, "unbalance_head", "C", mark="heads") == L.UNBALANCE_HEAD
    assert _unit_cell(units, "unbalance_total", "A", mark="total") == L.UNBALANCE_TOTAL
    assert _unit_cell(units, "bid_form_head", "A", index=1) == L.BID_DATE_LABEL
    assert _unit_cell(units, "bid_form_head", "B", index=1) == "{p.bid_date}"


def test_the_markup_rows_are_the_ones_the_recipe_lays_out(recipes):
    (markup,) = [s for s in recipes["book"] if s["sheet_name"] == L.MARKUP_SHEET]
    (grid,) = [u for u in markup["units"] if u["unit"] == "markup_grid"]
    assert tuple(r["name"].lower() for r in grid["params"]["rows"]) == L.MARKUP_ROWS


def test_visible_cols_run_up_to_the_hidden_tag_column():
    from openpyxl.utils import column_index_from_string, get_column_letter
    last = column_index_from_string(L.KIND_COL) - 1
    assert L.VISIBLE_COLS == "".join(get_column_letter(i) for i in range(1, last + 1))


def test_takeoff_list_keys_match_each_takeoff_units_own_list_param(units):
    for unit, kind in TAKEOFF_UNITS.items():
        list_params = [name for name, p in units[unit]["params"].items() if p.get("type") == "list"]
        assert list_params == [L.TAKEOFF_LIST[kind]], (unit, kind)


def test_baseline_sheets_are_the_book_sheets_other_than_rates_and_codes(recipes):
    # Rates grows with new rates (not fixed-shape) and Codes is regenerated
    # (decision 9) -- every other book sheet's shape depends only on the
    # items, which read-back has already confirmed match the spec.
    sheet_names = {s["sheet_name"] for s in recipes["book"] if "for_each" not in s}
    assert set(L.BASELINE_SHEETS) <= sheet_names
    assert sheet_names - set(L.BASELINE_SHEETS) == {"Rates", "Codes"}


def test_the_shown_but_unread_text_cells_are_the_packs(units):
    assert (_cell(units, "item_header", "ITEM", L.ITEM_DESC),
            _cell(units, "item_header", "ITEM", L.ITEM_UOM)) == ("{p.description}", "{p.uom}")
    assert L.BID_FORM_PROJECT == "A1"                      # the head's first row, column A
    assert _unit_cell(units, "bid_form_head", "A", index=0) == "{p.project}"


# --- the checks are not vacuous ---------------------------------------------

def _move_crew_count(units) -> None:
    """A fork that moves the crew count input from D to C."""
    for row in units["task"]["rows"]:
        cells = row.get("cells") or {}
        if (cells.get(L.KIND_COL) or {}).get("value") == "CREW":
            cells["C"] = cells.pop(L.CREW_COUNT)


def test_a_derived_pack_that_moves_an_input_column_fails_the_contract(tmp_path):
    moved = derived_pack_dir(tmp_path, units_edit=_move_crew_count)
    assert fp.readback_family(fp.load_pack(moved)) == L.FAMILY   # it loads, and claims the family
    units = yaml.safe_load((moved / "units.yaml").read_text(encoding="utf-8"))["units"]
    with pytest.raises(AssertionError):
        test_input_columns_are_the_packs(units)
    with pytest.raises(AssertionError):
        test_each_field_is_read_from_the_column_the_pack_writes_it_to(units)


def test_a_pack_named_in_the_environment_is_checked_even_outside_the_family(monkeypatch):
    """EST_READBACK_LAYOUT_PACKS is an org asking for its pack to be checked:
    a pack there that is not in the fieldbook family fails, never skips."""
    from estimating_tools.estimate_spec.tests._packs import LEGACY_DIR
    monkeypatch.setenv("EST_READBACK_LAYOUT_PACKS", str(LEGACY_DIR))
    assert LEGACY_DIR in _family_packs().values()
    with pytest.raises(AssertionError):
        test_the_contract_covers_fieldbook_and_every_pack_derived_from_it(LEGACY_DIR)


def test_the_package_tag_and_columns_are_the_packs(units):
    assert _unit_cell(units, "package_head", L.KIND_COL, index=0) == L.PACKAGE_TAG
    (crew,) = [c for n, k, c in _tagged_rows(units) if n == "task" and k == "CREW"]
    (line,) = [c for n, k, c in _tagged_rows(units) if n == "task" and k == "LINE"]
    for cells in (crew, line):
        assert cells[L.PACKAGE_ROW_TAG_COL]["value"] == "{it.u_tag}"
        assert "formula" in cells[L.ARR_BASIS_COL]


def test_the_package_sheet_labels_are_the_packs(units):
    lines = units["package_lines"]["rows"]
    head = lines[0]["cells"]
    h = L.PKG_HEADERS
    assert {k: head[c]["value"] for k, c in
            {"item": "A", "line": "B", "qty": "D", "uom": "E", "rate": "F", "pick": "H",
             "arr": "I", "arr_ext": "J"}.items()} == {k: h[k] for k in
            ("item", "line", "qty", "uom", "rate", "pick", "arr", "arr_ext")}
    assert head["{col:vl+2}"]["value"] == h["carry"]
    assert head["{col:vl+4}"]["value"] == h["source"]
    assert head["{col:vl+5}"]["value"] == h["state"]
    assert lines[0]["repeat_cols"]["cells"]["+1"]["value"] == h["ext"]
    assert lines[0]["repeat_cols"]["start"] == "K"        # vendor pairs start after ARR ext (J)
    assert lines[1]["cells"]["A"]["value"] == L.PKG_QUOTE_REF_LABEL
    assert lines[2]["cells"]["A"]["value"] == L.PKG_SURCHARGE_LABEL
    sel = next(r for r in units["package_head"]["rows"] if r.get("mark") == "sel")["cells"]
    assert sel["E"]["value"] == L.PKG_SELECTOR_LABEL
    assert sel["F"]["style"] == "input_select"
    items = units["package_items"]["rows"]
    assert items[0]["cells"]["B"]["value"] == L.PKG_ITEMS_HEAD
    assert items[1]["cells"]["B"]["value"] == L.PKG_ITEM_ROW_LABEL
    assert units["package_totals"]["rows"][0]["cells"]["A"]["value"] == L.PKG_TOTAL_LABEL
    assert units["package_conditions"]["rows"][0]["cells"]["B"]["value"] == L.PKG_CONDITIONS_LABEL
    assert units["package_conditions"]["rows"][1]["cells"]["B"]["value"] == "{it.text}"


def test_the_summary_sheet_is_a_baseline_sheet(recipes):
    names = {s["sheet_name"] for s in recipes["book"] if "for_each" not in s}
    assert L.SUMMARY_SHEET in names and L.SUMMARY_SHEET in L.BASELINE_SHEETS
