"""Sub-project 3 reads edits back by these cells; pin them."""
from __future__ import annotations

from estimating_tools.heavycivil import layout, model, style
from estimating_tools.heavycivil.columns import BF, CR, CW


def test_hidden_id_and_v_match_the_payload(doc, book):
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    ws = book["Cost Report"]
    for row in plan.cost_report:
        assert ws[f"{CR.KIND}{row.row}"].value == row.kind
        if row.kind in ("ITEM", "ACTIVITY", "RESOURCE", "STEP", "ELEMENT_QTY"):
            assert ws[f"{CR.ID}{row.row}"].value == row.id
            assert ws[f"{CR.V}{row.row}"].value == row.v
    crews = book["Crews"]
    for crew in wb.crews:
        r = plan.crew_rows[crew.id].row
        assert crews[f"{CW.ID}{r}"].value == crew.id and crews[f"{CW.V}{r}"].value == crew.v


def test_inputs_carry_the_input_fill(doc, book):
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    input_fill = "FF" + style.load_style().tokens["fills"]["input"]
    ws = book["Cost Report"]
    res = plan.resource_rows[wb.resources[0].id].row
    for col in (CR.QTY, CR.UCOST, CR.TYPE):
        assert ws[f"{col}{res}"].fill.fgColor.rgb == input_fill
    assert ws[f"{CR.TOTAL}{res}"].fill.fgColor.rgb != input_fill


def test_outline_levels_follow_the_plan(doc, book):
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    ws = book["Cost Report"]
    for row in plan.cost_report:
        assert (ws.row_dimensions[row.row].outline_level or 0) == min(row.level, 7)


def test_end_rows_carry_kind_and_activity_but_no_id(doc, book):
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    ws = book["Cost Report"]
    for a in wb.activities:
        r = plan.end_rows[a.id].row
        assert ws[f"{CR.KIND}{r}"].value == "END"
        assert ws[f"{CR.PARENT}{r}"].value == a.id
        assert ws[f"{CR.ID}{r}"].value is None and ws[f"{CR.V}{r}"].value is None
        assert "insert" in ws[f"{CR.DESC}{r}"].value


def test_start_rows_are_blank_short_markers(doc, book):
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    ws = book["Cost Report"]
    for a in wb.activities:
        r = plan.start_rows[a.id].row
        assert ws[f"{CR.KIND}{r}"].value == "START"
        assert ws[f"{CR.PARENT}{r}"].value == a.id
        assert ws[f"{CR.ID}{r}"].value is None and ws[f"{CR.V}{r}"].value is None
        for col in (CR.QTY, CR.TYPE, CR.MH) + tuple(c for _, c in CR.SPLIT):
            assert ws[f"{col}{r}"].value is None
        assert ws.row_dimensions[r].height == 6


def test_activity_sums_reach_the_end_row(doc, book):
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    ws = book["Cost Report"]
    for a in wb.activities:
        r = plan.activity_rows[a.id].row
        start, end = plan.start_rows[a.id].row, plan.end_rows[a.id].row
        assert f"({CR.EQP}{start}:{CR.EQP}{end})" in ws[f"{CR.EQP}{r}"].value


def _validations(book):
    out = {}
    for dv in book["Cost Report"].data_validations.dataValidation:
        out[dv.formula1] = (dv, {str(r) for r in dv.sqref.ranges})
    return out


def _covers(ranges, coord):
    from openpyxl.worksheet.cell_range import CellRange
    return any(CellRange(coord) <= CellRange(r) for r in ranges)


def test_list_validations_cover_the_coded_inputs(doc, book):
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    dvs = _validations(book)
    types = dvs['"labor,equipment,material,subcontractor,other"']
    basis, flag = dvs['"production,flat"'], dvs['"Y,N"']
    units = dvs['"DAYS,HOURS"']
    for dv, _ in (types, basis, flag, units):
        assert dv.type == "list" and dv.allow_blank
    assert len(book["Cost Report"].data_validations.dataValidation) == 4
    for res in wb.resources:
        r = plan.resource_rows[res.id].row
        assert _covers(types[1], f"{CR.TYPE}{r}")
        assert _covers(basis[1], f"{CR.BASIS}{r}")
        assert _covers(flag[1], f"{CR.BINC}{r}")
        assert _covers(units[1], f"{CR.PUNIT}{r}")
    for a in wb.activities:
        assert _covers(units[1], f"{CR.PUNIT}{plan.activity_rows[a.id].row}")
        for s in a.steps:
            assert _covers(units[1], f"{CR.UNIT}{plan.step_rows[s.id].row}")
    for a in wb.activities:
        for marker in (plan.start_rows[a.id].row, plan.end_rows[a.id].row):
            for dv, col in ((types, CR.TYPE), (basis, CR.BASIS), (flag, CR.BINC),
                            (units, CR.PUNIT)):
                assert _covers(dv[1], f"{col}{marker}")
    item = plan.item_rows[wb.items[0].id].row
    assert not _covers(types[1], f"{CR.TYPE}{item}")


def test_crew_header_hours_and_factor_read_as_export_values(doc, book):
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    tokens = style.load_style().tokens
    ws = book["Crews"]
    for crew in wb.crews:
        r = plan.crew_rows[crew.id].row
        for col in (CW.HPS, CW.CFACT):
            assert ws[f"{col}{r}"].fill.fgColor.rgb == "FF" + tokens["fills"]["export"]
            assert ws[f"{col}{r}"].font.i


def test_bid_form_estimate_rows_carry_their_input_marker(doc, book):
    """Read-back finds each estimate input and figure by its hidden name
    (T) on a marked row (J), not by its address."""
    wb = model.parse(doc)
    ws = book["Bid Form"]
    for name, r in BF.ROWS.items():
        assert ws[f"{BF.INPUT}{r}"].value == name
        expected = ("ESTIMATE" if r == BF.ROWS["markup_percentage"]
                    else "BID_INPUT" if name in BF.INPUTS else "BID_FIGURE")
        assert ws[f"{BF.KIND}{r}"].value == expected
    r0 = BF.ROWS["markup_percentage"]
    assert ws[f"{BF.ID}{r0}"].value == wb.estimate.id
    assert ws[f"{BF.V}{r0}"].value == wb.estimate.v
    assert ws.column_dimensions[BF.INPUT].hidden
