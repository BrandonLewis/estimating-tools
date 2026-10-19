"""The fieldbook pack: loads, validates, and lays out the workbook its spec describes.

Structure only -- what each cell holds, styles, tags, dropdowns. The numbers
those formulas compute are proven in test_fieldbook_eval.py.
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import pytest

from estimating_tools.estimate_spec import recipe as R
from estimating_tools.estimate_spec.scaffold import validate_spec
from estimating_tools.estimate_spec.tests._fieldbook import (
    CODE, FLAG, KIND, OK, build, example_spec, fieldbook_pack, rows_of_kind,
    simulate_insert_copied_row, task_block)

ITEM2 = "2 - 8IN MAIN"
ITEMS = ("1 - MOBILIZATION", ITEM2, "3 - VALVES")


@pytest.fixture(scope="module")
def wb():
    return build()


# ---------------------------------------------------------------- the pack

def test_the_pack_loads_and_promises_only_what_it_backs():
    pack = fieldbook_pack()
    assert (pack.name, pack.version) == ("fieldbook", "2")
    assert pack.supports == frozenset()       # never summarize, never artifact
    assert pack.protect == {}                 # copy-and-paste editing: no protection
    assert pack.vocabulary["markup_by_type"] == "required"   # a plain number markup is refused


def test_the_example_validates():
    validate_spec(example_spec(), pack=fieldbook_pack())


def test_every_task_needs_a_cost_code():
    spec = example_spec()
    del spec["items"][1]["labor"][0]["cost_code"]
    with pytest.raises(ValueError, match="cost_code"):
        validate_spec(spec, pack=fieldbook_pack())


def test_item_level_cost_blocks_are_refused():
    spec = example_spec()
    spec["items"][2]["cost_details"] = [
        {"name": "Material", "lines": [{"name": "x", "qty": 1, "unit_price": 1}]}]
    with pytest.raises(ValueError, match="False schema does not allow"):
        validate_spec(spec, pack=fieldbook_pack())


def test_a_burden_breakdown_that_misses_its_rate_fails_validation():
    spec = example_spec()
    spec["rate_table"][1]["fringe"] = 20.00           # 44 x 1.30 + 20 = 77.20, not 74.00
    with pytest.raises(ValueError, match="Pipelayer"):
        validate_spec(spec, pack=fieldbook_pack())


# ---------------------------------------------------------------- item sheets

def test_item_sheets_open_with_the_header_band(wb):
    ws = wb[ITEM2]
    assert [ws[c].value for c in ("A1", "B1", "G1", "H1", "I1")] == [
        2, "8-inch water main", 640, "LF", "Takeoff"]
    assert ws[f"{KIND}1"].value == "ITEM"
    assert wb["1 - MOBILIZATION"]["J1"].value == "n/a"     # a lump sum has no takeoff


def test_scope_notes_follow_the_header(wb):
    ws = wb[ITEM2]
    assert (ws["A3"].value, ws[f"{KIND}3"].value) == (
        "Trench to 6 ft max; native backfill above the pipe zone.", "NOTE")


# ---------------------------------------------------------------- palette

def test_the_palette_carries_the_survey_green_tokens():
    tokens = fieldbook_pack().tokens
    assert tokens["meta"]["base_font"] == {"name": "Arial", "size": 10}
    assert {k: tokens["fills"][k] for k in (
        "band", "colhead", "task", "note", "input",
        "lane_labor", "lane_equip", "lane_matl", "lane_sub")} == {
        "band": "1E4D3A", "colhead": "D7E6DD", "task": "EAF2ED", "note": "F6FAF7",
        "input": "FFF8DC", "lane_labor": "F3F8F5", "lane_equip": "F5F6FA",
        "lane_matl": "F7F9F0", "lane_sub": "FBF5F0"}
    colors = tokens["font_colors"]
    assert (colors["input"], colors["ok"], colors["bad"]) == ("1747B5", "1D7A46", "B42318")


def test_fill_marks_the_role_and_blue_type_marks_an_input(wb):
    ws = wb[ITEM2]
    assert (ws["A1"].fill.fgColor.rgb, ws["A1"].font.color.rgb, ws["A1"].font.b) == (
        "FF1E4D3A", "FFFFFFFF", True)                       # the header band
    assert (ws["G1"].fill.fgColor.rgb, ws["G1"].font.color.rgb) == (
        "FFFFF8DC", "FF1747B5")                              # bid qty is an input
    assert ws["A3"].fill.fgColor.rgb == "FFF6FAF7" and ws["A3"].font.i   # a note
    assert ws["A1"].font.name == "Arial"


# ---------------------------------------------------------------- rates and codes

def test_the_rates_sheet_lists_labor_and_equipment_by_full_name(wb):
    ws = wb["Rates"]
    assert (ws["A2"].value, ws["B2"].value) == ("Hours per crew-day", 8)
    names = [ws[f"A{r}"].value for r in range(5, 12)]
    assert names == ["Superintendent", "Pipelayer", "Equipment Operator", "Laborer",
                     "Excavator, 320 class", "Loader, 950 class", "Plate compactor"]
    assert [ws[f"B{r}"].value for r in (5, 9)] == ["Labor", "Equipment"]
    # a breakdown row computes $/hr; a flat row carries its rate
    assert (ws["C6"].value, ws["D6"].value, ws["E6"].value, ws["G6"].value) == (44, 0.3, 16.8, None)
    assert ws["G5"].value == 95
    assert ws["H6"].value == "=IF(ISNUMBER(C6),ROUND(C6*(1+D6)+E6,2),G6)"
    # includes-operator only on equipment rows, as a Yes/No dropdown
    assert (ws["F5"].value, ws["F9"].value) == (None, "No")
    dvs = {str(dv.sqref): dv.formula1 for dv in ws.data_validations.dataValidation}
    assert dvs["F9 F10 F11"] == '"Yes,No"'
    # Kind is typed by the estimator (Task 5's Labor/Equip split keys on it),
    # so it is a strict dropdown too, not a calculated label.
    assert dvs["B5 B6 B7 B8 B9 B10 B11"] == '"Labor,Equipment"'


def test_the_rates_table_ends_with_an_insert_above_marker_row(wb):
    ws = wb["Rates"]
    rows = [r for r in range(1, ws.max_row + 1)
            if ws[f"A{r}"].value == "insert new rates above this row"]
    (marker,) = rows
    assert marker == 12                               # one past the 7th (last) rate row
    assert ws[f"A{marker}"].font.italic
    for col in "BCDEFGH":
        assert ws[f"{col}{marker}"].value is None      # no amounts -- adds nothing on its own


def test_the_crew_dropdown_and_vlookup_range_run_through_the_rates_marker(wb):
    # The crew-resource dropdown and the crew VLOOKUP table both end AT the
    # marker row, one past the last real rate entry -- so a rate inserted
    # above it (Excel grows a range whose end anchor sits at the insertion
    # point, the same mechanism as a task block's own END row) lands inside
    # both, instead of the append being silently excluded.
    item = wb[ITEM2]
    crew_row = task_block(item, "02-100")["CREW"][0]
    assert item[f"G{crew_row}"].value == (
        f'=IFERROR(VLOOKUP($A{crew_row},\'Rates\'!$A$5:$H$12,8,FALSE),"")')
    dvs = {dv.formula1: str(dv.sqref) for dv in item.data_validations.dataValidation}
    assert "'Rates'!$A$5:$A$12" in dvs


def test_inserting_a_copied_rate_row_above_the_marker_grows_the_table():
    # A fresh build -- this test mutates the sheet (simulating a real paste).
    ws = build()["Rates"]
    (marker,) = [r for r in range(1, ws.max_row + 1)
                 if ws[f"A{r}"].value == "insert new rates above this row"]
    copy_from = marker - 1                              # "Plate compactor", the last real rate
    name_before = ws[f"A{copy_from}"].value

    simulate_insert_copied_row(ws, at_row=marker, copy_from_row=copy_from)

    assert ws[f"A{marker}"].value == name_before        # the copied rate landed above the marker
    assert ws[f"A{marker + 1}"].value == "insert new rates above this row"   # marker pushed down


def test_count_styled_cells_use_a_plain_general_format(wb):
    # '#,##0.##' renders a whole number as "8." in Excel; counts may be
    # fractional (a half crew-day), so the format must not force decimals.
    ws = wb[ITEM2]
    r = task_block(ws, "02-100")["CREW"][0]
    assert ws[f"D{r}"].number_format == "General"
    assert ws[f"E{r}"].number_format == "General"
    assert wb["Rates"]["B2"].number_format == "General"


def _codes(ws) -> list:
    return [(ws[f"A{r}"].value, ws[f"B{r}"].value, ws[f"C{r}"].value)
            for r in range(1, ws.max_row + 1)]


def test_the_codes_sheet_is_hidden_and_lists_the_org_code_list(wb):
    """The example carries the org's list (`cost_codes`, the seed's five);
    every task code is on it, so nothing is appended. C = on the org list."""
    ws = wb["Codes"]
    assert ws.sheet_state == "hidden"
    assert _codes(ws) == [
        ("01-100", "Mobilization", 1),
        ("02-100", "Trench excavation and pipe laying", 1),
        ("02-200", "Backfill and compaction", 1),
        ("02-300", "Pavement restoration", 1),
        ("02-510", "Valves and appurtenances", 1)]


def test_a_task_code_off_the_org_list_follows_it_once():
    spec = example_spec()
    spec["cost_codes"] = spec["cost_codes"][:2]                  # 01-100, 02-100
    spec["items"][2]["labor"][0]["cost_code"] = "02-200"         # two tasks now share 02-200
    assert _codes(build(spec)["Codes"]) == [
        ("01-100", "Mobilization", 1),
        ("02-100", "Trench excavation and pipe laying", 1),
        ("02-200", "Backfill & compaction", 0)]                  # the first task's description


def test_without_an_org_list_the_codes_sheet_lists_each_task_code_once():
    spec = example_spec()
    del spec["cost_codes"]
    spec["items"][2]["labor"][0]["cost_code"] = "02-100"         # item 3 reuses item 2's code
    assert _codes(build(spec)["Codes"]) == [
        ("01-100", "Mobilize crew and equipment", 0),
        ("02-100", "Trench excavation & pipe laying", 0),
        ("02-200", "Backfill & compaction", 0)]


def test_a_task_header_looks_its_code_up_on_the_org_list(wb):
    ws = wb[ITEM2]
    (head,) = task_block(ws, "02-100")["TASK"]
    assert ws[f"{OK}{head}"].value == (
        f"=IFERROR(INDEX('Codes'!$C$1:$C$5,MATCH(A{head},'Codes'!$A$1:$A$5,0)),0)")


# ---------------------------------------------------------------- takeoff

def test_takeoff_rows_carry_their_plan_reference_and_tie_to_bid_qty(wb):
    ws = wb[ITEM2]
    rows = rows_of_kind(ws, "TAKEOFF")
    assert [ws[f"C{r}"].value for r in rows] == ["C-3", "C-4"]
    total = rows[-1] + 1
    assert (ws[f"A{total}"].value, ws[f"{KIND}{total}"].value) == ("Takeoff total", "TOTAL")
    assert ws[f"B{total}"].value == f"=SUM(B{rows[0]}:B{rows[-1]})"
    assert ws[f"F{total}"].value == "=$G$1"
    assert ws[f"G{total}"].value == f'=IF(ABS(B{total}-F{total})<0.005,"✓","✗")'
    assert ws["J1"].value == f"=$B${total}"         # the header shows it, a forward ref
    valves = wb["3 - VALVES"]
    assert [valves[f"C{r}"].value for r in rows_of_kind(valves, "TAKEOFF")] == ["C-5"]


def test_a_measured_takeoff_prices_its_qty_by_the_unit_dropdown():
    spec = example_spec()
    spec["items"][1]["takeoff"] = {"kind": "measured", "lines": [
        {"label": "S-FTG-A1", "length": 20, "height": 3, "footing_cy": 14.8, "footing_cf": 400,
         "wall_cy": 0, "wall_cf": 0, "deck_cy": 0, "deck_cf": 0}]}
    ws = build(spec)[ITEM2]
    (r,) = rows_of_kind(ws, "TAKEOFF")
    assert (ws[f"A{r}"].value, ws[f"H{r}"].value) == ("S-FTG-A1", 14.8)
    qty = ws[f"B{r}"].value                          # live on the Unit, Count, L/W/H and CY columns
    eff = f'IF($C{r}="",$H$1,$C{r})'                # a blank Unit is the item's pay unit
    assert qty.startswith(f'=N{r}+IF(OR({eff}="CY",{eff}="CUYD"),SUM(H{r}:K{r}),')
    assert f"D{r}*E{r}*F{r}/9" in qty and f"L{r}/2000" in qty


def test_a_partial_measured_line_renders_blank_for_the_missing_measurements():
    # The schema requires only `label` on a measured line (vocabulary.yaml's
    # defs.takeoff/measured) -- an estimator who only has the footing poured
    # yet should be able to write {label: Footing, footing_cy: 14.8} without
    # the build crashing on the measurements nobody has entered.
    spec = example_spec()
    spec["items"][1]["takeoff"] = {"kind": "measured", "lines": [
        {"label": "Footing", "footing_cy": 14.8}]}
    ws = build(spec)[ITEM2]
    (r,) = rows_of_kind(ws, "TAKEOFF")
    assert (ws[f"A{r}"].value, ws[f"H{r}"].value) == ("Footing", 14.8)
    for col in "CDEFGIJKLMN":            # unit, count, L/W/H, wall/deck/other CY, weight, model, adjust
        assert ws[f"{col}{r}"].value is None
    assert ws[f"B{r}"].value.startswith(f"=N{r}+IF(")


# ---------------------------------------------------------------- task blocks

def test_a_task_block_opens_with_its_code_description_and_notes(wb):
    ws = wb[ITEM2]
    block = task_block(ws, "02-100")
    (head,) = block["TASK"]
    assert ws[f"B{head}"].value == "Trench excavation & pipe laying"
    assert [ws[f"A{r}"].value for r in block["NOTE"]] == [
        "Trench to 6 ft max; two pipe crews leapfrog; trench box both headings."]
    assert [ws[f"A{r}"].value for r in block["CREW"]] == [
        "Superintendent", "Pipelayer", "Equipment Operator", "Laborer", "Excavator, 320 class"]
    assert [(ws[f"D{r}"].value, ws[f"E{r}"].value) for r in block["CREW"]] == [(1, 8), (2, 8), (1, 8), (2, 8), (1, 8)]
    assert len(block["SUBTOTAL"]) == 1


def test_crew_rows_price_hours_by_rate_into_the_cost_type_column(wb):
    ws = wb[ITEM2]
    r = task_block(ws, "02-100")["CREW"][0]
    lookup = "'Rates'!$A$5:$H$12"
    assert ws[f"F{r}"].value == f"=D{r}*E{r}*'Rates'!$B$2"
    assert ws[f"G{r}"].value == f'=IFERROR(VLOOKUP($A{r},{lookup},8,FALSE),"")'
    assert ws[f"H{r}"].value == f'=IFERROR(VLOOKUP($A{r},{lookup},2,FALSE),"No rate")'
    assert ws[f"K{r}"].value == f'=IF(H{r}="Labor",F{r},0)'          # MH: labor hours only
    assert ws[f"L{r}"].value == f'=IF(H{r}="Labor",F{r}*G{r},0)'
    assert ws[f"M{r}"].value == f'=IF(H{r}="Equipment",F{r}*G{r},0)'
    assert ws[f"{OK}{r}"].value == (
        f'=IF(AND(ISNUMBER(G{r}),OR(H{r}="Labor",H{r}="Equipment")),1,0)')
    assert ws[f"{FLAG}{r}"].value == f'=IFERROR(IF(VLOOKUP($A{r},{lookup},6,FALSE)="Yes",1,0),0)'


def test_the_subtotal_sums_its_block_and_flags_a_double_counted_operator(wb):
    ws = wb[ITEM2]
    block = task_block(ws, "02-100")
    (head,), (sub,) = block["TASK"], block["SUBTOTAL"]
    assert ws[f"A{sub}"].value == f'=A{head}&" subtotal"'
    assert ws[f"L{sub}"].value == f"=SUM(L{head}:L{sub - 1})"
    assert ws[f"I{sub}"].value == f'=SUMIF(I{head}:I{sub - 1},"PLUG",P{head}:P{sub - 1})'
    assert ws[f"{FLAG}{sub}"].value == (
        f'=IF(AND(SUMIF(Q{head}:Q{sub - 1},"CREW",T{head}:T{sub - 1})>0,'
        f'COUNTIF(A{head}:A{sub - 1},"Equipment Operator")>0),1,0)')


# ---------------------------------------------------------------- round-trip tags

def test_every_item_sheet_hides_its_tag_and_helper_columns(wb):
    for name in ITEMS:
        dims = wb[name].column_dimensions
        assert [c for c in (KIND, CODE, OK, FLAG) if dims[c].hidden] == [KIND, CODE, OK, FLAG]


def test_the_code_tag_chains_from_each_task_header(wb):
    ws = wb[ITEM2]
    heads = rows_of_kind(ws, "TASK")
    assert len(heads) == 2
    for head in heads:
        assert ws[f"{CODE}{head}"].value == f'=A{head}&""'
        r = head + 1
        while ws[f"{KIND}{r}"].value not in ("TASK", None):
            assert ws[f"{CODE}{r}"].value == f"={CODE}{r - 1}", r
            r += 1


def test_every_laid_out_row_on_an_item_sheet_is_tagged(wb):
    for name in ITEMS:
        ws = wb[name]
        for r in range(1, ws.max_row + 1):
            filled = any(ws.cell(r, c).value is not None for c in range(1, 17))
            assert filled == (ws[f"{KIND}{r}"].value is not None), (name, r)


def _validations(ws):
    return {dv.formula1: (str(dv.sqref), dv) for dv in ws.data_validations.dataValidation}


def test_task_codes_and_crew_resources_are_strict_dropdowns(wb):
    for name in ITEMS:
        ws = wb[name]
        dvs = _validations(ws)
        assert dvs["'Codes'!$A:$A"][0] == " ".join(f"A{r}" for r in rows_of_kind(ws, "TASK"))
        assert dvs["'Rates'!$A$5:$A$12"][0] == " ".join(f"A{r}" for r in rows_of_kind(ws, "CREW"))
        for _, dv in dvs.values():
            assert (dv.type, dv.showErrorMessage, dv.errorStyle) == ("list", True, "stop")


def test_no_sheet_is_protected(wb):
    assert not any(ws.protection.sheet for ws in wb.worksheets)


def test_cost_lines_carry_type_source_and_vendor_as_inputs(wb):
    ws = wb[ITEM2]
    block = task_block(ws, "02-100")
    rows = block["LINE"]
    assert [[ws[f"{c}{r}"].value for c in "ABCGHIJ"] for r in rows] == [
        ["Trench box (rental)", 11, "DAY", 185, "Equipment", "QUOTE", "Rental Vendor B"],
        ["8-inch ductile iron pipe", 640, "LF", 42, "Material", "QUOTE", "Pipe Vendor A"],
        ["Bedding rock", 210, "TON", 31, "Material", "PLUG", None]]
    assert block["SUBTOTAL"] == [rows[-1] + 2]                    # lines, then the END marker, close the block
    r = rows[0]
    assert ws[f"M{r}"].value == f'=IF(H{r}="Equipment",B{r}*G{r},0)'
    assert ws[f"N{r}"].value == f'=IF(OR(H{r}="Material",H{r}="Other"),B{r}*G{r},0)'
    assert ws[f"O{r}"].value == f'=IF(H{r}="Subcontract",B{r}*G{r},0)'
    assert ws[f"{OK}{r}"].value == (
        f'=IF(AND(ISNUMBER(B{r}),ISNUMBER(G{r}),'
        f'OR(H{r}="Material",H{r}="Subcontract",H{r}="Equipment",H{r}="Other")),'
        f"IF(OR(AND(B{r}<>0,G{r}<>0),AND(U{r}=\"SP\",B{r}=0,V{r}<>0)),1,0),0)")
    assert ws[f"{FLAG}{r}"].value == f'=IF({CODE}{r}="",1,0)'     # no cost code


def test_line_types_and_sources_are_strict_literal_dropdowns(wb):
    for name in (ITEM2, "3 - VALVES"):
        ws = wb[name]
        rows = rows_of_kind(ws, "LINE")
        assert rows
        dvs = _validations(ws)
        assert dvs['"Material,Subcontract,Equipment,Other"'][0] == " ".join(f"H{r}" for r in rows)
        assert dvs['"QUOTE,PLUG"'][0] == " ".join(f"I{r}" for r in rows)


# ---------------------------------------------------------------- recap

def test_the_recap_references_each_task_subtotal_and_totals_them(wb):
    ws = wb[ITEM2]
    recap = rows_of_kind(ws, "RECAP")
    assert len(recap) == 2
    for r, code in zip(recap, ("02-100", "02-200")):
        block = task_block(ws, code)
        (head,), (sub,) = block["TASK"], block["SUBTOTAL"]
        assert [ws[f"{c}{r}"].value for c in "AB"] == [f"=$A${head}", f"=$B${head}"]
        assert [ws[f"{c}{r}"].value for c in "IKLMNOP"] == [f"=${c}${sub}" for c in "IKLMNOP"]
    total, per_unit = recap[-1] + 1, recap[-1] + 2
    assert ws[f"A{total}"].value == "ITEM TOTAL"
    assert ws[f"P{total}"].value == f"=SUM(P{recap[0]}:P{recap[-1]})"
    assert ws[f"A{per_unit}"].value == "PER LF"
    assert ws[f"P{per_unit}"].value == f"=IF($G$1=0,0,P{total}/$G$1)"
    assert rows_of_kind(ws, "TOTAL")[-2:] == [total, per_unit]


# ---------------------------------------------------------------- review fixes

def test_a_lump_sum_item_refuses_a_takeoff():
    spec = example_spec()
    spec["items"][0]["takeoff"] = {"kind": "count", "units": [{"label": "x", "count": 1}]}
    with pytest.raises(ValueError, match="takeoff"):
        validate_spec(spec, pack=fieldbook_pack())


def test_a_line_item_without_a_takeoff_is_refused():
    spec = example_spec()
    del spec["items"][1]["takeoff"]
    with pytest.raises(ValueError, match="takeoff"):
        validate_spec(spec, pack=fieldbook_pack())


def test_a_blank_cost_code_fails_validation():
    spec = example_spec()
    spec["items"][1]["labor"][0]["cost_code"] = ""
    with pytest.raises(ValueError, match="cost_code"):
        validate_spec(spec, pack=fieldbook_pack())


def test_two_tasks_with_the_same_cost_code_in_one_item_are_refused():
    # Two labor blocks naming the same cost code publish the same
    # `task[02-100]` instance key on one sheet -- without the engine's
    # duplicate-key guard, the second task's exports silently clobber the
    # first's and the recap/cost summary price the wrong block.
    spec = example_spec()
    spec["items"][1]["labor"].append(copy.deepcopy(spec["items"][1]["labor"][0]))
    with pytest.raises(ValueError, match="02-100"):
        build(spec)


def test_takeoff_total_shows_zero_instead_of_hiding_it(wb):
    ws = wb[ITEM2]
    rows = rows_of_kind(ws, "TAKEOFF")
    total = rows[-1] + 1
    assert ws[f"B{total}"].number_format == "#,##0.00"      # qty style, not money (which blanks 0)


def test_the_head_style_renders_dark_green_column_head_text(wb):
    ws = wb[ITEM2]
    detail_row = next(r for r in rows_of_kind(ws, "HEAD")
                       if ws[f"A{r}"].value == "Code / resource / item")
    assert ws[f"C{detail_row}"].font.color.rgb == "FF1E4D3A"
    assert ws[f"A{detail_row}"].font.color.rgb == "FF1E4D3A"      # head_left matches head


def test_the_head_and_task_text_tokens_carry_the_dark_green_ink():
    tokens = fieldbook_pack().tokens
    styles, font_colors = tokens["styles"], tokens["font_colors"]
    assert font_colors[styles["head"]["font_color"]] == "1E4D3A"
    assert font_colors[styles["head_left"]["font_color"]] == "1E4D3A"
    assert font_colors[styles["task_text"]["font_color"]] == "1E4D3A"


def test_item_sheet_columns_are_wide_enough_for_bid_qty_and_measured_heads(wb):
    # F must fit "12,345.00" (the bid-qty forward ref in the takeoff-total
    # row) and "Footing CY" (a measured-takeoff head); D/E must fit
    # "Length ft"/"Height ft" (the other measured-takeoff heads).
    widths = wb[ITEM2].column_dimensions
    assert (widths["D"].width, widths["E"].width, widths["F"].width) == (11, 11, 13)


def test_bid_form_shows_an_empty_input_cell_when_bid_date_is_absent():
    spec = example_spec()
    del spec["bid_date"]
    ws = build(spec)["Bid Form"]
    assert ws["B2"].value in ("", None)
    assert ws["B2"].fill.fgColor.rgb == "FFFFF8DC"           # cream input fill, ready to type into


# ---------------------------------------------------------------- tasks 5-7 review fixes

def test_a_crew_member_without_days_fails_validation():
    spec = example_spec()
    del spec["items"][1]["labor"][0]["crew"][0]["days"]
    with pytest.raises(ValueError, match="days"):
        validate_spec(spec, pack=fieldbook_pack())


def test_the_vendor_column_is_wide_enough_for_a_name(wb):
    assert wb[ITEM2].column_dimensions["J"].width == 24


def test_conditional_formats_mark_no_rate_quote_and_plug(wb):
    ws = wb[ITEM2]
    cfs = [(str(cf.sqref), rule.formula[0],
            rule.dxf.font.color.rgb if rule.dxf and rule.dxf.font and rule.dxf.font.color else None,
            rule.dxf.fill.bgColor.rgb if rule.dxf and rule.dxf.fill else None)
           for cf in ws.conditional_formatting for rule in cf.rules]
    crew_row = task_block(ws, "02-100")["CREW"][0]
    line_row = task_block(ws, "02-100")["LINE"][0]
    assert (f"H{crew_row}", f'$H{crew_row}="No rate"', "FFB42318", "FFFBE4E2") in cfs
    assert (f"I{line_row}", f'$I{line_row}="QUOTE"', "FF1D7A46", "FFE3F1E8") in cfs
    assert (f"I{line_row}", f'$I{line_row}="PLUG"', "FFB42318", "FFFBE4E2") in cfs


def test_the_per_row_shows_mh_per_unit_guarded_against_zero_qty(wb):
    ws = wb[ITEM2]
    recap = rows_of_kind(ws, "RECAP")
    total, per_unit = recap[-1] + 1, recap[-1] + 2
    assert ws[f"K{per_unit}"].value == f"=IF($G$1=0,0,K{total}/$G$1)"
    assert ws[f"K{per_unit}"].number_format == ws[f"L{per_unit}"].number_format   # same look as the other PER figures


def test_item_total_plug_dollar_uses_the_recap_rows_money_style(wb):
    ws = wb[ITEM2]
    recap = rows_of_kind(ws, "RECAP")
    total = recap[-1] + 1
    assert ws[f"I{total}"].number_format == '#,##0.00;(#,##0.00);""'


# ---------------------------------------------------------------- markup

def test_the_markup_sheet_reads_the_spec_fractions_bond_and_unbalance(wb):
    ws = wb["Markup"]
    assert [[ws[f"{c}{r}"].value for c in "ABCDE"] for r in (3, 4, 5)] == [
        ["Overhead", 0.12, 0.1, 0.05, 0.03],
        ["Insurance", 0.02, 0.01, 0.0, 0.0],
        ["Profit", 0.12, 0.1, 0.06, 0.04]]
    assert ws["B6"].value == "=SUM(B3:B5)"
    assert (ws["A7"].value, ws["B7"].value) == ("Bond (% of bid)", 0.012)
    # row 9: an "Unbalance" title row (its own section header, see below)
    # separates the bond row from the unbalance table.
    assert [[ws[f"{c}{r}"].value for c in "AC"] for r in (12, 13, 14)] == [
        [1, 1000], [2, -1000], [3, 0]]
    assert ws["C16"].value == "=SUM(C12:C14)"
    assert ws.column_dimensions["G"].hidden                 # the guard column


def test_the_unbalance_section_has_its_own_title_row(wb):
    ws = wb["Markup"]
    (title_r,) = [r for r in range(1, ws.max_row + 1) if ws[f"A{r}"].value == "Unbalance"]
    assert ws[f"A{title_r + 1}"].value == "Item"            # the column heads follow right after
    assert ws[f"B{title_r + 1}"].value == "Description"
    assert ws[f"C{title_r + 1}"].value == "Unbalance $"


def test_a_markup_row_the_sheet_does_not_lay_out_is_refused():
    spec = example_spec()
    spec["markup"]["contingency"] = {"labor": 0.05}
    with pytest.raises(ValueError, match=r"fieldbook lays out markup rows overhead, "
                                         r"insurance and profit only \(got 'contingency'\)"):
        build(spec)


def test_an_unknown_markup_row_without_bond_pct_is_still_caught():
    # (a): the guard must not key on bond_pct's presence -- an unknown row
    # with no bond_pct at all used to build silently with markup dropped.
    spec = example_spec()
    del spec["markup"]["bond_pct"]
    spec["markup"]["contingency"] = {"labor": 0.05}
    with pytest.raises(ValueError, match="fieldbook lays out markup rows"):
        build(spec)


def test_an_unknown_markup_row_with_bond_pct_zero_is_still_caught():
    # (b): bond_pct: 0 is falsy but still PRESENT -- the guard must not key
    # on its truthiness either.
    spec = example_spec()
    spec["markup"]["bond_pct"] = 0
    spec["markup"]["contingency"] = {"labor": 0.05}
    with pytest.raises(ValueError, match="fieldbook lays out markup rows"):
        build(spec)


@pytest.mark.parametrize("name", ["labor", "equip", "matl", "sub", "bond"])
def test_a_markup_row_named_like_a_markup_grid_export_is_still_refused(name):
    # markup_grid itself exports labor/equip/matl/sub/bond (the per-cost-type
    # totals and the bond cell) -- a spec markup row that happens to share
    # one of those names must not be able to borrow that export's address: the
    # guard needs its OWN namespace, or a row named e.g. "labor" builds
    # silently (wrong dollars, no row for it) instead of being refused.
    spec = example_spec()
    spec["markup"][name] = spec["markup"].pop("overhead")
    with pytest.raises(ValueError, match=r"fieldbook lays out markup rows overhead, "
                                         rf"insurance and profit only \(got '{name}'\)"):
        build(spec)


def test_markup_keys_are_case_sensitive():
    spec = example_spec()
    spec["markup"]["Overhead"] = spec["markup"].pop("overhead")   # capitalized: a different key
    with pytest.raises(ValueError, match="case-sensitive"):
        build(spec)


def test_a_plain_number_markup_is_refused_outright():
    # (c): fieldbook requires markup by cost type (markup_by_type: required);
    # a plain number -- what scaffold writes by default -- used to build
    # with markup silently dropped. Now it is refused outright, both by
    # schema and (independent of validate_spec) by the builder itself --
    # fieldbook's strict: true (Task 15) now runs that same schema check
    # inside build() too, ahead of the builder's own guard, so build(spec)
    # now surfaces the schema message first.
    spec = example_spec()
    spec["markup"] = 0
    with pytest.raises(ValueError, match="schema violation"):
        validate_spec(spec, pack=fieldbook_pack())
    with pytest.raises(ValueError, match="schema violation"):
        build(spec)
    # The builder's own guard is still there, independent of strict: a pack
    # that does NOT set strict: true still gets this refusal from build()
    # (proven generically in test_engine_extensions.py); confirmed directly
    # here against the raw EstimateBuilder, schema check skipped.
    from estimating_tools.estimate_spec.build import EstimateBuilder
    with pytest.raises(R.RecipeError, match="fieldbook"):
        EstimateBuilder(spec, fieldbook_pack())


# ---------------------------------------------------------------- cost summary

def test_the_cost_summary_reads_each_recap_and_solves_the_bid(wb):
    ws = wb["Cost Summary"]
    assert [ws[f"A{r}"].value for r in (4, 5, 6)] == [1, 2, 3]
    item = wb[ITEM2]
    (total,) = [r for r in rows_of_kind(item, "TOTAL") if item[f"A{r}"].value == "ITEM TOTAL"]
    assert [ws[f"{c}5"].value for c in "CDEFGI"] == [
        f"='2 - 8IN MAIN'!${c}${total}" for c in "KLMNOI"]
    assert ws["H5"].value == "=SUM(D5:G5)"
    assert ws["J5"].value == ("=D5*'Markup'!$B$6+E5*'Markup'!$C$6"
                              "+F5*'Markup'!$D$6+G5*'Markup'!$E$6")
    assert ws["K5"].value == "='Markup'!$C$13"               # item 2's unbalance row (Unbalance title shifted it down)
    assert ws["L5"].value == "=(H5+J5+K5)/(1-'Markup'!$B$7)"
    assert (ws["A8"].value, ws["L8"].value) == ("TOTAL", "=SUM(L4:L6)")
    assert ws["L9"].value == "=IF(C8=0,0,L8/C8)"            # bid $/MH


def test_the_cost_summary_carries_the_plug_line_moved_off_the_bid_form(wb):
    ws = wb["Cost Summary"]
    assert (ws["K10"].value, ws["L10"].value) == ("Plug $", "=I8")
    assert (ws["K11"].value, ws["L11"].value) == (
        "Plug % of direct", "=IF(H8=0,0,I8/H8)")


# ---------------------------------------------------------------- bid form

def test_the_bid_form_rounds_unit_prices_and_extends_them(wb):
    ws = wb["Bid Form"]
    assert (ws["A1"].value, ws["B2"].value.isoformat()) == ("Demo Pipeline Replacement", "2026-10-01")
    assert [[ws[f"{c}{r}"].value for c in "ABD"] for r in (5, 6, 7)] == [
        [1, "Mobilization and setup", "LS"], [2, "8-inch water main", "LF"],
        [3, "8-inch gate valves", "EA"]]
    assert ws["C6"].value == "='2 - 8IN MAIN'!$G$1"
    assert ws["E6"].value == "=IF(C6=0,0,ROUND('Cost Summary'!$L$5/C6,2))"
    assert ws["F6"].value == "=C6*E6"
    assert (ws["A9"].value, ws["F9"].value) == ("TOTAL BID", "=SUM(F5:F7)")
    # column G (the pooled rounding-allowance figure) is dead code, removed:
    # check 6 polices rounding per item now, not off a pooled allowance.
    assert ws["G9"].value is None
    assert not ws.column_dimensions["G"].hidden


def test_bid_form_qty_shows_plain_numbers_not_forced_decimals(wb):
    ws = wb["Bid Form"]
    assert ws["C5"].number_format == "General"     # qty 1 (LS) -- shows "1", not "1.00"
    assert ws["C6"].number_format == "General"     # qty 640 (LF) -- shows "640", not "640.00"


def test_bid_form_unit_price_and_amount_show_a_zero_instead_of_hiding_it(wb):
    ws = wb["Bid Form"]
    assert ws["E5"].number_format == "#,##0.00;(#,##0.00)"
    assert ws["F5"].number_format == "#,##0.00;(#,##0.00)"


# ---------------------------------------------------------------- checks

def _check_rows(ws):
    return [r for r in range(1, ws.max_row + 1) if isinstance(ws[f"A{r}"].value, int)]


def test_the_book_sheets_come_first_in_order(wb):
    assert wb.sheetnames == [
        "Bid Form", "Cost Summary", "Markup", "Checks", "Rates", "Codes", *ITEMS, "_templates"]


def test_the_checks_sheet_has_one_row_per_rule_and_item(wb):
    ws = wb["Checks"]
    rows = _check_rows(ws)
    per_rule = {}
    for r in rows:
        per_rule.setdefault(ws[f"A{r}"].value, []).append(ws[f"C{r}"].value)
    assert per_rule == {1: [1, 2, 3], 2: [1, 2, 3], 3: [1, 2, 3], 4: ["all"],
                        5: [1, 2, 3], 6: [1, 2, 3], 7: [1, 2, 3], 8: [1, 2, 3],
                        9: [1, 2, 3]}
    assert all(ws[f"F{r}"].value.startswith("=IFERROR(IF(") for r in rows)
    cf = {str(c.sqref): [rule.formula for rule in c.rules] for c in ws.conditional_formatting}
    assert sorted(cf) == sorted(f"F{r}" for r in rows)
    assert cf[f"F{rows[0]}"] == [[f'$F{rows[0]}="✓"'], [f'$F{rows[0]}="✗"']]
    assert (ws["B2"].value, ws["D2"].value) == (
        '=COUNTIF($F:$F,"✓")', '=COUNTIF($F:$F,"✓")+COUNTIF($F:$F,"✗")')


def test_check_5_reconciles_the_recap_by_the_kind_tags(wb):
    ws = wb["Checks"]
    (r,) = [r for r in _check_rows(ws) if (ws[f"A{r}"].value, ws[f"C{r}"].value) == (5, 2)]
    item = "'2 - 8IN MAIN'"
    assert ws[f"E{r}"].value == (f'=SUMIF({item}!$Q:$Q,"CREW",{item}!$P:$P)'
                                 f'+SUMIF({item}!$Q:$Q,"LINE",{item}!$P:$P)')


def test_check_6_is_per_item_not_pooled(wb):
    # Each item's own |Bid Form amount - Cost Summary bid| <= that item's own
    # qty x 0.005 + 0.005 -- not one pooled row for the whole bid, so a
    # rounding slip on one item can't hide behind another item's slack.
    ws = wb["Checks"]
    (r,) = [r for r in _check_rows(ws) if (ws[f"A{r}"].value, ws[f"C{r}"].value) == (6, 2)]
    assert ws[f"D{r}"].value == "='Bid Form'!$F$6"
    assert ws[f"E{r}"].value == "='Cost Summary'!$L$5"
    assert ws[f"F{r}"].value == (f'=IFERROR(IF(ABS(D{r}-E{r})'
                                 f'<=\'Bid Form\'!$C$6*0.005+0.005,"✓","✗"),"✗")')


def test_the_bid_form_status_strip_shows_only_the_checks_pass_count(wb):
    # A pass count is not a cost; the agency-facing Bid Form carries no
    # internal cost figure (not even a plug total) -- see the next test.
    ws = wb["Bid Form"]
    assert [ws[c].value for c in ("A11", "B11", "D11")] == [
        "Checks passing", "='Checks'!$B$2", "='Checks'!$D$2"]
    assert ws["A12"].value is None and ws["B12"].value is None


def test_the_bid_form_never_references_plug_or_direct_cost(wb):
    ws = wb["Bid Form"]
    for row in ws.iter_rows():
        for cell in row:
            v = cell.value
            if not isinstance(v, str):
                continue
            assert "plug" not in v.lower(), (cell.coordinate, v)
            assert "direct" not in v.lower(), (cell.coordinate, v)
            assert not re.search(r"Cost Summary'!\$[HI]\$", v), (cell.coordinate, v)


# ---------------------------------------------------------------- the END marker row

def test_each_task_block_ends_with_an_insert_above_marker_row(wb):
    ws = wb[ITEM2]
    for code in ("02-100", "02-200"):
        block = task_block(ws, code)
        (end_r,) = block["END"]
        (sub_r,) = block["SUBTOTAL"]
        assert end_r == sub_r - 1
        assert ws[f"A{end_r}"].value == "insert new lines above this row"
        assert ws[f"A{end_r}"].font.italic
        assert ws[f"{CODE}{end_r}"].value == f"={CODE}{end_r - 1}"


def test_the_end_row_carries_no_amounts_so_it_adds_nothing_to_any_total(wb):
    ws = wb[ITEM2]
    block = task_block(ws, "02-100")
    (end_r,) = block["END"]
    for col in "BCDEFGHIJKLMNOP":
        assert ws[f"{col}{end_r}"].value is None


def test_inserting_a_copied_line_row_at_the_end_row_grows_the_subtotal():
    # A fresh build -- this test mutates the sheet (simulating a real paste).
    ws = build()[ITEM2]
    block = task_block(ws, "02-100")
    (head,) = block["TASK"]
    (end_r,) = block["END"]
    (sub_r,) = block["SUBTOTAL"]
    line_rows = block["LINE"]
    copy_from = line_rows[0]

    simulate_insert_copied_row(ws, at_row=end_r, copy_from_row=copy_from)

    new_block = task_block(ws, "02-100")
    assert len(new_block["LINE"]) == len(line_rows) + 1          # the new line is in the block
    new_end_r, new_sub_r = new_block["END"][0], new_block["SUBTOTAL"][0]
    assert (new_end_r, new_sub_r) == (end_r + 1, sub_r + 1)       # END and SUBTOTAL both shifted down
    # The subtotal's own SUM/SUMIF ranges now end at the (shifted) END row,
    # one row further down than before the insert -- the new LINE row (at
    # the position the END row used to occupy) sits inside every range.
    for col in "KLMNO":
        assert ws[f"{col}{new_sub_r}"].value == f"=SUM({col}{head}:{col}{new_end_r})"
    assert ws[f"P{new_sub_r}"].value == f"=SUM(P{head}:P{new_end_r})"
    assert end_r < new_end_r
    # The new row carries its own copied amount formula, self-referencing
    # its own (new) row -- not the row it was copied from.
    assert ws[f"P{end_r}"].value == f"=SUM(L{end_r}:O{end_r})"


def test_inserting_a_copied_crew_row_keeps_its_absolute_rates_reference():
    # A fresh build -- this test mutates the sheet (simulating a real paste).
    # A copied CREW row's G/F formulas hold a cross-sheet reference into the
    # Rates table ('Rates'!$A$5:$H$12, 'Rates'!$B$2) that must never move --
    # the insertion-style row shifter (built for the OTHER, pushed-down rows
    # on this sheet) mis-reads the second endpoint of an absolute range (and
    # even a lone $COL$ROW cell) as a shiftable reference, because its regex
    # only refuses a reference immediately preceded by '!', not one preceded
    # by the reference's own leading '$'.
    ws = build()[ITEM2]
    block = task_block(ws, "02-100")
    (end_r,) = block["END"]
    copy_from = block["CREW"][0]

    simulate_insert_copied_row(ws, at_row=end_r, copy_from_row=copy_from)

    new_row = end_r                                   # the copy landed where END used to be
    assert ws[f"F{new_row}"].value == f"=D{new_row}*E{new_row}*'Rates'!$B$2"
    assert ws[f"G{new_row}"].value == (
        f'=IFERROR(VLOOKUP($A{new_row},\'Rates\'!$A$5:$H$12,8,FALSE),"")')
    assert ws[f"H{new_row}"].value == (
        f'=IFERROR(VLOOKUP($A{new_row},\'Rates\'!$A$5:$H$12,2,FALSE),"No rate")')


def test_inserting_a_copied_row_does_not_change_check_5s_whole_column_reconciliation(wb):
    # Check 5 (recap vs. detail) sums CREW/LINE by kind tag over the WHOLE
    # column, so it needs no update for a wider per-task SUBTOTAL range --
    # confirm that formula is exactly what Task 11 pinned, unchanged.
    ws = wb["Checks"]
    rows = [r for r in range(1, ws.max_row + 1) if isinstance(ws[f"A{r}"].value, int)]
    (r,) = [r for r in rows if (ws[f"A{r}"].value, ws[f"C{r}"].value) == (5, 2)]
    item = "'2 - 8IN MAIN'"
    assert ws[f"E{r}"].value == (f'=SUMIF({item}!$Q:$Q,"CREW",{item}!$P:$P)'
                                 f'+SUMIF({item}!$Q:$Q,"LINE",{item}!$P:$P)')


# ---------------------------------------------------------------- golden

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden" / "fieldbook.snapshot.json"


def test_the_example_workbook_matches_its_golden_snapshot():
    """Regenerate only for a deliberate, reviewed change:
    UPDATE_GOLDEN=1 pytest <this file> -k golden"""
    from estimating_tools.estimate_spec.tests._snapshot import snapshot

    got = json.loads(json.dumps(snapshot(build())))
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    # a golden that lost its layout must not pass: every sheet is in it, item sheets in full
    assert golden["order"] == ["Bid Form", "Cost Summary", "Markup", "Checks", "Rates", "Codes", *ITEMS, "_templates"]
    assert len(golden["sheets"][ITEM2]["cells"]) > 300
    assert got == golden


def test_the_seed_names_only_resources_the_vocabulary_permits():
    from estimating_tools.estimate_spec.format_pack import seed_rate_trades

    pack = fieldbook_pack()
    trades = set(pack.vocabulary["trades"])
    assert {t["trade"] for t in seed_rate_trades(pack.seed)} <= trades
    assert {m["trade"] for crew in pack.seed["crews"] for m in crew["members"]} <= trades
    assert {m["trade"] for m in pack.seed["default_crew"]} <= trades


def test_check_9_compares_task_headers_with_their_org_list_flags(wb):
    ws = wb["Checks"]
    (r,) = [r for r in _check_rows(ws) if (ws[f"A{r}"].value, ws[f"C{r}"].value) == (9, 2)]
    item = "'2 - 8IN MAIN'"
    assert ws[f"B{r}"].value == "Every task's cost code is on the org's code list"
    assert ws[f"D{r}"].value == f'=COUNTIF({item}!$Q:$Q,"TASK")'
    assert ws[f"E{r}"].value == f'=SUMIF({item}!$Q:$Q,"TASK",{item}!$S:$S)'


def test_without_an_org_list_there_is_no_check_9():
    spec = example_spec()
    del spec["cost_codes"]
    ws = build(spec)["Checks"]
    assert 9 not in {ws[f"A{r}"].value for r in _check_rows(ws)}


# ---------------------------------------------------------------- freeze + print

def test_the_bid_form_prints_one_page_wide_under_its_column_heads(wb):
    ws = wb["Bid Form"]
    assert ws.freeze_panes == "A4"                           # project, bid date, heads stay put
    assert ws.page_setup.orientation == "portrait"
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True
    assert (ws.page_setup.fitToWidth, ws.page_setup.fitToHeight) == (1, 0)
    assert ws.print_title_rows == "$1:$3"


def test_item_sheets_freeze_their_header_band_and_print_landscape(wb):
    for name in ITEMS:
        ws = wb[name]
        assert ws.freeze_panes == "A2", name                 # item #, description, bid qty
        assert ws.page_setup.orientation == "landscape", name
        assert ws.sheet_properties.pageSetUpPr.fitToPage is True, name
        assert (ws.page_setup.fitToWidth, ws.page_setup.fitToHeight) == (1, 0), name
        assert ws.print_title_rows == "$1:$1", name


def test_the_other_book_sheets_freeze_their_column_heads(wb):
    assert {s: wb[s].freeze_panes for s in ("Cost Summary", "Markup", "Checks", "Rates", "Codes")} == {
        "Cost Summary": "C3", "Markup": None, "Checks": "A4", "Rates": "A5", "Codes": None}
    for name, orientation, rows in (("Cost Summary", "landscape", "$1:$2"),
                                    ("Checks", "portrait", "$1:$3")):
        ws = wb[name]
        assert ws.page_setup.orientation == orientation, name
        assert (ws.page_setup.fitToWidth, ws.page_setup.fitToHeight) == (1, 0), name
        assert ws.print_title_rows == rows, name
