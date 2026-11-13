"""Fieldbook on the contract, delivery 1 (fieldbook spec, "Testing"): the
golden book reads back with no changes; two builds differ only in the
export time; each bound input, edited, is one update of its field."""
from __future__ import annotations

import json
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from estimating_tools.estimate_spec.pack import FieldbookPack
from estimating_tools.estimate_spec.tests import _exchange as X
from estimating_tools.exchange import reader


def _run(path):
    _book, _s, _changes, change_set, problems = reader.run(path, pack=FieldbookPack())
    return change_set, problems.items


def test_an_untouched_book_reads_back_with_no_changes(tmp_path):
    change_set, problems = _run(X.book(tmp_path))
    assert problems == []
    assert (change_set.ops, change_set.notes) == ([], [])
    assert reader.read_book(X.book(tmp_path / "again"), pack=FieldbookPack()).ops == []


def _dump(path) -> dict:
    """Every cell's value or formula, every defined name, every custom
    property, and the hidden columns, of a saved book."""
    wb = load_workbook(path)
    out = {}
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is not None:
                    out[(ws.title, cell.coordinate)] = cell.value
        out[(ws.title, "hidden")] = tuple(sorted(
            k for k, d in ws.column_dimensions.items() if d.hidden))
        out[(ws.title, "state")] = ws.sheet_state
    for name, dn in wb.defined_names.items():
        out[("name", name)] = dn.attr_text
    for prop in wb.custom_doc_props.props:
        out[("property", prop.name)] = prop.value
    return out


def test_two_builds_differ_only_in_the_export_time(tmp_path):
    a = _dump(X.book(tmp_path / "a"))
    assert _dump(X.book(tmp_path / "b")) == a
    later = _dump(X.book(tmp_path / "c", exported_at="2026-11-09T10:30:00Z"))
    assert {k for k in a.keys() | later.keys() if a.get(k) != later.get(k)} == {
        ("_wb", "A1"), ("property", "exported_at")}
    stamps = [json.loads(d[("_wb", "A1")]) for d in (a, later)]
    assert [s.pop("exported_at") for s in stamps] == [X.EXPORTED_AT, "2026-11-09T10:30:00Z"]
    assert stamps[0] == stamps[1]


def _row(ws, ident):
    return next(r for r in range(1, ws.max_row + 1) if ws[f"W{r}"].value == ident)


def _note(ws, task, n):
    """The ``n``-th note row under task ``task``."""
    head = _row(ws, task)
    return [r for r in range(head + 1, ws.max_row + 1) if ws[f"Q{r}"].value == "NOTE"][n]


def _rate(ws, name):
    return next(r for r in range(1, ws.max_row + 1) if ws[f"A{r}"].value == name)


def _set(sheet, find, column, value):
    def edit(wb):
        ws = wb[sheet]
        ws[f"{column}{find(ws)}"] = value
    return edit


EDITS = [
    ("a task's name", _set(X.ITEM1, lambda ws: _row(ws, 21), "B", "Mobilize the yard"),
     [("activity.update", 21, {"name": "Mobilize the yard"})]),
    ("a task's note", _set(X.ITEM1, lambda ws: _note(ws, 21, 1), "A", "Set up the laydown"),
     [("activity.update", 21,
       {"description": "Two days: yard load-out, haul\nSet up the laydown"})]),
    ("the shift length", _set("Rates", lambda ws: 2, "B", 10),
     [("activity.update", a, {"hours_per_shift": Decimal(10)}) for a in (21, 22, 23)]),
    ("a crew row's count", _set(X.ITEM2, lambda ws: _row(ws, 33), "D", 2),
     [("resource.update", 33, {"quantity": Decimal(2)})]),
    ("a crew row's days", _set(X.ITEM2, lambda ws: _row(ws, 33), "E", 9),
     [("resource.update", 33, {"time_value": Decimal(9)})]),
    ("a crew row's time unit", _set(X.ITEM2, lambda ws: _row(ws, 32), "Z", "DAYS"),
     [("resource.update", 32, {"time_unit": "DAYS"})]),
    ("a local rate's cost", _set("Rates", lambda ws: _rate(ws, "Laborer (local)"), "G", 42),
     [("resource.update", 35, {"unit_cost": Decimal(42)})]),
    ("a line's name", _set(X.ITEM2, lambda ws: _row(ws, 34), "A", "8-inch DI pipe, class 52"),
     [("resource.update", 34, {"name": "8-inch DI pipe, class 52"})]),
    ("a line's unit", _set(X.ITEM2, lambda ws: _row(ws, 34), "C", "EA"),
     [("resource.update", 34, {"unit": "EA"})]),
    ("a line's quantity",_set(X.ITEM2, lambda ws: _row(ws, 34), "B", 650),
     [("resource.update", 34, {"quantity": Decimal(650)})]),
    ("a line's price", _set(X.ITEM2, lambda ws: _row(ws, 34), "G", 44),
     [("resource.update", 34, {"unit_cost": Decimal(44)})]),
    ("a line's type", _set(X.ITEM2, lambda ws: _row(ws, 34), "H", "Subcontract"),
     [("resource.update", 34, {"component_type": "subcontractor"})]),
    ("a line's source", _set(X.ITEM2, lambda ws: _row(ws, 34), "I", "PLUG"),
     [("resource.update", 34, {"description": "PLUG · Pipe Vendor A"})]),
    ("a line's vendor cleared", _set(X.ITEM2, lambda ws: _row(ws, 34), "J", None),
     [("resource.update", 34, {"description": "QUOTE"})]),
]


def _norm(fields):
    out = {}
    for k, v in fields.items():
        try:
            out[k] = Decimal(v) if isinstance(v, str) and k not in (
                "name", "description", "time_unit", "component_type") else v
        except ArithmeticError:
            out[k] = v
    return out


@pytest.mark.parametrize("what, edit, expected", EDITS, ids=[e[0] for e in EDITS])
def test_each_bound_input_edited_is_one_update_of_its_field(what, edit, expected, tmp_path):
    golden = X.book(tmp_path)
    wb = load_workbook(golden)
    edit(wb)
    path = tmp_path / "edited.xlsx"
    wb.save(path)
    change_set, problems = _run(path)
    assert problems == [], what
    assert [(op["op"], op["ref"], _norm(op["fields"])) for op in change_set.ops] == expected
    base = {a["id"]: a["v"] for a in X.payload()["activities"]}
    base.update({r["id"]: r["v"] for r in X.payload()["resources"]})
    assert [op["v"] for op in change_set.ops] == [base[op["ref"]] for op in change_set.ops]
