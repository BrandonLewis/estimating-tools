"""The read-back report: one Markdown page, a section per kind of finding."""
from __future__ import annotations

from estimating_tools.estimate_spec.readback import Findings, ReadBack, render_report


def test_no_changes_says_so():
    text = render_report(ReadBack({}, Findings()), workbook="bid.xlsx", spec="bid.estimate.yaml")
    assert text == (
        "# Read-back: bid.xlsx → bid.estimate.yaml\n"
        "\n"
        "changes: 0 · need a rate: 0 · formula cells typed over: 0 · untagged rows: 0 · problems: 0\n"
        "\n"
        "No changes: the workbook matches the spec.\n")


def test_every_finding_has_its_section():
    f = Findings(
        changes=["item 2 · 02-100 · 8-inch ductile iron pipe: unit_price 42 → 44.5"],
        needs_rate={"Truck Driver": ["item 2 · 02-100", "item 3 · 02-510"]},
        overwrites=["2 - 8IN MAIN!N29 (SUBTOTAL): typed 35000 over the formula"],
        untagged=["2 - 8IN MAIN row 49: A: Saw cut existing pavement, B: 120"],
        notices=["2 - 8IN MAIN row 21 (item 2 · 02-100): resource 'pipelayer' read as "
                 "'Pipelayer' (same name, different case)"],
        problems=["2 - 8IN MAIN row 37 (item 2 · 02-200): count is blank"])
    text = render_report(ReadBack({}, f), workbook="bid.xlsx", spec="bid.estimate.yaml")
    assert text == "\n".join([
        "# Read-back: bid.xlsx → bid.estimate.yaml",
        "",
        "changes: 1 · need a rate: 1 · formula cells typed over: 1 · untagged rows: 1 · problems: 1",
        "",
        "## Problems — nothing is written until these are fixed",
        "",
        "Fix them in the workbook, save, and read it back again.",
        "",
        "- 2 - 8IN MAIN row 37 (item 2 · 02-200): count is blank",
        "",
        "## Changes",
        "",
        "- item 2 · 02-100 · 8-inch ductile iron pipe: unit_price 42 → 44.5",
        "",
        "## Needs you: resources with no rate",
        "",
        "Applied as typed, but nothing prices them: give each a rate on the Rates sheet "
        "(above the marker row) and read back again. Until then check 2 shows ✗.",
        "",
        "- Truck Driver — used in item 2 · 02-100, item 3 · 02-510",
        "",
        "## Formula cells typed over — ignored, the rebuild restores them",
        "",
        "- 2 - 8IN MAIN!N29 (SUBTOTAL): typed 35000 over the formula",
        "",
        "## Untagged rows — not read (never guessed)",
        "",
        "These rows carry no kind tag, so they were pasted from outside the workbook. "
        "Copy a row of the right kind (crew, cost line) inside a task block and type "
        "the values into it instead.",
        "",
        "- 2 - 8IN MAIN row 49: A: Saw cut existing pavement, B: 120",
        "",
        "## Notices",
        "",
        "- 2 - 8IN MAIN row 21 (item 2 · 02-100): resource 'pipelayer' read as 'Pipelayer' "
        "(same name, different case)",
        ""])
