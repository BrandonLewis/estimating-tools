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


def test_the_packages_section_lists_selections_quote_files_and_problems():
    from estimating_tools.estimate_spec.readback.merge import QuoteWrite
    from estimating_tools.quotes.model import CanonicalQuote
    f = Findings(
        changes=["packages · Hauling · selected Dirt Movers → ARR",
                 "item 2 · 02-100 · Bedding rock: qty 210 → 220"],
        problems=["Sub Valves: selector 'Nobody' is not ARR, CARRY or a quoted vendor "
                  "(vendors: Valve Pros)"],
        quote_edits=["Sub Hauling!K8 (Dirt Movers, item 2 Haul): 16.5 → 15.9 written to dm.json"])
    writes = [QuoteWrite("coastal-trucking--hauling.json",
                         CanonicalQuote(vendor_name="Coastal Trucking", work_package_name="Hauling"),
                         "typed into Sub Hauling")]
    text = render_report(ReadBack({}, f, quote_writes=writes), workbook="b.xlsx", spec="b.yaml")
    assert "\n".join([
        "## Packages",
        "",
        "- packages · Hauling · selected Dirt Movers → ARR",
        "- quote files to write: coastal-trucking--hauling.json (typed into Sub Hauling)",
        "- quote edits written: Sub Hauling!K8 (Dirt Movers, item 2 Haul): 16.5 → 15.9 written to "
        "dm.json",
        "- Sub Valves: selector 'Nobody' is not ARR, CARRY or a quoted vendor (vendors: Valve Pros)",
        ""]) in text
    assert text.index("## Changes") < text.index("## Packages")
    assert "formula cells typed over: 0" in text and "## Formula cells typed over" not in text


def test_quote_writes_alone_are_not_no_changes():
    from estimating_tools.estimate_spec.readback.merge import QuoteWrite
    from estimating_tools.quotes.model import CanonicalQuote
    writes = [QuoteWrite("a--hauling.json",
                         CanonicalQuote(vendor_name="A", work_package_name="Hauling"),
                         "edited in Sub Hauling")]
    text = render_report(ReadBack({}, Findings(), quote_writes=writes), workbook="b", spec="s")
    assert "No changes" not in text and "a--hauling.json" in text
