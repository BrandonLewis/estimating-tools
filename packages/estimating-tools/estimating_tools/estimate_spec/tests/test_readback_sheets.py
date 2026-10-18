"""Reading an edited fieldbook workbook's sheets into plain rows (no spec involved)."""
from __future__ import annotations

from estimating_tools.estimate_spec.readback import sheets as S
from estimating_tools.estimate_spec.tests._fieldbook import (
    CODE, KIND, build, copy_rows, simulate_delete_row, simulate_insert_copied_row, task_block)

ITEM2 = "2 - 8IN MAIN"


def _read(wb, sheet=ITEM2, takeoff_kind="linear"):
    return S.read_item_sheet(wb[sheet], takeoff_kind=takeoff_kind)


def test_an_item_sheet_reads_by_its_kind_tags():
    s = _read(build())
    assert (s.item_no, s.qty) == (2, 640)
    assert [r["A"] for r in s.notes] == ["Trench to 6 ft max; native backfill above the pipe zone."]
    assert [(r["A"], r["B"], r["C"]) for r in s.takeoff] == [
        ("STA 10+00 to 13+20", 320, "C-3"), ("STA 13+20 to 16+40", 320, "C-4")]
    assert [(t.code, t.description) for t in s.tasks] == [
        ("02-100", "Trench excavation & pipe laying"), ("02-200", "Backfill & compaction")]
    first = s.tasks[0]
    assert [r["A"] for r in first.notes] == [
        "Trench to 6 ft max; two pipe crews leapfrog; trench box both headings."]
    assert [(r["A"], r["D"], r["E"]) for r in first.crew] == [
        ("Superintendent", 1, 8), ("Pipelayer", 2, 8), ("Equipment Operator", 1, 8),
        ("Laborer", 2, 8), ("Excavator, 320 class", 1, 8)]
    assert [tuple(r[c] for c in "ABCGHIJ") for r in first.lines] == [
        ("Trench box (rental)", 11, "DAY", 185, "Equipment", "QUOTE", "Rental Vendor B"),
        ("8-inch ductile iron pipe", 640, "LF", 42, "Material", "QUOTE", "Pipe Vendor A"),
        ("Bedding rock", 210, "TON", 31, "Material", "PLUG", None)]
    assert s.noticed == S.Noticed()


def test_the_walk_never_reads_the_code_tags():
    # After a row delete Excel leaves `=#REF!` in the code chain; the walk
    # groups rows by the kind tag alone, so nothing changes.
    wb = build()
    ws = wb[ITEM2]
    for r in range(1, ws.max_row + 1):
        if ws[f"{CODE}{r}"].value:
            ws[f"{CODE}{r}"] = "=#REF!"
    assert _read(wb) == _read(build())


def test_a_pasted_block_is_a_task_of_its_own():
    wb = build()
    ws = wb[ITEM2]
    block = task_block(ws, "02-200")
    (first,), (sub,) = block["TASK"], block["SUBTOTAL"]
    copy_rows(ws, first, sub, sub + 1)
    ws[f"A{sub + 1}"] = "02-300"
    s = _read(wb)
    assert [t.code for t in s.tasks] == ["02-100", "02-200", "02-300"]
    assert [r["A"] for r in s.tasks[2].crew] == [r["A"] for r in s.tasks[1].crew]
    assert s.noticed == S.Noticed()


def test_a_row_with_no_kind_tag_is_listed_never_read():
    wb = build()
    ws = wb[ITEM2]
    ws["A40"], ws["B40"] = "Saw cut existing pavement", 120
    ws["A41"], ws["D41"], ws[f"{KIND}41"] = "Laborer", 2, "Crew"
    s = _read(wb)
    assert s.noticed.untagged == [
        "2 - 8IN MAIN row 40: A: Saw cut existing pavement, B: 120",
        "2 - 8IN MAIN row 41 (unknown tag 'Crew'): A: Laborer, D: 2"]
    assert [len(t.crew) for t in s.tasks] == [5, 4]


def test_an_untagged_rows_listing_shows_only_non_formula_values():
    # review fix (Tasks 1-4): a stray formula left in a pasted row is not
    # "typed content" the estimator wrote -- it never shows in the listing.
    wb = build()
    ws = wb[ITEM2]
    ws["A40"], ws["B40"], ws["C40"] = "Saw cut existing pavement", 120, "=A1"
    s = _read(wb)
    assert s.noticed.untagged == ["2 - 8IN MAIN row 40: A: Saw cut existing pavement, B: 120"]


def test_is_formula_recognises_array_and_data_table_formula_objects():
    # review fix (Tasks 1-4): openpyxl hands back an ArrayFormula/
    # DataTableFormula object, not a "=..." string, for those cell kinds.
    from openpyxl.worksheet.formula import ArrayFormula

    wb = build()
    ws = wb[ITEM2]
    (sub,) = task_block(ws, "02-100")["SUBTOTAL"]
    ws[f"N{sub}"] = ArrayFormula(f"N{sub}", f"=SUM(N1:N2)")
    assert _read(wb).noticed.overwrites == []


def test_a_literal_over_a_formula_is_noticed():
    wb = build()
    ws = wb[ITEM2]
    (sub,) = task_block(ws, "02-100")["SUBTOTAL"]
    crew = task_block(ws, "02-200")["CREW"][0]
    ws[f"N{sub}"] = 35000
    ws[f"G{crew}"] = None
    ws["P11"] = 1                                      # a recap figure
    assert _read(wb).noticed.overwrites == [
        "2 - 8IN MAIN!P11 (RECAP): typed 1 over the formula",
        f"2 - 8IN MAIN!N{sub} (SUBTOTAL): typed 35000 over the formula",
        f"2 - 8IN MAIN!G{crew} (CREW): cleared the formula"]


def test_a_row_below_the_end_marker_still_belongs_to_its_task():
    wb = build()
    ws = wb[ITEM2]
    block = task_block(ws, "02-100")
    (sub,) = block["SUBTOTAL"]
    simulate_insert_copied_row(ws, sub, block["CREW"][0])    # between END and SUBTOTAL
    s = _read(wb)
    assert [r["A"] for r in s.tasks[0].crew][-1] == "Superintendent"
    assert s.noticed.notices == [
        f"2 - 8IN MAIN row {sub}: CREW row below task 02-100's END row "
        "(outside its subtotal in this workbook) -- read into 02-100"]


def test_a_cleared_crew_row_reads_as_removed_not_four_blank_problems():
    # review fix (Tasks 5-7): the estimator deletes a row by clearing its
    # contents, not by deleting the row -- read it as removed, not as a pile
    # of "is blank" problems for every one of its fields.
    wb = build()
    ws = wb[ITEM2]
    crew = [r for r in task_block(ws, "02-100")["CREW"]
            if ws[f"A{r}"].value == "Pipelayer"][0]
    for col in "ADE":
        ws[f"{col}{crew}"] = None
    s = _read(wb)
    assert [r["A"] for r in s.tasks[0].crew] == [
        "Superintendent", "Equipment Operator", "Laborer", "Excavator, 320 class"]
    assert s.noticed.notices == [f"2 - 8IN MAIN row {crew}: CREW row was cleared -- read as removed"]
    assert s.noticed.problems == []


def test_a_partly_cleared_crew_row_still_blocks():
    wb = build()
    ws = wb[ITEM2]
    crew = [r for r in task_block(ws, "02-100")["CREW"]
            if ws[f"A{r}"].value == "Pipelayer"][0]
    ws[f"D{crew}"] = None                                     # only count cleared
    s = _read(wb)
    assert [r["A"] for r in s.tasks[0].crew][1] == "Pipelayer"
    assert s.noticed.notices == []


def test_a_crew_row_above_the_first_task_is_a_problem():
    wb = build()
    ws = wb[ITEM2]
    simulate_insert_copied_row(ws, 2, task_block(ws, "02-100")["CREW"][0])
    s = _read(wb)
    assert s.noticed.problems == [
        "2 - 8IN MAIN row 2: a CREW row above the first task block belongs to no task "
        "-- move it into a block (above an END row)"]
    assert [len(t.crew) for t in s.tasks] == [5, 4]


def test_deleting_a_row_moves_formulas_the_way_excel_does():
    # The helper later tests delete rows with: references below move up one,
    # a reference to the deleted row becomes #REF! (the code chain breaks).
    wb = build()
    ws = wb[ITEM2]
    block = task_block(ws, "02-100")
    (head,), (end,), (sub,) = block["TASK"], block["END"], block["SUBTOTAL"]
    line = block["LINE"][-1]                                  # Bedding rock, right above END
    simulate_delete_row(ws, line)
    assert ws[f"{KIND}{line}"].value == "END"
    assert ws[f"{CODE}{line}"].value == "=#REF!"
    assert ws[f"P{sub - 1}"].value == f"=SUM(P{head}:P{end - 1})"


def test_simulate_delete_row_shifts_merged_ranges_like_excel(tmp_path):
    # review fix (Tasks 5-7): openpyxl's own delete_rows never touches
    # merged_cells at all -- a range below the deleted row must move up
    # with it, and a range spanning only the deleted row must disappear.
    wb = build()
    ws = wb[ITEM2]
    assert "A19:J19" in {str(r) for r in ws.merged_cells.ranges}    # a single-row NOTE merge
    simulate_delete_row(ws, 19)                                      # delete that row itself
    ranges = {str(r) for r in ws.merged_cells.ranges}
    assert "A19:J19" not in ranges and "A18:J18" not in ranges       # gone, not duplicated either
    assert "B30:J30" not in ranges and "B29:J29" in ranges           # everything below moved up

    wb2 = build()
    ws2 = wb2[ITEM2]
    line = task_block(ws2, "02-100")["LINE"][0]                      # row 25: above neither merge
    simulate_delete_row(ws2, line)
    ranges2 = {str(r) for r in ws2.merged_cells.ranges}
    assert "A19:J19" in ranges2                                       # above the delete: untouched
    assert "B30:J30" not in ranges2 and "B29:J29" in ranges2           # below the delete: shifted up

    # The worksheet still has consistent merges after a save/reload.
    path = tmp_path / "deleted.xlsx"
    wb.save(path)
    from estimating_tools.estimate_spec.readback import load_workbook
    assert load_workbook(path) is not None


# ---------------------------------------------------------------- book sheets

def test_the_rate_table_reads_through_its_insert_above_marker():
    wb = build()
    rates = S.read_rates(wb["Rates"])
    assert rates.shift_hours == 8
    assert [tuple(r[c] for c in "ABCDEFG") for r in rates.rows][:2] == [
        ("Superintendent", "Labor", None, None, None, None, 95.0),
        ("Pipelayer", "Labor", 44.0, 0.3, 16.8, None, None)]
    simulate_insert_copied_row(wb["Rates"], 12, 11)          # a rate pasted above the marker
    wb["Rates"]["A12"] = "Water truck"
    rates = S.read_rates(wb["Rates"])
    assert [r["A"] for r in rates.rows][-2:] == ["Plate compactor", "Water truck"]
    assert rates.noticed == S.Noticed()


def test_a_typed_over_rate_formula_is_noticed():
    wb = build()
    wb["Rates"]["H6"] = 80
    assert S.read_rates(wb["Rates"]).noticed.overwrites == [
        "Rates!H6 (rate $/hr): typed 80 over the formula"]


def test_a_plainly_inserted_rate_row_never_had_an_h_formula_to_clear():
    # review fix (Tasks 1-4): a brand new row's $/hr is never read back (the
    # rate is derived from A-G), so a blank H there is not "cleared" -- there
    # was nothing to clear. A typed-over VALUE is still worth a notice.
    wb = build()
    ws = wb["Rates"]
    ws.insert_rows(12)                                  # a plain new row, nothing copied in
    ws["A12"], ws["B12"], ws["G12"] = "Water truck", "Equipment", 95
    assert S.read_rates(ws).noticed.overwrites == []
    ws["H12"] = 999                                      # the estimator typed a number in H anyway
    assert S.read_rates(ws).noticed.overwrites == [
        "Rates!H12 (rate $/hr): typed 999 over the formula"]


def test_rows_below_the_rates_marker_are_noticed_not_silently_dropped():
    # review fix (Tasks 1-4): a rate pasted BELOW the marker lands outside
    # both the crew VLOOKUP table and the dropdown; it was silently ignored.
    wb = build()
    ws = wb["Rates"]
    (marker,) = [r for r in range(1, ws.max_row + 1) if ws[f"A{r}"].value == "insert new rates above this row"]
    ws[f"A{marker + 1}"], ws[f"B{marker + 1}"], ws[f"G{marker + 1}"] = "Water truck", "Equipment", 95
    rates = S.read_rates(ws)
    assert [r["A"] for r in rates.rows] == [
        "Superintendent", "Pipelayer", "Equipment Operator", "Laborer",
        "Excavator, 320 class", "Loader, 950 class", "Plate compactor"]
    assert rates.noticed.notices == [
        f"Rates row {marker + 1} (Water truck): below the Rates marker -- not in the rate "
        "table; insert rates above the marker"]


def test_the_markup_sheet_reads_its_grid_bond_and_unbalances():
    m = S.read_markup(build()["Markup"])
    assert {name: [row[c] for c in "BCDE"] for name, row in m.rows.items()} == {
        "overhead": [0.12, 0.1, 0.05, 0.03], "insurance": [0.02, 0.01, 0.0, 0.0],
        "profit": [0.12, 0.1, 0.06, 0.04]}
    assert m.bond == 0.012
    assert [(r.row, r["A"], r["C"]) for r in m.unbalance] == [(12, 1, 1000), (13, 2, -1000), (14, 3, 0)]


def test_a_deleted_total_row_does_not_swallow_bond_and_unbalance():
    # review fix (Tasks 1-4): the grid used to stay "open" past a missing
    # Total row, so Bond and the unbalance rows got read as grid rows too.
    wb = build()
    ws = wb["Markup"]
    (total,) = [r for r in range(1, ws.max_row + 1) if ws[f"A{r}"].value == "Total"]
    simulate_delete_row(ws, total)
    m = S.read_markup(ws)
    assert set(m.rows) == {"overhead", "insurance", "profit"}
    assert m.bond == 0.012
    assert [(r["A"], r["C"]) for r in m.unbalance] == [(1, 1000), (2, -1000), (3, 0)]
    assert m.noticed.notices == [
        "Markup: no 'Total' row found under the grid -- closed it at the first blank row"]


def test_the_bid_date_is_read_off_the_bid_form():
    value, found = S.read_bid_date(build()["Bid Form"])
    assert found and str(value)[:10] == "2026-10-01"


def test_the_bid_date_reads_an_excel_serial_as_a_date():
    # review fix (Tasks 1-4): a Bid date cell that lost its date number
    # format still reads back as the date it represents, not a raw serial.
    wb = build()
    wb["Bid Form"]["B2"] = 46000
    value, found = S.read_bid_date(wb["Bid Form"])
    assert found and str(value)[:10] == "2025-12-09"


def test_a_missing_bid_date_label_row_is_reported_as_not_found():
    wb = build()
    wb["Bid Form"]["A2"] = "Start date"
    assert S.read_bid_date(wb["Bid Form"]) == (None, False)


def test_a_typed_over_book_formula_is_found_against_a_fresh_build():
    wb = build()
    wb["Bid Form"]["E6"] = 170                                # a unit price typed over
    noticed = S.Noticed()
    S.scan_against_baseline(wb["Bid Form"], build()["Bid Form"], noticed)
    assert noticed.overwrites == ["Bid Form!E6 (formula): typed 170 over the formula"]


def test_a_book_sheet_whose_rows_moved_is_not_scanned():
    wb = build()
    wb["Cost Summary"].insert_rows(3)
    noticed = S.Noticed()
    S.scan_against_baseline(wb["Cost Summary"], build()["Cost Summary"], noticed)
    assert noticed.notices == [
        "Cost Summary: rows were added, removed or moved -- not checked for typed-over formulas"]
    assert noticed.overwrites == []


def test_row_map_follows_rows_inserted_and_deleted_by_their_kind_tags():
    base = build()["2 - 8IN MAIN"]
    wb = build()
    ws = wb["2 - 8IN MAIN"]
    simulate_insert_copied_row(ws, 7, 7)                  # a takeoff row, inside the SUM
    simulate_delete_row(ws, 27)                           # the ductile iron pipe line (was 26)
    rows = S.row_map(base, ws)
    assert rows[1] == 1 and rows[6] == 6                  # above the insert: unmoved
    assert rows[7] == 8 and rows[8] == 9                  # the old last segment, the total
    assert rows[25] == 26                                 # trench box line
    assert 26 not in rows                                 # the deleted line
    assert rows[27] == 27                                 # Bedding rock: +1 -1
    assert rows[28] == 28 and rows[38] == 38              # END, last SUBTOTAL: +1 -1


_OUTSIDE = "is not in the workbook's takeoff total"


def test_a_takeoff_row_inserted_below_the_total_range_is_a_notice():
    # Excel does not grow `=SUM(B6:B7)` for a row inserted at row 8 (the
    # total row): the edited workbook prices 640 LF, the rebuild 900.
    wb = build()
    ws = wb[ITEM2]
    simulate_insert_copied_row(ws, 8, 7)
    ws["A8"], ws["B8"] = "STA 16+40 to 19+00", 260
    assert ws["B9"].value == "=SUM(B6:B7)"
    sheet = _read(wb)
    assert [r.row for r in sheet.takeoff] == [6, 7, 8]          # still read as a segment
    assert sheet.noticed.notices == [
        f"{ITEM2}: takeoff row 8 (STA 16+40 to 19+00) {_OUTSIDE} -- it is read back as a "
        "segment, so the total will change after the rebuild (insert segments above the "
        "total row to see them priced now)"]


def test_a_takeoff_row_inserted_inside_the_total_range_is_no_notice():
    wb = build()
    ws = wb[ITEM2]
    simulate_insert_copied_row(ws, 7, 7)
    ws["A7"], ws["B7"] = "STA 16+40 to 19+00", 260
    assert ws["B9"].value == "=SUM(B6:B8)"
    sheet = _read(wb)
    assert [r.row for r in sheet.takeoff] == [6, 7, 8]
    assert not any(_OUTSIDE in n for n in sheet.noticed.notices)
