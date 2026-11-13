"""Display blocks and regions: an object's prototype rows, its children
repeated, its variant, several regions on one sheet filled bottom-up -- and
the loader's and the lint's refusals."""
from __future__ import annotations

import copy

import pytest
import yaml
from openpyxl import load_workbook

from estimating_tools.exchange import declaration as D
from estimating_tools.exchange import display
from estimating_tools.exchange import model
from estimating_tools.exchange.fill import lint as L
from estimating_tools.exchange.fill.plan import regions
from estimating_tools.exchange.template import TemplatePack
from estimating_tools.exchange.tests import _template as T
from estimating_tools.heavybook.tests import _readback as H

AT = "2026-11-06T09:00:00Z"


def _packed(tmp_path, declaration=None, edit=None):
    d = T.make(tmp_path / "pack", declaration=declaration, edit=edit)
    decl = D.load(yaml.safe_load((d / "pack.yaml").read_text(encoding="utf-8")))
    return d, decl, L.check(d / "template.xlsx", decl)


def test_an_activity_is_its_lines_and_a_crew_activity_adds_its_charge(tmp_path):
    _d, decl, found = _packed(tmp_path)
    wb = model.parse(H.edge_doc())
    (at1, lines), (at2, warnings) = regions(decl, "lines", wb, found.protos)
    assert (at1, at2) == (2, 4)
    by_activity = [(r.kind, r.ident) for r in lines]
    # Activity 1 (crew 1): its charge, then its one resource line; 2 (no
    # crew): its two resources' lines; 3: its one.
    assert by_activity[:5] == [("CHARGE", 1), ("RESOURCE", 1), ("RESOURCE", 2),
                               ("RESOURCE", 3), ("RESOURCE", 4)]
    assert [(r.kind, r.ident) for r in warnings] == [
        ("WARNING", display.warning_ident(5, "No production rate"))]


def test_regions_fill_bottom_up_and_rows_land_where_planned(tmp_path):
    d, _decl, _found = _packed(tmp_path)
    book = tmp_path / "book.xlsx"
    TemplatePack(d).build(H.edge_doc(), book, options={"exported_at": AT})
    ws = load_workbook(book)[T.LINES]
    kinds = [ws[f"F{r}"].value for r in range(2, ws.max_row + 1)]
    n = kinds.index(None)                         # the first region's sentinel
    assert kinds[:2] == ["CHARGE", "RESOURCE"] and ws[f"A{n + 3}"].value == "Warnings"
    assert ws[f"F{n + 4}"].value == "WARNING" and ws[f"B{n + 4}"].value == "No production rate"
    wb = model.parse(H.edge_doc())
    a = wb.activity(1)
    # The charge row's labels: its activity's code, its crew's name.
    assert (ws["A2"].value or None, ws["B2"].value) == (a.code or None, wb.crew(a.crew_id).name)


@pytest.mark.parametrize("change, says", [
    (lambda s: s["lines"].update(regions=[{"at": 4, "rows": ["WARNING"]},
                                          {"at": 2, "rows": ["ACTIVITY"]}]),
     "each at a later row than the one before"),
    (lambda s: s["lines"]["regions"][0].update(rows=["NOPE"]), "NOPE is not a display source"),
    (lambda s: s["lines"]["prototypes"].update({"ACTIVITY.gold": "x"}),
     "gold is not a variant of ACTIVITY"),
    (lambda s: s["lines"]["prototypes"].update({"CREW": "x"}), "CREW is in no region"),
    (lambda s: s["lines"].pop("regions"), "a display sheet names its regions"),
    (lambda s: s["estimate"].update(regions=[{"at": 4, "rows": ["ITEM"]}]),
     "a blocks sheet fills from first_row"),
])
def test_the_loader_refuses_a_region_or_prototype_it_cannot_fill(change, says):
    doc = copy.deepcopy(T.DECLARATION)
    change(doc["sheets"])
    with pytest.raises(D.DeclarationError, match=says):
        D.load(doc)


def test_the_lint_checks_display_labels_against_their_rows(tmp_path):
    doc = copy.deepcopy(T.DECLARATION)
    doc["sheets"]["lines"]["labels"]["RESOURCE"]["D"] = "activity.colour"
    doc["sheets"]["lines"]["labels"]["GHOST"] = {"A": "name"}
    with pytest.raises(L.LintError) as exc:
        _packed(tmp_path, declaration=doc)
    assert exc.value.problems == [
        "sheets.lines.labels.GHOST: no prototype of this sheet has GHOST rows",
        "sheets.lines.labels.RESOURCE.D: activity.colour: Activity has no colour"]


def test_a_region_row_the_template_fills_must_be_blank(tmp_path):
    with pytest.raises(L.LintError, match=r"Lines!A4: the fill inserts above this row"):
        _packed(tmp_path, edit=lambda wb: wb[T.LINES].__setitem__("A4", "x"))


def _proto_row(wb, name):
    return int(str(wb.defined_names[name].attr_text).rsplit("$", 1)[1])


def test_a_display_row_reads_the_rows_above_from_the_row_over_its_region(tmp_path):
    def edit(wb):
        tpl = wb[T.PROTO]
        r = _proto_row(wb, "mb.fill.warning")
        tpl[f"H{r}"] = f"=COUNT(C$3:C{r - 1})"       # Lines!3, the row over the warnings

    d, _decl, _found = _packed(tmp_path, edit=edit)
    book = tmp_path / "book.xlsx"
    TemplatePack(d).build(H.edge_doc(), book, options={"exported_at": AT})
    ws = load_workbook(book)[T.LINES]
    kinds = [ws[f"F{r}"].value for r in range(2, ws.max_row + 1)]
    n = kinds.index(None)
    # The rows above start at the heading over the warnings, wherever the
    # inserts above it moved it.
    assert ws[f"H{n + 4}"].value == f"=COUNT(C${n + 3}:C{n + 3})"


def test_the_rows_above_start_at_the_header_or_the_row_over_the_region(tmp_path):
    def edit(wb):
        r = _proto_row(wb, "mb.fill.warning")
        wb[T.PROTO][f"H{r}"] = f"=COUNT(C$2:C{r - 1})"

    with pytest.raises(L.LintError, match=r"C\$2:C\d+ is a fixed row of a sheet the fill "
                                          "expands"):
        _packed(tmp_path, edit=edit)


def test_a_display_prototypes_id_tag_is_the_fills(tmp_path):
    def edit(wb):
        wb[T.PROTO][f"G{_proto_row(wb, 'mb.fill.warning')}"] = 7

    with pytest.raises(L.LintError, match="G is the id tag -- leave it blank"):
        _packed(tmp_path, edit=edit)


def test_a_display_label_on_a_tag_column_is_refused():
    doc = copy.deepcopy(T.DECLARATION)
    doc["sheets"]["lines"]["labels"]["WARNING"]["G"] = "text"
    with pytest.raises(D.DeclarationError, match="labels.WARNING.G: G is a tag column"):
        D.load(doc)


def test_two_blocks_sheets_cannot_share_a_prototype_name(tmp_path):
    doc = copy.deepcopy(T.DECLARATION)
    doc["sheets"]["again"] = dict(copy.deepcopy(doc["sheets"]["estimate"]), tab="Again")
    with pytest.raises(L.LintError) as exc:
        _packed(tmp_path, declaration=doc)
    assert ("prototypes.activity: sheets.estimate and sheets.again both need the activity "
            "prototype -- lay one of them out on a display sheet, whose prototypes are its "
            "own") in exc.value.problems


def test_a_row_kind_shows_one_class_on_a_sheet(tmp_path):
    doc = copy.deepcopy(T.DECLARATION)
    doc["sheets"]["lines"]["prototypes"]["WARNING"] = "mb.fill.lines"   # RESOURCE rows
    with pytest.raises(L.LintError, match="its RESOURCE rows show Warning objects; another "
                                          "prototype's show Resource"):
        _packed(tmp_path, declaration=doc)


def test_each_crew_is_its_block_and_a_library_crew_carries_its_banner(tmp_path):
    from estimating_tools.exchange.reader import read_book

    d, decl, found = _packed(tmp_path)
    wb = model.parse(H.fixture_doc())
    ((at, rows),) = regions(decl, "crews", wb, found.protos)
    assert [(r.kind, getattr(r.obj, "id", None)) for r in rows] == [
        ("CREW", 1), ("MEMBER", 1), ("MEMBER", 2), ("CREW_END", None),
        ("CREW", 2), ("NOTE", None), ("MEMBER", 3), ("CREW_END", None)]
    book = tmp_path / "book.xlsx"
    TemplatePack(d).build(H.fixture_doc(), book, options={"exported_at": AT})
    assert read_book(book).ops == []
    ws = load_workbook(book)[T.CREWS]
    assert ws["I4"].value == "=SUM(C4:C7)" and ws["R9"].value.startswith('=IF(K9="CREW"')


def test_a_member_edited_in_a_filled_crew_reads_as_its_update(tmp_path):
    from estimating_tools.exchange.reader import read_book

    d, _decl, _found = _packed(tmp_path)
    book = tmp_path / "book.xlsx"
    TemplatePack(d).build(H.fixture_doc(), book, options={"exported_at": AT})
    wb = load_workbook(book)
    ws = wb[T.CREWS]
    assert (ws["K10"].value, ws["L10"].value) == ("MEMBER", 3)
    ws["C10"] = 4
    wb.save(book)
    (op,) = read_book(book).ops
    assert (op["op"], op["ref"]) == ("crew.update_members", 2)
    assert [m["count"] for m in op["fields"]["members"]] == ["4"]


def test_a_flat_sheet_fills_its_lines_totals_and_named_rows(tmp_path):
    from estimating_tools.exchange.reader import read_book

    d, _decl, _found = _packed(tmp_path)
    book = tmp_path / "book.xlsx"
    TemplatePack(d).build(H.fixture_doc(), book, options={"exported_at": AT})
    ws = load_workbook(book)[T.BID]
    kinds = [ws[f"J{r}"].value for r in range(7, ws.max_row + 1)]
    # One section with its items, the group, the rest; the sentinel; the
    # heading; the two bid totals.
    assert kinds[:7] == ["SECTION", "ITEM_BID", "ITEM_BID", "GROUP", "ITEM_BID", "ITEM_BID",
                         "ITEM_BID"]
    assert kinds[7:11] == [None, None, "BID_TOTAL", "BID_TOTAL"]
    assert (ws["C2"].value, ws["K2"].value) == (10, 1)       # markup %, the estimate's id
    assert read_book(book).ops == []


def test_a_rates_sheet_is_its_sections_and_reads_back_clean(tmp_path):
    from estimating_tools.exchange.reader import read_book

    d, _decl, _found = _packed(tmp_path)
    book = tmp_path / "book.xlsx"
    TemplatePack(d).build(H.linked_doc(), book, options={"exported_at": AT})
    ws = load_workbook(book)[T.RATES]
    col = [(ws[f"A{r}"].value, ws[f"E{r}"].value) for r in range(1, 12)]
    assert col[:3] == [("Labor rates", None), ("Id", None), (1, "labor:1")]
    assert ("Equipment rates", None) in col and (7, "equipment:7") in col
    assert read_book(book).ops == []


def test_a_rate_change_refreshes_its_own_kinds_row(tmp_path):
    # Labor rate 1 and material rate 1 share an id: a refresh finds each
    # rate's row by its kind and id.
    d, _decl, _found = _packed(tmp_path)
    book = tmp_path / "book.xlsx"
    pack = TemplatePack(d)
    pack.build(H.linked_doc(), book, options={"exported_at": AT})
    fresh = H.linked_doc()
    fresh["rates"]["material"][0]["cost"] = "120.00"
    report = pack.refresh(book, fresh)
    assert report.clean, report
    ws = load_workbook(book)[T.RATES]
    rows = {ws[f"E{r}"].value: r for r in range(1, ws.max_row + 1) if ws[f"E{r}"].value}
    assert ws[f"D{rows['material:1']}"].value == 120
    assert ws[f"D{rows['labor:1']}"].value == 54


@pytest.mark.parametrize("change, says", [
    (lambda r: r["labels"]["RATE"].update(A="name", B="id"),
     r"labels.RATE.A: the reader reads the rate's id in A \(columns_by_key.id\)"),
    (lambda r: r["labels"]["RATE"].pop("D"),
     r"labels.RATE.D: the reader reads the rate's rate in D"),
    (lambda r: r["labels"].update(RATE_TITLE={"B": "title"}),
     r"labels.RATE_TITLE: the reader reads a section's title in A"),
    (lambda r: r["tags"].update(id="C"), r"labels.RATE.C: C is a tag column"),
])
def test_a_rates_sheet_fills_the_columns_its_reader_reads(change, says):
    doc = copy.deepcopy(T.DECLARATION)
    change(doc["sheets"]["rates"])
    with pytest.raises(D.DeclarationError, match=says):
        D.load(doc)


# -- the review of Tasks 16-18 ---------------------------------------------------

def test_a_later_region_cannot_read_an_earlier_one_from_the_header(tmp_path):
    def edit(wb):
        r = _proto_row(wb, "mb.fill.warning")
        wb[T.PROTO][f"H{r}"] = f"=COUNT(C$1:C{r - 1})"      # over the ACTIVITY region too

    with pytest.raises(L.LintError, match=r"C\$1:C\d+ is a fixed row of a sheet the fill "
                                          "expands"):
        _packed(tmp_path, edit=edit)


def test_a_header_cell_sits_above_the_first_region():
    doc = copy.deepcopy(T.DECLARATION)
    doc["sheets"]["lines"].update(first_row=5, header={"B3": "estimate.name"})
    with pytest.raises(D.DeclarationError, match=r"lines.header.B3: a header cell sits above "
                                                 r"the first region \(2\)"):
        D.load(doc)


def test_a_prototype_above_its_regions_start_is_told_to_move_below_it(tmp_path):
    doc = copy.deepcopy(T.DECLARATION)
    doc["sheets"]["lines"]["regions"][1]["at"] = 60

    def edit(wb):
        r = _proto_row(wb, "mb.fill.warning")
        wb[T.PROTO][f"H{r}"] = f"=COUNT(C$59:C{r - 1})"

    with pytest.raises(L.LintError, match=r"starts at row 59, at or below this prototype's row "
                                          r"\d+ -- put the prototype below row 59"):
        _packed(tmp_path, declaration=doc, edit=edit)


def test_a_crew_activity_reads_its_crew_on_the_crews_sheet_live(tmp_path):
    from estimating_tools.xlcalc import cache_values

    d, _decl, _found = _packed(tmp_path)
    book = tmp_path / "book.xlsx"
    TemplatePack(d).build(H.fixture_doc(), book, options={"exported_at": AT})

    def heads():
        cache_values(book)
        ws = load_workbook(book, data_only=True)[T.TAB]
        row = next(r for r in range(T.FIRST, ws.max_row + 1)
                   if ws[f"{T.KIND}{r}"].value == "ACTIVITY" and ws[f"{T.ID}{r}"].value == 6)
        return ws[f"{T.CREW_HEADS}{row}"].value
    assert heads() == 3                                   # crew 2: member 3, count 3
    wb = load_workbook(book)
    ws = wb[T.CREWS]
    row = next(r for r in range(4, ws.max_row + 1)
               if ws[f"K{r}"].value == "MEMBER" and ws[f"L{r}"].value == 3)
    ws[f"C{row}"] = 5
    wb.save(book)
    assert heads() == 5
