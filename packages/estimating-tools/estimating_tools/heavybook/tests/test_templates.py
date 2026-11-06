"""Estimate Navigator's ``_templates`` sheet and ``hc.tpl.*`` names (#1486
sub-project 4): each prototype is a real row of its kind, blank."""
from __future__ import annotations

import pytest
from openpyxl.formula.translate import Translator

from estimating_tools.heavybook import build, layout, style
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.columns import CR, CW
from estimating_tools.exchange.reader import fields as RF
from estimating_tools.heavybook.sheets.templates import SHEET
from estimating_tools.heavybook.tests import _readback as H


def _inputs(sheet, kind, *, stepped=False):
    """The inputs the reader reads on HeavyBook's own declaration."""
    return RF.inputs_for_decl(hb_pack.pack().declaration(), sheet, kind, stepped=stepped)

KINDS = {
    "hc.tpl.activity": ("ACTIVITY", "START", "RESOURCE", "END"),
    "hc.tpl.stepped": ("ACTIVITY", "STEPS", "STEP", "START", "RESOURCE", "END"),
    "hc.tpl.resource": ("RESOURCE",),
    "hc.tpl.step": ("STEP",),
}


def _build(doc):
    return build.build(doc, style=style.load_style(), exported_at="2026-10-20T09:00:00Z",
                       host="www.bidsheet.ai")


def test_the_sheet_is_hidden_and_last(book):
    assert book.sheetnames[-1] == SHEET
    assert book[SHEET].sheet_state == "hidden"


def test_the_names_cover_the_prototype_rows(book):
    assert {n for n in book.defined_names if n.startswith("hc.tpl.")} == set(
        layout.TEMPLATE_NAMES.values())
    names = {n: book.defined_names[n].attr_text for n in layout.TEMPLATE_NAMES.values()}
    assert names == {"hc.tpl.activity": "'_templates'!$5:$8",
                     "hc.tpl.stepped": "'_templates'!$9:$14",
                     "hc.tpl.resource": "'_templates'!$15:$15",
                     "hc.tpl.step": "'_templates'!$16:$16",
                     "hc.tpl.member": "'_templates'!$19:$19"}
    ws = book[SHEET]
    for name, kinds in KINDS.items():
        first, last = H.template_rows(book, name)
        assert tuple(ws[f"{CR.KIND}{r}"].value for r in range(first, last + 1)) == kinds
    first, last = H.template_rows(book, "hc.tpl.member")
    assert first == last and ws[f"{CW.KIND}{first}"].value == "MEMBER"


def test_the_header_row_is_the_cost_reports(book):
    ws, cr = book[SHEET], book["Cost Report"]
    for col in ("A", "B", CR.KIND, CR.ACT):
        assert ws[f"{col}{layout.HEADER_ROW}"].value == cr[f"{col}{layout.HEADER_ROW}"].value


def _rows(book, name):
    first, last = H.template_rows(book, name)
    return range(first, last + 1)


def test_prototypes_carry_no_id_or_v_a_chain_owner_tag_and_blank_inputs(book):
    """A prototype's owner tag is the chain formula of its own row (a step,
    resource, marker or member names the block it is pasted into); the
    prototype activity's own parent is blank (a root)."""
    ws = book[SHEET]
    for name, kinds in KINDS.items():
        stepped = name == "hc.tpl.stepped"
        for r, kind in zip(_rows(book, name), kinds):
            for col in (CR.ID, CR.V):
                assert ws[f"{col}{r}"].value is None, (name, kind, col)
            assert ws[f"{CR.PARENT}{r}"].value == (
                None if kind == "ACTIVITY" else H.owner_formula(r)), (name, kind)
            for inp in _inputs("cost_report", kind, stepped=stepped):
                assert ws[f"{inp.letter}{r}"].value is None, (name, kind, inp.letter)
    (r,) = _rows(book, "hc.tpl.member")
    for col in (CW.ID, CW.V, CW.RATE_ID, CW.EXPORT):
        assert ws[f"{col}{r}"].value is None, col
    assert ws[f"{CW.CREW}{r}"].value == H.crew_formula(r)
    for inp in _inputs("crews", "MEMBER"):
        assert ws[f"{inp.letter}{r}"].value is None, inp.letter


def _real_doc():
    """The fixture with resource 6 gone, so Prep (activity 4) is ACTIVITY,
    STEPS, one STEP, START, one RESOURCE, END -- the stepped prototype's
    shape -- as Fence (activity 7) is the plain one's."""
    doc = H.fixture_doc()
    doc["resources"] = [r for r in doc["resources"] if r["id"] != 6]
    return doc


def _formulas(ws, r, last_col):
    return {c: ws.cell(row=r, column=c).value for c in range(1, last_col + 1)
            if ws.cell(row=r, column=c).data_type == "f"}


def _assert_same_formulas(real_ws, real_rows, tpl_ws, tpl_rows):
    last_col = max(real_ws.max_column, tpl_ws.max_column)
    for src, dst in zip(real_rows, tpl_rows, strict=True):
        real, tpl = _formulas(real_ws, src, last_col), _formulas(tpl_ws, dst, last_col)
        assert set(real) == set(tpl), (src, dst)
        for col, formula in real.items():
            origin = real_ws.cell(row=src, column=col).coordinate
            moved = Translator(formula, origin=origin).translate_formula(
                tpl_ws.cell(row=dst, column=col).coordinate)
            assert tpl[col] == moved, (src, dst, col)


@pytest.mark.parametrize("name, first, last", [
    ("hc.tpl.activity", ("ACTIVITY", 7), ("END", 7)),
    ("hc.tpl.stepped", ("ACTIVITY", 4), ("END", 4)),
    ("hc.tpl.resource", ("RESOURCE", 8), ("RESOURCE", 8)),
    ("hc.tpl.step", ("STEP", 1), ("STEP", 1)),
])
def test_each_prototype_has_a_real_rows_formulas(name, first, last):
    book = _build(_real_doc())
    cr, tpl = book["Cost Report"], book[SHEET]
    top = H.cr_row(cr, first[0], first[1])
    bottom = (H.cr_row(cr, "END", parent=last[1], start=top) if last[0] == "END"
              else H.cr_row(cr, last[0], last[1]))
    _assert_same_formulas(cr, range(top, bottom + 1), tpl, _rows(book, name))


def test_the_member_prototype_has_a_real_members_formulas(book):
    real = H.cw_row(book["Crews"], "MEMBER", 1)
    _assert_same_formulas(book["Crews"], [real], book[SHEET], _rows(book, "hc.tpl.member"))


def test_prototype_inputs_are_styled_and_validated_as_real_rows(book):
    ws = book[SHEET]
    input_fill = "FF" + style.load_style().tokens["fills"]["input"]
    (res,) = _rows(book, "hc.tpl.resource")
    for col in (CR.DESC, CR.QTY, CR.UCOST, CR.TYPE):
        assert ws[f"{col}{res}"].fill.fgColor.rgb == input_fill, col
    assert ws[f"{CR.TOTAL}{res}"].fill.fgColor.rgb != input_fill
    lists = {dv.formula1: dv.sqref for dv in ws.data_validations.dataValidation}
    (step,) = _rows(book, "hc.tpl.step")
    assert f"{CR.TYPE}{res}" in lists['"labor,equipment,material,subcontractor,other"']
    assert f"{CR.UNIT}{step}" in lists['"DAYS,HOURS"']


def test_the_templates_sheet_is_never_read(tmp_path):
    """Read-back reads only the declaration's sheets: a scribbled-over ``_templates``
    (formulas overwritten, a row of an unknown kind) changes nothing."""
    path = H.build_book(H.fixture_doc(), tmp_path / "book.xlsx")
    wb = H.open_book(path)
    ws = wb[SHEET]
    first, last = H.template_rows(wb, "hc.tpl.activity")
    for r in range(first, last + 1):
        for col in (CR.MH, CR.TOTAL, CR.ACT):
            ws[f"{col}{r}"] = 1
    ws[f"{CR.KIND}{last + 30}"] = "NOT_A_KIND"
    ws[f"{CR.DESC}{last + 30}"] = "stray"
    H.save_book(wb, path)
    cs = H.read(path)
    assert cs.ops == [] and cs.notes == []


def test_a_blank_payload_is_blank_but_still_an_ordinary_object():
    import copy

    from estimating_tools.heavybook.sheets.templates import _Blank

    blank = _Blank(steps=[])
    assert blank.id is None and blank.steps == []
    assert not hasattr(blank, "__deepcopy__")
    assert copy.deepcopy(blank).steps == []


def test_every_prototype_row_reads_as_untouched(book):
    """Read-back's "nothing typed" test (``scan.untouched_row``) holds on every
    prototype row as the writers leave it -- pins ``WRITTEN_TEXT`` and the
    marker cues to what the writers put there."""
    from estimating_tools.exchange.reader.scan import untouched_row
    from estimating_tools.heavybook.sheets.templates import _declaration

    ws, decl = book[SHEET], _declaration()
    for name in layout.TEMPLATE_NAMES.values():
        sheet, kind_col = (("crews", CW.KIND) if name == "hc.tpl.member"
                           else ("cost_report", CR.KIND))
        for r in _rows(book, name):
            assert untouched_row(decl, ws, r, sheet, ws[f"{kind_col}{r}"].value), (name, r)
