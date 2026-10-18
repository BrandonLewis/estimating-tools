"""The read-back's picture of the fieldbook grid is the pack's own.

`readback/layout.py` restates where fieldbook puts each input and formula;
every test here reads `packs/fieldbook/units.yaml` and fails the moment a
pack edit moves a column the reader still looks for.
"""
from __future__ import annotations

import yaml

from estimating_tools.estimate_spec.readback import layout as L
from estimating_tools.estimate_spec.tests._fieldbook import FIELDBOOK_DIR

UNITS = yaml.safe_load((FIELDBOOK_DIR / "units.yaml").read_text(encoding="utf-8"))["units"]
TAKEOFF_UNITS = {"takeoff_linear": "linear", "takeoff_count": "count",
                 "takeoff_measured": "measured"}


def _tagged_rows():
    """(unit name, kind tag, cells) for every unit row that writes a kind tag."""
    for name, unit in UNITS.items():
        for row in unit.get("rows") or []:
            cells = row.get("cells") or {}
            kind = (cells.get(L.KIND_COL) or {}).get("value")
            if kind:
                yield name, kind, cells


def _is_input(cell: dict) -> bool:
    return str(cell.get("style", "")).startswith(("input_", "band_input"))


def test_the_reader_knows_every_kind_tag():
    assert {kind for _, kind, _ in _tagged_rows()} == L.KINDS


def test_formula_columns_are_the_packs():
    # An input written through `formula:` (crew days, a line's qty and price,
    # the bid qty -- a number, or a formula the spec itself carries) is an
    # input, not a formula a literal could be typed over.
    for name, kind, cells in _tagged_rows():
        got = {c for c, cell in cells.items() if "formula" in cell and not _is_input(cell)}
        want = set(L.formula_columns(kind, label=(cells.get("A") or {}).get("value"),
                                     in_task=name == "task", takeoff_kind=TAKEOFF_UNITS.get(name)))
        assert got == want, (name, kind)


def test_input_columns_are_the_packs():
    for name, kind, cells in _tagged_rows():
        got = {c for c, cell in cells.items() if _is_input(cell)}
        assert got == set(L.INPUT_COLS.get((kind, TAKEOFF_UNITS.get(name)), "")), (name, kind)


def _cell(unit: str, kind: str, col: str) -> str:
    (cells,) = [c for n, k, c in _tagged_rows() if n == unit and k == kind]
    cell = cells[col]
    return cell.get("value", cell.get("formula"))


def test_each_field_is_read_from_the_column_the_pack_writes_it_to():
    assert _cell("task", "TASK", L.TASK_CODE) == "{p.cost_code}"
    assert _cell("task", "TASK", L.TASK_DESC) == "{p.description}"
    assert [_cell("task", "CREW", c) for c in (L.CREW_TRADE, L.CREW_COUNT, L.CREW_DAYS)] == [
        "{it.trade}", "{it.count}", "{it.days}"]
    assert [_cell("task", "LINE", c) for c in (
        L.LINE_NAME, L.LINE_QTY, L.LINE_UOM, L.LINE_PRICE, L.LINE_TYPE, L.LINE_SOURCE,
        L.LINE_VENDOR)] == ["{it.name}", "{it.qty}", "{it.uom}", "{it.unit_price}",
                            "{p.type_{it.cost_type}}", "{p.src_{it.source}}", "{it.vendor}"]
    assert _cell("item_header", "ITEM", L.ITEM_QTY) == "{p.qty}"
    for unit, kind in TAKEOFF_UNITS.items():
        for key, col, _ in L.TAKEOFF_FIELDS[kind]:
            assert _cell(unit, "TAKEOFF", col) == f"{{it.{key}}}", (unit, key)


def test_the_rate_table_columns_are_the_packs():
    (repeat,) = [r for r in UNITS["rates"]["rows"] if r.get("repeat") == "p.rates"]
    cells = {c: v.get("value", v.get("formula")) for c, v in repeat["cells"].items()}
    assert [cells[c] for c in (L.RATE_NAME, L.RATE_KIND, L.RATE_BASE, L.RATE_BURDEN,
                               L.RATE_FRINGE, L.RATE_OPERATOR, L.RATE_FLAT)] == [
        "{it.trade}", "{p.kind_{it.kind}}", "{it.base}", "{it.burden_pct}", "{it.fringe}",
        "{p.op_{it.includes_operator}}", "{it.rate}"]
    assert "formula" in repeat["cells"][L.RATE_HOURLY]


def test_the_markup_grid_columns_are_the_packs():
    (repeat,) = [r for r in UNITS["markup_grid"]["rows"] if r.get("repeat") == "p.rows"]
    assert [repeat["cells"][c]["value"] for c, _ in L.MARKUP_COLS] == [
        f"{{it.{key}}}" for _, key in L.MARKUP_COLS]


def test_dropdown_labels_are_the_packs_defaults():
    task = UNITS["task"]["params"]
    rates = UNITS["rates"]["params"]
    assert {task[f"type_{v}"]["default"]: v for v in L.LINE_TYPES.values()} == L.LINE_TYPES
    assert {task[f"src_{v}"]["default"]: v for v in L.LINE_SOURCES.values()} == L.LINE_SOURCES
    assert {rates[f"kind_{v}"]["default"]: v for v in L.RATE_KINDS.values()} == L.RATE_KINDS
    assert {rates[f"op_{v}"]["default"]: v for v in L.OPERATOR.values()} == L.OPERATOR


def _unit_cell(unit: str, col: str, *, index: int = None, mark: str = None):
    """A book-sheet unit's own cell (by fixed position, or by its `mark`),
    the way `_cell` pins an item-sheet field to its kind tag -- so a label
    moved to another column, or renamed on the wrong row, fails here."""
    rows = UNITS[unit]["rows"]
    row = rows[index] if mark is None else next(r for r in rows if r.get("mark") == mark)
    cell = row["cells"][col]
    return cell.get("value", cell.get("formula"))


def test_book_sheet_labels_are_pinned_to_their_unit_and_column():
    assert _unit_cell("rates", "A", index=0) == L.RATES_HEAD
    assert _unit_cell("rates", "A", mark="end") == L.RATES_MARKER
    assert _unit_cell("rates_shift", "A", mark="shift") == L.SHIFT_LABEL
    assert _unit_cell("rates_shift", "B", mark="shift") == "{p.shift_hours}"
    assert _unit_cell("markup_grid", "A", index=1) == L.MARKUP_HEAD
    assert _unit_cell("markup_grid", "A", mark="total") == L.MARKUP_TOTAL
    assert _unit_cell("markup_grid", "A", mark="bond") == L.BOND_LABEL
    assert _unit_cell("markup_grid", "B", mark="bond") == "{p.bond}"
    assert _unit_cell("unbalance_head", "C", mark="heads") == L.UNBALANCE_HEAD
    assert _unit_cell("unbalance_total", "A", mark="total") == L.UNBALANCE_TOTAL
    assert _unit_cell("bid_form_head", "A", index=1) == L.BID_DATE_LABEL
    assert _unit_cell("bid_form_head", "B", index=1) == "{p.bid_date}"


def test_the_markup_rows_are_the_ones_the_recipe_lays_out():
    recipes = yaml.safe_load((FIELDBOOK_DIR / "recipes.yaml").read_text(encoding="utf-8"))
    (markup,) = [s for s in recipes["book"] if s["sheet_name"] == L.MARKUP_SHEET]
    (grid,) = [u for u in markup["units"] if u["unit"] == "markup_grid"]
    assert tuple(r["name"].lower() for r in grid["params"]["rows"]) == L.MARKUP_ROWS


def test_visible_cols_run_up_to_the_hidden_tag_column():
    from openpyxl.utils import column_index_from_string, get_column_letter
    last = column_index_from_string(L.KIND_COL) - 1
    assert L.VISIBLE_COLS == "".join(get_column_letter(i) for i in range(1, last + 1))


def test_takeoff_list_keys_match_each_takeoff_units_own_list_param():
    for unit, kind in TAKEOFF_UNITS.items():
        list_params = [name for name, p in UNITS[unit]["params"].items() if p.get("type") == "list"]
        assert list_params == [L.TAKEOFF_LIST[kind]], (unit, kind)


def test_baseline_sheets_are_the_book_sheets_other_than_rates_and_codes():
    # Rates grows with new rates (not fixed-shape) and Codes is regenerated
    # (decision 9) -- every other book sheet's shape depends only on the
    # items, which read-back has already confirmed match the spec.
    recipes = yaml.safe_load((FIELDBOOK_DIR / "recipes.yaml").read_text(encoding="utf-8"))
    sheet_names = {s["sheet_name"] for s in recipes["book"]}
    assert set(L.BASELINE_SHEETS) <= sheet_names
    assert sheet_names - set(L.BASELINE_SHEETS) == {"Rates", "Codes"}


def test_the_shown_but_unread_text_cells_are_the_packs():
    assert (_cell("item_header", "ITEM", L.ITEM_DESC),
            _cell("item_header", "ITEM", L.ITEM_UOM)) == ("{p.description}", "{p.uom}")
    assert L.BID_FORM_PROJECT == "A1"                      # the head's first row, column A
    assert _unit_cell("bid_form_head", "A", index=0) == "{p.project}"
