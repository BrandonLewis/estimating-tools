"""The template lint (engine spec, Fill step 1, "Testing: Lint"): the test
pack's template is clean; each defect is refused naming the cell and the
formula, or -- what the fill does not copy from a prototype row -- listed as
dropped."""
from __future__ import annotations

import copy

import pytest
import yaml
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import PatternFill
from openpyxl.workbook.defined_name import DefinedName

from estimating_tools.exchange.declaration import load
from estimating_tools.exchange.fill import lint as L
from estimating_tools.exchange.tests import _template as T

#: The test pack's resource prototype row on ``_templates`` (``_template.make``).
RES = 17


def _lint(tmp_path, edit=None, declaration=None):
    d = T.make(tmp_path / "pack", edit=edit, declaration=declaration)
    decl = load(yaml.safe_load((d / "pack.yaml").read_text(encoding="utf-8")))
    return L.check(d / "template.xlsx", decl)


def _refused(tmp_path, edit=None, declaration=None):
    with pytest.raises(L.LintError) as exc:
        _lint(tmp_path, edit, declaration)
    return exc.value.problems


def _put(sheet, ref, value):
    def edit(wb):
        wb[sheet][ref] = value
    return edit


def test_the_test_packs_template_is_clean(tmp_path):
    found = _lint(tmp_path)
    assert found.dropped == [] and found.sheet == T.PROTO
    assert found.protos["stepped"].kinds == ("ACTIVITY", "STEPS", "STEP", "START", "RESOURCE",
                                             "END")
    assert found.protos["shares:SHARE"].kinds == ("SHARE",)


@pytest.mark.parametrize("formula, says", [
    (f"=C{RES}*E{RES}+C4", f"C4 reads another row -- a prototype row reads its own row"),
    (f"=C{RES}*$E${RES}", f"$E${RES} is a fixed row of a sheet the fill expands"),
    (f'=INDIRECT("C{RES}")*E{RES}', "INDIRECT -- the lint cannot follow"),
    (f"=OFFSET(C{RES},0,2)", "OFFSET -- the lint cannot follow"),
    (f"=C{RES}*'Shares'!E2", "'Shares'!E2 is a fixed row of a sheet the fill expands"),
    (f"=C{RES}*'_templates'!E{RES}", "reads the prototype sheet"),
    (f"=C{RES}*'[1]Other'!A1", "reads another workbook"),
    (f"=SUM(Jan:Mar!A{RES})", "is a 3-D reference"),
])
def test_a_formula_the_fill_cannot_move_is_refused(tmp_path, formula, says):
    problems = _refused(tmp_path, _put(T.PROTO, f"F{RES}", formula))
    assert problems == [f"{T.PROTO}!F{RES}: {formula}: {problems[0].split(': ', 2)[2]}"]
    assert says in problems[0]


def test_an_owner_row_may_read_its_brackets_but_not_its_sample_row(tmp_path):
    problems = _refused(tmp_path, _put(T.PROTO, "F7", "=SUM(F8:F10)*P7+F9"))
    assert problems == [f"{T.PROTO}!F7: =SUM(F8:F10)*P7+F9: F9 reads another row -- a "
                        "prototype row reads its own row, and its block's owner and marker rows"]


def test_whole_columns_names_and_sheets_the_fill_does_not_expand_are_read_freely(tmp_path):
    def edit(wb):
        markup = wb.create_sheet("Markup")
        markup["B3"] = 5
        wb[T.PROTO][f"F{RES}"] = f"=C{RES}*E{RES}*Markup!$B$3+SUM('Shares'!$E:$E)*0"
    assert _lint(tmp_path, edit).dropped == []


@pytest.mark.parametrize("edit, says", [
    (_put(T.PROTO, f"C{RES}", 3), f"{T.PROTO} row {RES} (resource prototype resource): C is "
                                  "the quantity input -- leave it blank"),
    (_put(T.PROTO, f"H{RES}", 9), "H is a stored tag -- leave it blank"),
    (_put(T.PROTO, f"J{RES}", 5), "J is a derived tag -- it needs its chain formula"),
    (_put(T.PROTO, f"M{RES}", "=ROW()"), "M is the owner-row helper the engine writes"),
    # Even the helper's own formula: the fill writes the cell, and the
    # writer never overwrites a formula.
    (_put(T.PROTO, f"M{RES}", T._owner_row(RES)), "M is the owner-row helper the engine "
                                                  "writes -- leave it blank"),
    (_put(T.PROTO, "N7", 4), "N is an export value or label -- leave it blank"),
    (_put(T.PROTO, "G9", "STEP"), "mb.tpl.activity (_templates rows 7-10) holds ACTIVITY, "
                                  "START, STEP, END in its kind column; the fill needs "
                                  "ACTIVITY, START, RESOURCE, END"),
    (_put(T.TAB, "B9", "leftover"), f"{T.TAB}!B9: the fill owns the rows from 4 down"),
    (_put(T.TAB, "A2", "a title"), f"{T.TAB}!A2: a header cell the fill writes"),
    (lambda wb: setattr(wb[T.TAB].column_dimensions["H"], "hidden", False),
     f"{T.TAB} column H holds the id tag and must be hidden"),
    (lambda wb: wb.remove(wb["_wb"]), "the template has no _wb sheet"),
    (lambda wb: setattr(wb["_wb"], "sheet_state", "visible"), "the _wb sheet must be hidden"),
])
def test_a_template_defect_is_named(tmp_path, edit, says):
    problems = _refused(tmp_path, edit)
    assert any(says in p for p in problems), problems


def test_a_missing_or_misplaced_prototype_is_refused(tmp_path):
    doc = copy.deepcopy(T.DECLARATION)
    del doc["prototypes"]["stepped"]
    assert _refused(tmp_path / "a", declaration=doc) == [
        "prototypes.stepped: the fill needs a stepped prototype (sheets.estimate)"]
    doc = copy.deepcopy(T.DECLARATION)
    doc["prototypes"]["group"] = "mb.nowhere"
    assert _refused(tmp_path / "b", declaration=doc) == [
        "prototypes.group: no defined name mb.nowhere over whole rows in the template"]


def _group_on(title, chart=False):
    """The group prototype's name pointed at rows of ``title`` (a chart sheet
    when ``chart``; openpyxl reads a chart sheet back only with a chart)."""
    def edit(wb):
        if chart:
            cs = wb.create_chartsheet(title)
            bars = BarChart()
            bars.add_data(Reference(wb[T.TAB], min_col=6, min_row=1, max_row=2))
            cs.add_chart(bars)
        wb.defined_names["mb.tpl.group"] = DefinedName("mb.tpl.group",
                                                       attr_text=f"'{title}'!$6:$6")
    return edit


@pytest.mark.parametrize("edit, says", [
    (_group_on("Gone"), "prototypes.group: mb.tpl.group ('Gone'!$6:$6) is on a sheet the "
                        "template does not have"),
    (_group_on("Chart", chart=True), "prototypes.group: mb.tpl.group ('Chart'!$6:$6) is on a "
                                     "chart sheet -- prototypes are rows of a worksheet"),
])
def test_a_prototype_off_every_worksheet_is_named_not_a_crash(tmp_path, edit, says):
    assert _refused(tmp_path, edit) == [says]


def test_a_flat_or_rates_sheet_without_regions_is_refused(tmp_path):
    doc = copy.deepcopy(T.DECLARATION)
    for key in ("regions", "prototypes", "labels"):
        doc["sheets"]["rates"].pop(key)
    problems = _refused(tmp_path, declaration=doc)
    assert problems == ["sheets.rates: a rates sheet the fill lays out names its regions"]


def test_a_named_row_the_template_lacks_is_refused(tmp_path):
    problems = _refused(tmp_path, lambda wb: wb[T.BID].__setitem__("T4", None))
    assert problems == ["sheets.bid.named_rows.indirect_cost: the template holds it 0 times "
                        "above row 7 (in T); it needs it once"]


def test_what_the_fill_does_not_copy_from_a_prototype_row_is_listed(tmp_path):
    def edit(wb):
        ws = wb[T.PROTO]
        ws[f"B{RES}"].comment = Comment("a hint", "author")
        ws.merge_cells(f"D{RES}:E{RES}")
        ws.conditional_formatting.add(f"F{RES}", CellIsRule(
            operator="lessThan", formula=["0"], fill=PatternFill("solid", fgColor="FF0000")))
    assert sorted(_lint(tmp_path, edit).dropped) == [
        f"{T.PROTO}!B{RES}: a note on a prototype row",
        f"{T.PROTO}!D{RES}:E{RES}: merged cells on a prototype row",
        f"{T.PROTO}!F{RES}: a conditional format on a prototype row"]


def test_a_navigator_name_the_template_lacks_is_refused(tmp_path):
    doc = copy.deepcopy(T.DECLARATION)
    doc["navigator"] = {"cells": {"total": "mb.total"}}
    assert _refused(tmp_path, declaration=doc) == [
        "navigator.cells.total: no defined name mb.total in the template"]


@pytest.mark.parametrize("ref", ["Markup!B2", "Markup!$B2", "Markup!B2:B$3", "Markup!2:2"])
def test_a_relative_row_of_a_sheet_the_fill_does_not_expand_is_refused(tmp_path, ref):
    """A copied prototype row moves a relative row of any sheet: placed at
    row 40, ``Markup!B2`` would read ``Markup!B25``."""
    formula = f"=C{RES}*E{RES}*SUM({ref})"

    def edit(wb):
        wb.create_sheet("Markup")["B2"] = 1.1
        wb[T.PROTO][f"F{RES}"] = formula
    problems = _refused(tmp_path, edit)
    assert problems == [f"{T.PROTO}!F{RES}: {formula}: {ref} is a relative row of a sheet the "
                        "fill does not expand -- a copied row would read another row; anchor "
                        "the row with $"]


def test_an_anchored_row_of_a_sheet_the_fill_does_not_expand_is_read(tmp_path):
    def edit(wb):
        wb.create_sheet("Markup")["B2"] = 1.1
        wb[T.PROTO][f"F{RES}"] = f"=C{RES}*E{RES}*Markup!B$2*SUM(Markup!$2:$3)*Markup!B:B*Rate"
    assert _lint(tmp_path, edit).dropped == []


@pytest.mark.parametrize("row", [1, T.HEADER])
def test_a_blocks_prototype_at_or_above_the_header_row_is_refused(tmp_path, row):
    """The owner-row helper on a prototype row reads the rows above it from
    the blocks sheet's header row (``MAX(M$3:M<r-1>)``): at row 1 that is
    ``M$3:M0``, at or above the header a range over its own cell. A patch
    or refresh inserts from the prototype rows themselves, so the helper
    must be the rows-above form there."""
    def edit(wb):
        wb[T.PROTO][f"{T.KIND}{row}"] = "ITEM"
        wb.defined_names["mb.tpl.item"] = DefinedName(
            "mb.tpl.item", attr_text=f"'{T.PROTO}'!${row}:${row}")
    problems = _refused(tmp_path, edit)
    assert problems == [f"prototypes.item: mb.tpl.item ({T.PROTO} rows {row}-{row}) starts at "
                        f"or above Estimate's header row {T.HEADER} -- the owner-row helper "
                        f"reads the rows above from there; put the prototype below row "
                        f"{T.HEADER}"]
