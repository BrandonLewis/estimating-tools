"""The round trip (fieldbook phase 4's acceptance test): build -> edit in "Excel"
-> read back -> write -> rebuild -> evaluate.

The edits are what an estimator does in Excel, simulated with openpyxl the way
Excel moves formulas (`_fieldbook`'s copy/insert/delete helpers). Every money
figure below is what pycel computed from the rebuilt workbook.
"""
from __future__ import annotations

import pytest
import yaml

from estimating_tools.estimate_spec import cli
from estimating_tools.estimate_spec.readback import load_workbook, read_back
from estimating_tools.estimate_spec.tests._fieldbook import (
    EXAMPLE, FIELDBOOK_DIR, build, check_statuses, copy_rows, example_spec, rows_of_kind,
    simulate_delete_row, simulate_insert_copied_row, task_block)
from estimating_tools.estimate_spec.tests._formula_eval import evaluate

ITEM2 = "2 - 8IN MAIN"


def _row(ws, kind, name):
    (r,) = [r for r in rows_of_kind(ws, kind) if ws[f"A{r}"].value == name]
    return r


def _add_rate(wb, name, kind, rate):
    """Paste a copy of the last rate in above the Rates marker row and retype it."""
    ws = wb["Rates"]
    (marker,) = [r for r in range(1, ws.max_row + 1)
                 if ws[f"A{r}"].value == "insert new rates above this row"]
    simulate_insert_copied_row(ws, marker, marker - 1)
    ws[f"A{marker}"], ws[f"B{marker}"], ws[f"G{marker}"] = name, kind, rate
    ws[f"F{marker}"] = "No" if kind == "Equipment" else None


def _estimator_edits(wb, *, overwrite=True, paste_block=True) -> None:
    """The acceptance edits. For bid parity (the edited workbook prices what
    the rebuilt one does) leave out two by design: the number typed over a
    subtotal (`overwrite`; ignored, the rebuild restores the formula) and the
    pasted 02-300 block (`paste_block`; the item's recap only sums the tasks
    laid out at build time, so a pasted block is priced from the rebuild on)."""
    ws = wb[ITEM2]
    # A crew row copied in above 02-100's END row, retyped as a resource with no rate.
    block = task_block(ws, "02-100")
    end = block["END"][0]
    (laborer,) = [r for r in block["CREW"] if ws[f"A{r}"].value == "Laborer"]
    simulate_insert_copied_row(ws, end, laborer)
    ws[f"A{end}"], ws[f"D{end}"], ws[f"E{end}"] = "Truck Driver", 1, 8
    # A cost line deleted.
    simulate_delete_row(ws, _row(ws, "LINE", "Bedding rock"))
    # The whole 02-200 block copied below the last block; a new code and description.
    if paste_block:
        block = task_block(ws, "02-200")
        (first,), (sub,) = block["TASK"], block["SUBTOTAL"]
        copy_rows(ws, first, sub, sub + 1)
        head = sub + 1
        ws[f"A{head}"], ws[f"B{head}"] = "02-300", "Pavement restoration"
        (loader,) = [r for r in range(head, head + sub - first + 1)
                     if ws[f"A{r}"].value == "Loader, 950 class"]
        ws[f"A{loader}"] = "Water truck"                # uses the rate added below
    # A better pipe price, and a number typed over a subtotal by mistake.
    ws[f"G{_row(ws, 'LINE', '8-inch ductile iron pipe')}"] = 44.5
    if overwrite:
        (sub,) = task_block(ws, "02-100")["SUBTOTAL"]
        ws[f"N{sub}"] = 35000
    # A row pasted in from another workbook (no kind tag).
    untagged = ws.max_row + 2
    for col, value in zip("ABCG", ("Saw cut existing pavement", 120, "LF", 3.25)):
        ws[f"{col}{untagged}"] = value
    # A rate added above the Rates marker row, a markup %, offsetting unbalances.
    _add_rate(wb, "Water truck", "Equipment", 95)
    wb["Markup"]["B5"] = 0.10                           # profit on labor
    wb["Markup"]["C12"], wb["Markup"]["C14"] = 500, 500  # item 1: 1000 -> 500, item 3: 0 -> 500


def test_an_unedited_workbook_round_trips_to_the_same_spec(tmp_path):
    path = tmp_path / "built.xlsx"
    build().save(path)
    result = read_back(example_spec(), load_workbook(path))
    assert result.spec == example_spec()
    assert result.findings.changes == [] and not result.blocked


def test_the_round_trip(tmp_path):
    wb = build()
    _estimator_edits(wb)
    path = tmp_path / "edited.xlsx"
    wb.save(path)
    result = read_back(example_spec(), load_workbook(path))
    f = result.findings
    assert f.changes == [
        "rates · + Water truck (equipment, 95/hr)",
        "markup · profit labor 0.12 → 0.1",
        "item 1 · unbalance 1,000 → 500",
        "item 3 · unbalance 0 → 500",
        "item 2 · 02-100 · + crew Truck Driver × 1, 8 days",
        "item 2 · 02-100 · 8-inch ductile iron pipe: unit_price 42 → 44.5",
        "item 2 · 02-100 · − line Bedding rock 210 TON @ 31 material (removed)",
        "item 2 · + new task 02-300 Pavement restoration (4 crew rows, 1 cost line, 1 note)",
        "item 2 · 02-300 · + note 'Native backfill above the pipe zone; 95% relative "
        "compaction under pavement.'",
        "item 2 · 02-300 · + crew Equipment Operator × 1, 3 days",
        "item 2 · 02-300 · + crew Laborer × 2, 3 days",
        "item 2 · 02-300 · + crew Water truck × 1, 3 days",
        "item 2 · 02-300 · + crew Plate compactor × 1, 3 days",
        "item 2 · 02-300 · + line Haul, import + export 460 CY @ 18 subcontract"]
    assert f.needs_rate == {"Truck Driver": ["item 2 · 02-100"]}
    assert f.overwrites == ["2 - 8IN MAIN!N29 (SUBTOTAL): typed 35000 over the formula"]
    assert f.untagged == ["2 - 8IN MAIN row 49: A: Saw cut existing pavement, B: 120, C: LF, G: 3.25"]
    assert f.notices == [] and f.problems == []

    # Rebuilt: the new task is in the recap; every check passes but the one
    # the estimator still owes (Truck Driver has no rate: check 2, item 2).
    rebuilt = build(result.spec)
    ev = evaluate(rebuilt, tmp_path)
    ws = rebuilt[ITEM2]
    assert [ev[f"{ITEM2}!A{r}"] for r in rows_of_kind(ws, "RECAP")] == ["02-100", "02-200", "02-300"]
    statuses = check_statuses(rebuilt, ev)
    assert len(statuses) == 25
    assert {k for k, s in statuses.items() if s != "✓"} == {(2, 2)}

    # Round two: the estimator adds the missing rate in the rebuilt workbook.
    _add_rate(rebuilt, "Truck Driver", "Labor", 70)
    path2 = tmp_path / "round2.xlsx"
    rebuilt.save(path2)
    second = read_back(result.spec, load_workbook(path2))
    round_two_bid = _bid(load_workbook(path2), tmp_path / "ev_round2")
    assert second.findings.changes == ["rates · + Truck Driver (labor, 70/hr)"]
    assert second.findings.needs_rate == {} and not second.blocked

    final = build(second.spec)
    ev = evaluate(final, tmp_path)
    statuses = check_statuses(final, ev)
    assert len(statuses) == 25 and set(statuses.values()) == {"✓"}
    assert (ev["Bid Form!B11"], ev["Bid Form!D11"]) == (25, 25)
    total = {c: ev[f"Cost Summary!{c}8"] for c in "CDEFGHIJKL"}
    # The example's 552 MH / $99,385 direct, plus: Truck Driver 64 MH x $70;
    # the new 02-300 task (02-200's crew with a water truck for the loader,
    # and its haul line); the pipe at $44.50; Bedding rock gone.
    assert total["C"] == 688                                        # MH
    assert (total["D"], total["E"], total["F"], total["G"]) == (49696, 17915, 28480, 19160)
    assert total["H"] == 115251                                     # direct
    assert total["I"] == 16560                                      # plugs
    assert total["J"] == pytest.approx(20163.19)                    # markup, profit on labor at 10%
    assert total["K"] == 0                                          # the unbalances still net out
    assert total["L"] == pytest.approx(137058.8967611336)
    assert ev["Bid Form!F9"] == pytest.approx(137060.84)
    assert round(ev["Bid Form!F9"], 2) == round_two_bid             # bid parity, round two


def test_the_cli_round_trip_writes_what_read_back_computed(tmp_path, capsys):
    spec = tmp_path / "bid.estimate.yaml"
    spec.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    xlsx = tmp_path / "bid.xlsx"
    assert cli.main(["build", str(spec), "-o", str(xlsx), "--format", str(FIELDBOOK_DIR)]) == 0
    wb = load_workbook(xlsx)
    _estimator_edits(wb)
    wb.save(xlsx)
    expected = read_back(example_spec(), load_workbook(xlsx)).spec
    assert cli.main(["read-back", str(spec), str(xlsx), "--write"]) == 0
    assert yaml.safe_load(spec.read_text(encoding="utf-8")) == expected
    rebuilt = tmp_path / "rebuilt.xlsx"
    assert cli.main(["build", str(spec), "-o", str(rebuilt), "--format", str(FIELDBOOK_DIR)]) == 0
    assert "WROTE:" in capsys.readouterr().out


def _bid(wb, tmp_path) -> float:
    """The Bid Form total, as pycel computes it from `wb`."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    return round(evaluate(wb, tmp_path)["Bid Form!F9"], 2)


def _anchored_example() -> str:
    """The example with item 3's task crew an alias of item 1's (`&mobcrew`)."""
    text = EXAMPLE.read_text(encoding="utf-8")
    text = text.replace("""        crew:
          - { trade: Superintendent, count: 1, days: 2 }
          - { trade: Laborer, count: 2, days: 2 }""", """        crew: &mobcrew
          - { trade: Superintendent, count: 1, days: 2 }
          - { trade: Laborer, count: 2, days: 2 }""")
    text = text.replace("""        crew:
          - { trade: Pipelayer, count: 2, days: 2 }
          - { trade: Laborer, count: 1, days: 2 }""", "        crew: *mobcrew")
    assert text.count("mobcrew") == 2
    return text


def test_an_edit_to_a_yaml_anchor_shared_by_two_tasks_edits_only_its_own_task(tmp_path, capsys):
    spec = tmp_path / "bid.estimate.yaml"
    spec.write_text(_anchored_example(), encoding="utf-8")
    xlsx = tmp_path / "bid.xlsx"
    assert cli.main(["build", str(spec), "-o", str(xlsx), "--format", str(FIELDBOOK_DIR)]) == 0
    wb = load_workbook(xlsx)
    ws = wb["1 - MOBILIZATION"]
    ws[f"E{_row(ws, 'CREW', 'Superintendent')}"] = 3
    wb.save(xlsx)
    edited_bid = _bid(load_workbook(xlsx), tmp_path / "ev_edited")
    capsys.readouterr()
    assert cli.main(["read-back", str(spec), str(xlsx), "--write"]) == 0
    out = capsys.readouterr().out
    assert "- item 1 · 01-100 · Superintendent: days 2 → 3" in out
    assert "item 3" not in out.split("## Changes")[1].split("##")[0]     # no bogus change
    assert ("the YAML anchor shared by item 1 · 01-100 · crew and item 3 · 02-510 · crew "
            "was expanded so each can be edited separately") in out
    written = yaml.safe_load(spec.read_text(encoding="utf-8"))
    assert written["items"][0]["labor"][0]["crew"][0]["days"] == 3
    assert written["items"][2]["labor"][0]["crew"][0]["days"] == 2
    rebuilt = tmp_path / "rebuilt.xlsx"
    assert cli.main(["build", str(spec), "-o", str(rebuilt), "--format", str(FIELDBOOK_DIR)]) == 0
    assert _bid(load_workbook(rebuilt), tmp_path / "ev_rebuilt") == edited_bid


def _swap_crew(wb):
    ws = wb[ITEM2]
    a, b = task_block(ws, "02-100")["CREW"][:2]
    for c in "ADE":
        ws[f"{c}{a}"].value, ws[f"{c}{b}"].value = ws[f"{c}{b}"].value, ws[f"{c}{a}"].value


def _clear_crew_row(wb):
    ws = wb[ITEM2]
    (r,) = [r for r in task_block(ws, "02-100")["CREW"] if ws[f"A{r}"].value == "Laborer"]
    for c in "ADE":
        ws[f"{c}{r}"] = None


def _rename_task(wb):
    ws = wb[ITEM2]
    (head,) = task_block(ws, "02-200")["TASK"]
    ws[f"A{head}"] = "02-250"


def _set(**cells):
    def edit(wb):
        for address, value in cells.items():
            sheet, cell = address.split("!")
            wb[sheet][cell] = value
    return edit


def _line(name, **cols):
    def edit(wb):
        ws = wb[ITEM2]
        r = _row(ws, "LINE", name)
        for col, value in cols.items():
            ws[f"{col}{r}"] = value
    return edit


def _crew(name, **cols):
    def edit(wb):
        ws = wb[ITEM2]
        r = _row(ws, "CREW", name)
        for col, value in cols.items():
            ws[f"{col}{r}"] = value
    return edit


@pytest.mark.parametrize("edit", [
    _line("8-inch ductile iron pipe", G=44.5),                       # unit price
    _crew("Pipelayer", E=9),                                         # days
    _line("Bedding rock", H="Subcontract", I="QUOTE", J="Rock Co"),  # type / source / vendor
    _set(**{"Rates!B2": 10}),                                        # hours per crew-day
    _clear_crew_row,                                                 # a crew row cleared
    _rename_task,                                                    # a code retyped
    _swap_crew,                                                      # crew rows swapped
    lambda wb: _estimator_edits(wb, overwrite=False, paste_block=False),
], ids=["price", "days", "type-source", "shift-hours", "cleared-crew-row", "rename",
        "crew-reorder", "acceptance-edits"])
def test_one_edit_rebuilds_to_the_bid_the_edited_workbook_shows(tmp_path, edit):
    spec = tmp_path / "bid.estimate.yaml"
    spec.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    xlsx = tmp_path / "bid.xlsx"
    assert cli.main(["build", str(spec), "-o", str(xlsx), "--format", str(FIELDBOOK_DIR)]) == 0
    unedited = _bid(load_workbook(xlsx), tmp_path / "ev_unedited")
    wb = load_workbook(xlsx)
    edit(wb)
    wb.save(xlsx)
    edited = _bid(load_workbook(xlsx), tmp_path / "ev_edited")
    assert cli.main(["read-back", str(spec), str(xlsx), "--write"]) == 0
    rebuilt = tmp_path / "rebuilt.xlsx"
    assert cli.main(["build", str(spec), "-o", str(rebuilt), "--format", str(FIELDBOOK_DIR)]) == 0
    assert _bid(load_workbook(rebuilt), tmp_path / "ev_rebuilt") == edited
    # Every money edit really moved the bid (a rename or reorder does not).
    assert (edited == unedited) == (edit in (_rename_task, _swap_crew))


# ------------------------------------- placeholder formulas after rows move

TRENCH_BOX = "Trench box (rental)"


def _placeholder_spec() -> dict:
    """The example with the trench box's qty a placeholder: the takeoff total."""
    spec = example_spec()
    (line,) = [ln for ln in spec["items"][1]["labor"][0]["lines"] if ln["name"] == TRENCH_BOX]
    line["qty"] = "={ref:quantity.total}"
    return spec


def _insert_segment(wb) -> None:
    """A third takeoff segment: the last one copied and inserted above itself
    (Excel's insert copied cells -- inside the total's SUM range, so the
    total grows), then retyped. Every row below it moves down one."""
    ws = wb[ITEM2]
    last = rows_of_kind(ws, "TAKEOFF")[-1]
    simulate_insert_copied_row(ws, last, last)
    ws[f"A{last}"], ws[f"B{last}"], ws[f"C{last}"] = "STA 16+40 to 19+00", 260, "C-5"


def _delete_segment(wb) -> None:
    ws = wb[ITEM2]
    simulate_delete_row(ws, rows_of_kind(ws, "TAKEOFF")[-1])


def _qty_formula(wb) -> str:
    ws = wb[ITEM2]
    return ws[f"B{_row(ws, 'LINE', TRENCH_BOX)}"].value


def test_an_unchanged_placeholder_still_matches_after_a_takeoff_row_is_inserted(tmp_path):
    # Copilot review (PR #355): the line qty's `={ref:quantity.total}` builds
    # as `=$B$8`; inserting a takeoff row makes Excel shift it to `=$B$9`,
    # which no longer equaled the baseline's `=$B$8` -- the untouched input
    # was blocked as a cell-referencing formula.
    spec = _placeholder_spec()
    wb = build(spec)
    assert _qty_formula(wb) == "=$B$8"
    _insert_segment(wb)
    assert _qty_formula(wb) == "=$B$9"                       # what Excel did to it
    wb.save(tmp_path / "edited.xlsx")
    result = read_back(spec, load_workbook(tmp_path / "edited.xlsx"))
    assert result.findings.problems == []
    assert result.findings.changes == [
        "item 2 · takeoff · + takeoff row label STA 16+40 to 19+00, length_lf 260, ref C-5"]
    (line,) = [ln for ln in result.spec["items"][1]["labor"][0]["lines"] if ln["name"] == TRENCH_BOX]
    assert line["qty"] == "={ref:quantity.total}"             # the placeholder kept


def test_an_unchanged_placeholder_still_matches_after_a_takeoff_row_is_deleted(tmp_path):
    spec = _placeholder_spec()
    wb = build(spec)
    _delete_segment(wb)
    assert _qty_formula(wb) == "=$B$7"
    wb.save(tmp_path / "edited.xlsx")
    result = read_back(spec, load_workbook(tmp_path / "edited.xlsx"))
    assert result.findings.problems == []
    assert result.findings.changes == [
        "item 2 · takeoff · − takeoff row label STA 13+20 to 16+40, length_lf 320, ref C-4 (removed)"]


def test_a_genuinely_different_reference_after_rows_move_is_still_a_problem(tmp_path):
    spec = _placeholder_spec()
    wb = build(spec)
    _insert_segment(wb)
    ws = wb[ITEM2]
    r = _row(ws, "LINE", TRENCH_BOX)
    ws[f"B{r}"] = "=$B$8"            # the OLD address: now a takeoff segment, not the total
    wb.save(tmp_path / "edited.xlsx")
    result = read_back(spec, load_workbook(tmp_path / "edited.xlsx"))
    assert result.findings.problems == [
        f"{ITEM2} row {r} (item 2 · 02-100): qty holds the formula '=$B$8' -- type a number"]


def test_a_placeholder_moved_by_an_inserted_takeoff_row_rebuilds_to_the_same_bid(tmp_path):
    spec = tmp_path / "bid.estimate.yaml"
    spec.write_text(yaml.safe_dump(_placeholder_spec(), sort_keys=False), encoding="utf-8")
    xlsx = tmp_path / "bid.xlsx"
    assert cli.main(["build", str(spec), "-o", str(xlsx), "--format", str(FIELDBOOK_DIR)]) == 0
    unedited = _bid(load_workbook(xlsx), tmp_path / "ev_unedited")
    wb = load_workbook(xlsx)
    _insert_segment(wb)
    wb.save(xlsx)
    edited = _bid(load_workbook(xlsx), tmp_path / "ev_edited")
    assert edited != unedited                     # 260 more LF -- and more trench-box days
    assert cli.main(["read-back", str(spec), str(xlsx), "--write"]) == 0
    rebuilt = tmp_path / "rebuilt.xlsx"
    assert cli.main(["build", str(spec), "-o", str(rebuilt), "--format", str(FIELDBOOK_DIR)]) == 0
    assert _bid(load_workbook(rebuilt), tmp_path / "ev_rebuilt") == edited
