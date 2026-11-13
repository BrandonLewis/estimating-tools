"""Fieldbook's book through the generic reader (delivery 1): the stamp's
declaration expands into one sheet per item, rows carry their form and
their contract kind, a task's notes are its joined rows and an item's scope
notes are the sheet's own; each binding reads what the build wrote; the
tagged Rates sheet is checked by its library rows only."""
from __future__ import annotations

import pytest

from estimating_tools.estimate_spec.pack import FieldbookPack
from estimating_tools.estimate_spec.tests import _exchange as X
from estimating_tools.exchange.reader import book as book_mod
from estimating_tools.exchange.reader import scan
from estimating_tools.exchange.reader.errors import Problems


@pytest.fixture(scope="module")
def golden(tmp_path_factory):
    return X.book(tmp_path_factory.mktemp("golden"))


def _scanned(path):
    book = book_mod.load(path, pack=FieldbookPack())
    problems = Problems()
    return book, scan.scan(book, problems), problems


def test_the_declaration_expands_into_one_sheet_per_item(golden):
    book = book_mod.load(golden, pack=FieldbookPack())
    assert [(k, s.tab) for k, s in book.decl.sheets.items()] == [
        ("items.1", X.ITEM1), ("items.2", X.ITEM2), ("rates", "Rates")]


def test_rows_carry_their_form_and_their_contract_kind(golden):
    _book, s, problems = _scanned(golden)
    assert problems.items == []
    lines = s.lines["items.2"]
    assert [(x.form, x.kind, x.id) for x in lines if x.kind == "RESOURCE"] == [
        ("CREW", "RESOURCE", 32), ("CREW", "RESOURCE", 33), ("LINE", "RESOURCE", 34),
        ("CREW", "RESOURCE", 35), ("LINE", "RESOURCE", 36)]
    assert [(o.id, o.item_id, o.line.form, o.line.parent) for o in s.activities] == [
        (21, 11, "TASK", None), (22, 12, "TASK", None), (23, 12, "TASK", None)]
    assert {x.at[0] for x in s.lines["items.1"]} == {0}
    assert {x.at[0] for x in lines} == {1}


def test_a_tasks_notes_are_its_joined_rows_and_an_items_are_its_own(golden):
    book, s, _problems = _scanned(golden)
    (mob,) = [o for o in s.activities if o.id == 21]
    ws = book.ws("items.1")
    assert [ws[f"A{x.row}"].value for x in mob.joined["NOTE"]] == [
        "Two days: yard load-out, haul", "Set up the yard"]
    scope = [x for x in s.lines["items.2"] if x.form == "NOTE"]
    assert len(scope) == 1 and scope[0].occ is None
    assert all(not o.joined for o in s.activities if o.id != 21)


from decimal import Decimal

from openpyxl import load_workbook

from estimating_tools.exchange.reader import fields as F
from estimating_tools.exchange.reader import rates


def _row(ws, ident):
    """The row whose hidden id (W) is ``ident``."""
    return next(r for r in range(1, ws.max_row + 1) if ws[f"W{r}"].value == ident)


def _lines_by_id(s):
    return {x.id: x for x in s.all_lines() if x.kind in ("ACTIVITY", "RESOURCE")}


def test_every_bound_input_reads_what_the_build_wrote(golden):
    book, s, _problems = _scanned(golden)
    lines = _lines_by_id(s)
    for a in book.model.activities:
        assert F.equal_to_base(book, lines[a.id], "ACTIVITY", a), a.name
    for res in book.model.resources:
        assert F.equal_to_base(book, lines[res.id], "RESOURCE", res), res.name


def test_each_form_reads_its_value(golden):
    book, s, _problems = _scanned(golden)
    lines = _lines_by_id(s)
    mob = F.read_line(book, lines[21], "ACTIVITY").values
    assert mob == {"name": "Mobilize crew and equipment",
                   "description": "Two days: yard load-out, haul\nSet up the yard",
                   "hours_per_shift": Decimal(8)}
    local = F.read_line(book, lines[35], "RESOURCE").values
    assert (local["name"], local["component_type"], local["unit_cost"]) == (
        "Laborer", "labor", Decimal(40))
    hours = F.read_line(book, lines[32], "RESOURCE").values
    assert (hours["time_value"], hours["time_unit"]) == (Decimal(16), "HOURS")
    assert F.read_line(book, lines[33], "RESOURCE").values["component_type"] == "equipment"
    sub = F.read_line(book, lines[36], "RESOURCE").values
    assert (sub["component_type"], sub["description"]) == ("subcontractor", "PLUG")
    assert F.read_line(book, lines[34], "RESOURCE").values["description"] == (
        "QUOTE · Pipe Vendor A")


def test_a_crew_row_whose_name_picks_no_rate_is_a_problem(golden, tmp_path):
    wb = load_workbook(golden)
    ws = wb[X.ITEM2]
    ws[f"A{_row(ws, 33)}"] = "Excavator, 330 class"
    path = tmp_path / "no-rate.xlsx"
    wb.save(path)
    book, s, _problems = _scanned(path)
    read = F.read_line(book, _lines_by_id(s)[33], "RESOURCE")
    assert {"component_type", "unit_cost"} <= read.bad
    assert any("no rate named 'Excavator, 330 class' on the Rates sheet" in p.message
               for p in read.problems)


def _rates_problems(path):
    book = book_mod.load(path, pack=FieldbookPack())
    problems = Problems()
    rates.check(book, problems)
    return problems.items


def test_the_rates_sheet_reads_clean(golden):
    assert _rates_problems(golden) == []


def test_a_library_rate_is_read_only_and_a_local_one_is_the_books(golden, tmp_path):
    wb = load_workbook(golden)
    ws = wb["Rates"]
    rows = {ws[f"A{r}"].value: r for r in range(1, ws.max_row + 1)}
    ws[f"G{rows['Pipelayer']}"] = 85
    ws[f"G{rows['Laborer (local)']}"] = 42
    path = tmp_path / "rates.xlsx"
    wb.save(path)
    (problem,) = _rates_problems(path)
    assert (problem.sheet, problem.row) == ("Rates", rows["Pipelayer"])
    assert "library rates are read-only -- add a local rate row instead" in problem.message


from estimating_tools.exchange import reader


def _edited(golden, tmp_path, edit, name="edited.xlsx"):
    wb = load_workbook(golden)
    edit(wb)
    path = tmp_path / name
    wb.save(path)
    return path


def _run(path):
    _book, _s, _changes, change_set, problems = reader.run(path, pack=FieldbookPack())
    return change_set, problems.items


def test_a_problem_names_the_sheet_its_row_is_on(golden, tmp_path):
    def foreign(wb):
        ws = wb[X.ITEM2]
        ws[f"W{_row(ws, 23)}"] = 999
    _cs, problems = _run(_edited(golden, tmp_path, foreign))
    assert [(p.sheet, p.message) for p in problems] == [
        (X.ITEM2, "only resource rows can be pasted in from another workbook")]


def test_a_deleted_row_names_its_items_sheet(golden, tmp_path):
    def delete(wb):
        ws = wb[X.ITEM2]
        ws.delete_rows(_row(ws, 36))
    change_set, problems = _run(_edited(golden, tmp_path, delete))
    assert problems == []
    assert [(op["op"], op["ref"]) for op in change_set.ops] == [("resource.delete", 36)]
    assert change_set.rows == [{"op_index": 0, "sheet": X.ITEM2, "row": None}]


def test_a_row_typed_into_a_task_block_is_refused(golden, tmp_path):
    def typed(wb):
        ws = wb[X.ITEM2]
        end = next(r for r in range(_row(ws, 33), ws.max_row + 1) if ws[f"Q{r}"].value == "END")
        ws.insert_rows(end)
        ws[f"A{end}"] = "Flagger"
        ws[f"D{end}"] = 2
    _cs, problems = _run(_edited(golden, tmp_path, typed))
    assert any(p.sheet == X.ITEM2 and "copy a crew or line row" in p.message
               for p in problems)


def test_a_crew_rows_cleared_name_is_one_problem(golden, tmp_path):
    def clear(wb):
        ws = wb[X.ITEM2]
        ws[f"A{_row(ws, 33)}"] = None
    _cs, problems = _run(_edited(golden, tmp_path, clear))
    assert len(problems) == 1, [p.message for p in problems]
    (problem,) = problems
    assert (problem.sheet, problem.column) == (X.ITEM2, "A")
    assert "can't be cleared" in problem.message


ITEM3 = "3 - HYDRANTS"


def _three_items(where):
    """The golden book with a third item (one task, one crew row)."""
    import copy

    from estimating_tools.estimate_spec import build as B
    from estimating_tools.estimate_spec import identity
    from estimating_tools.estimate_spec.tests._fieldbook import fieldbook_pack

    doc, config = X.payload(), X.config()
    doc["items"].append(copy.deepcopy(doc["items"][0]) | {
        "id": 13, "item_number": "3", "description": "Hydrants", "unit": "EA",
        "quantity": "4.00", "schedule_quantity": "4.00", "v": "a000000000000013"})
    doc["activities"].append(copy.deepcopy(doc["activities"][1]) | {
        "id": 24, "estimate_item_id": 13, "name": "Set hydrants",
        "activity_code": {"id": 94, "code": "03-100"}, "v": "b000000000000024"})
    doc["resources"].append(copy.deepcopy(doc["resources"][0]) | {
        "id": 37, "activity_id": 24, "time_value": "1", "v": "c000000000000037"})
    config["items"].append({
        "recipe": "lump_sum", "sheet": ITEM3, "item_no": "3", "description": "Hydrants",
        "qty": 4, "uom": "EA", "exchange": {"id": 13, "v": "a000000000000013"},
        "labor": [{"slot": "01", "cost_code": "03-100", "description": "Set hydrants",
                   "exchange": {"id": 24, "v": "b000000000000024"},
                   "crew": [{"trade": "Superintendent", "count": 1, "days": 1,
                             "exchange": {"id": 37, "v": "c000000000000037",
                                          "ref": "labor:1", "time_unit": "DAYS"}}]}]})
    base = identity.Baseline(payload=doc, host=X.HOST, exported_at=X.EXPORTED_AT)
    where.mkdir(parents=True, exist_ok=True)
    path = where / "three.xlsx"
    B.generate(config, fieldbook_pack(), exchange=base).save(path)
    return path


def _insert_blank_crew_row(ws, crew_id):
    """An inserted crew row left blank, under crew row ``crew_id``: its
    formulas and kind copied, its id, version, link and inputs cleared."""
    src = _row(ws, crew_id)
    ws.insert_rows(src + 1)
    for col in range(1, ws.max_column + 1):
        ws.cell(src + 1, col).value = ws.cell(src, col).value
    for letter in "ADEWXY":
        ws[f"{letter}{src + 1}"] = None
    return src + 1


def test_skipped_rows_are_noted_sheet_by_sheet_then_row(tmp_path):
    path = _three_items(tmp_path)
    wb = load_workbook(path)
    rows = {}
    # The second item's row low on its sheet, the third's near its top: a
    # sort by row alone would put the third sheet's note first.
    for tab, crew_id in ((X.ITEM2, 35), (ITEM3, 37), (X.ITEM1, 31)):
        rows[tab] = _insert_blank_crew_row(wb[tab], crew_id)
    assert rows[ITEM3] < rows[X.ITEM2]
    edited = tmp_path / "skipped.xlsx"
    wb.save(edited)
    book, _s, changes, change_set, problems = reader.run(edited, pack=FieldbookPack())
    assert problems.items == []
    assert change_set.ops == []
    assert [(book.tab(key), row) for key, row, _what in changes.skipped] == [
        (X.ITEM1, rows[X.ITEM1]), (X.ITEM2, rows[X.ITEM2]), (ITEM3, rows[ITEM3])]
    assert [n.split(": ")[1] for n in change_set.notes] == [
        "an empty inserted resource line was skipped"] * 3
