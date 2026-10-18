from estimating_tools.spreads.model import Cell, Row, Spread, VendorTotal
from estimating_tools.spreads.render import render_spread


def _spread() -> Spread:
    vendors = [
        {"vendor_id": 91, "quote_id": 1, "display_name": "Acme", "is_dbe": False, "status": "received"},
        {"vendor_id": 92, "quote_id": 2, "display_name": "Bravo", "is_dbe": True, "status": "received"},
    ]
    row1 = Row(11, 101, "201", "1", "Base Bid", "Excavation", "CY", 100.0, cells={
        91: Cell(91, "bid", unit_price=10.0, quantity=100.0, extended_amount=1000.0),
        92: Cell(92, "bid", unit_price=9.0, quantity=40.0, extended_amount=360.0, is_partial=True),
    }, best_vendor_id=92, best_unit_price=9.0, best_extended=900.0)
    row2 = Row(12, 102, "202", "2", "Base Bid", "Backfill", "CY", 50.0, cells={
        91: Cell(91, "bid", unit_price=20.0, quantity=50.0, extended_amount=1000.0),
        92: Cell(92, "excluded", is_included=False, exclusion_notes="not our scope"),
    }, best_vendor_id=91, best_unit_price=20.0, best_extended=1000.0)
    return Spread(
        vendors=vendors, rows=[row1, row2],
        vendor_totals=[
            VendorTotal(91, "Acme", False, "received", 2000.0, 2, 2),
            VendorTotal(92, "Bravo", True, "received", 360.0, 1, 2),
        ],
        best_of_breed_total=1900.0,
        outliers=[],
        gaps=[{"vendor_id": 92, "work_package_item_id": 12, "reason": "excluded"}],
    )


def test_render_is_deterministic_markdown_table():
    out = render_spread(_spread())
    expected = (
        "| Item | Description | Unit | Qty | Acme | Bravo* |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 1 (Base Bid) | Excavation | CY | 100 | 10.00 | **9.00**~ |\n"
        "| 2 (Base Bid) | Backfill | CY | 50 | **20.00** | excl |\n"
        "| **Total** |  |  |  | 2000.00 (2/2) | 360.00 (1/2) |\n"
        "\n"
        "Best-of-breed total: 1900.00\n"
        "\n"
        "Gaps:\n"
        "- Bravo: item 2 (Base Bid) — excluded (not our scope)\n"
    )
    assert out == expected


def test_render_includes_outlier_section_when_present():
    s = _spread()
    s.outliers = [{"vendor_id": 91, "work_package_item_id": 11, "unit_price": 10.0, "best_unit_price": 9.0}]
    out = render_spread(s)
    assert "Outliers:" in out
    assert "Acme: item 1 (Base Bid) — 10.00 vs best 9.00" in out


def test_render_escapes_pipe_in_a_cell():
    s = _spread()
    s.vendors[0]["display_name"] = "Ac|me"
    out = render_spread(s)
    assert "Ac\\|me" in out            # the pipe is escaped, so the table is not broken


def test_render_conditions_summary_and_group():
    # reuse the sample-bridge fixture helpers from test_conditions (import them)
    from estimating_tools.spreads.tests.test_conditions import (
        _conditions, _spread)
    from estimating_tools.spreads.conditions import apply_conditions
    out = render_spread(apply_conditions(_spread(), _conditions()))
    assert "Scope group: cages (items 35 (A), 41 (A))" in out
    assert "n/c" in out                              # suppressed best markers
    assert "Obtainable single-vendor total:" in out and "CVR" in out
    assert "NOT OBTAINABLE" in out or "suppressed" in out
    assert "possible scope fold" not in out          # fully tagged fixture


def test_render_unconditioned_spread_unchanged():
    from estimating_tools.spreads.tests.test_conditions import _spread
    out = render_spread(_spread())
    assert "Scope group" not in out and "Obtainable" not in out


def test_render_group_warnings_coverage_gap_and_unresolved_group():
    from estimating_tools.spreads.model import ScopeGroup
    s = _spread()
    s.scope_groups = [ScopeGroup(
        name="cages", basis_row_ids=[11],
        subtotals={91: 1000.0, 92: None}, best_vendor_id=91,
        warnings=["unresolved item key a::99 — not in this package"])]
    s.condition_warnings = [
        {"kind": "unresolved_group", "group": "ghost", "keys": ["z::9"]}]
    out = render_spread(s)
    assert "Scope group: cages (items 1 (Base Bid))" in out
    assert "- Acme: 1000.00 ← best" in out
    assert "- Bravo*: no full-scope coverage" in out
    assert "- warning: unresolved item key a::99 — not in this package" in out
    assert "- unresolved group: ghost (keys: z::9)" in out


def test_render_obtainable_dbe_star_and_mix_none_messages():
    s = _spread()
    s.obtainable_single_vendor = {
        "vendor_id": 92, "display_name": "Bravo", "total": 360.0}
    out = render_spread(s)
    assert "Obtainable single-vendor total: 360.00 (Bravo*)" in out
    assert "Obtainable best mix: none respects acceptance flags" in out
    s.obtainable_best_mix_reason = "coverage"
    assert ("Obtainable best mix: none — coverage incomplete"
            in render_spread(s))


def test_render_zero_winner_best_of_breed():
    s = _spread()
    for r in s.rows:
        r.best_vendor_id = r.best_unit_price = r.best_extended = None
    s.best_of_breed_total = 0.0
    s.condition_warnings = [{"kind": "unknown_acceptance", "vendor_id": 91}]
    out = render_spread(s)
    assert "Best-of-breed: no priced winners" in out
    assert "Best-of-breed total:" not in out
    assert "acceptance unverified for Acme" in out

def test_render_alternate_cell_priced_marked_alt():
    s = _spread()
    s.rows[0].cells[92] = Cell(92, "alternate", unit_price=5.0, quantity=40.0,
                               extended_amount=200.0, is_included=False, is_alternate=True)
    s.has_alternates = True
    out = render_spread(s)
    assert "alt 5.00" in out


def test_render_alternate_cell_unpriced_shows_alt_only():
    s = _spread()
    s.rows[0].cells[92] = Cell(92, "alternate", is_included=False, is_alternate=True)
    s.has_alternates = True
    out = render_spread(s)
    lines = [ln for ln in out.splitlines() if ln.startswith("| 1 (Base Bid)")]
    assert lines and "| alt |" in lines[0]


def test_render_amount_only_alternate_cell_shows_alt_with_extended():
    # no unit_price, but a stored extended amount (amount-only alternate) -> "alt (<amt>)"
    s = _spread()
    s.rows[0].cells[92] = Cell(92, "alternate", unit_price=None, quantity=None,
                               extended_amount=800.0, is_included=False, is_alternate=True)
    s.has_alternates = True
    out = render_spread(s)
    lines = [ln for ln in out.splitlines() if ln.startswith("| 1 (Base Bid)")]
    assert lines and "| alt (800.00) |" in lines[0]


def test_render_with_alternates_row_appears_when_has_alternates():
    # Realistic fixture: a third row (item 3) carries Acme's priced alternate, so
    # items_total grows to 3 and Acme's items_bid_with_alternates (2 base + 1
    # alternate = 3) never exceeds it -- a vendor can never be "bid" on more items
    # than exist.
    s = _spread()
    s.rows.append(Row(13, 103, "203", "3", "Base Bid", "Grading", "CY", 20.0, cells={
        91: Cell(91, "alternate", unit_price=5.0, quantity=20.0, extended_amount=100.0,
                 is_included=False, is_alternate=True),
    }))
    s.has_alternates = True
    for vt in s.vendor_totals:
        vt.items_total = 3
    totals = {vt.vendor_id: vt for vt in s.vendor_totals}
    totals[91].total_with_alternates = totals[91].total + 100.0
    totals[91].items_bid_with_alternates = totals[91].items_bid + 1
    totals[92].total_with_alternates = totals[92].total
    totals[92].items_bid_with_alternates = totals[92].items_bid
    out = render_spread(s)
    assert "**With alternates**" in out
    # appears right after the Total row
    lines = out.splitlines()
    total_idx = next(i for i, ln in enumerate(lines) if ln.startswith("| **Total**"))
    assert lines[total_idx + 1].startswith("| **With alternates**")
    assert "2100.00 (3/3)" in lines[total_idx + 1]


def test_render_no_with_alternates_row_when_flag_false():
    out = render_spread(_spread())
    assert "With alternates" not in out


def test_render_alternate_gap_reason():
    s = _spread()
    s.rows[0].cells[92] = Cell(92, "alternate", unit_price=5.0, quantity=40.0,
                               extended_amount=200.0, is_included=False, is_alternate=True)
    s.has_alternates = True
    s.gaps = [{"vendor_id": 92, "work_package_item_id": 11, "reason": "alternate"}]
    out = render_spread(s)
    assert "- Bravo: item 1 (Base Bid) — alternate only (200.00)\n" in out


def test_render_unpriced_alternate_gap_has_no_price_parens():
    s = _spread()
    s.rows[0].cells[92] = Cell(92, "alternate", is_included=False, is_alternate=True)
    s.has_alternates = True
    s.gaps = [{"vendor_id": 92, "work_package_item_id": 11, "reason": "alternate"}]
    out = render_spread(s)
    assert "- Bravo: item 1 (Base Bid) — alternate only\n" in out


def test_render_mix_alone_triggers_summary_block():
    """Gate window: conditions matched, all flags True, no tags -> no groups,
    no warnings, no annotations; nobody covers the full package -> no
    obtainable single. The computed mix alone must still trigger the
    conditioned summary block rather than the legacy best-of-breed line."""
    from estimating_tools.quotespace.conditions import QuoteConditionRecord
    from estimating_tools.spreads.conditions import apply_conditions
    from estimating_tools.spreads.level import build_spread

    items = [{"id": 1, "project_bid_item_id": 10, "item_number": "10",
              "schedule_name": "A", "item_code": None},
             {"id": 2, "project_bid_item_id": 11, "item_number": "11",
              "schedule_name": "A", "item_code": None}]
    bid_items = [{"id": 10, "description": "One", "unit": "LS", "quantity": "1"},
                 {"id": 11, "description": "Two", "unit": "LS", "quantity": "1"}]
    quotes = [{"id": 20, "vendor_id": 1, "vendor_name": "Alpha"},
              {"id": 21, "vendor_id": 2, "vendor_name": "Bravo"}]
    lines = {20: [{"id": 30, "work_package_item_id": 1, "unit_price": "100",
                   "quantity": "1", "amount": None, "is_included": True}],
             21: [{"id": 31, "work_package_item_id": 2, "unit_price": "200",
                   "quantity": "1", "amount": None, "is_included": True}]}
    conds = [QuoteConditionRecord(work_package={"name": "P"},
                                  vendor={"org_name": n, "bm_vendor_id": vid},
                                  separate_acceptance_permitted=True)
             for n, vid in (("Alpha", 1), ("Bravo", 2))]
    spread = apply_conditions(build_spread(items, bid_items, quotes, lines), conds)
    assert spread.obtainable_best_mix is not None
    assert spread.obtainable_single_vendor is None and not spread.scope_groups
    out = render_spread(spread)
    assert "Obtainable best mix:" in out
    assert not out.rstrip().endswith(
        f"Best-of-breed total: {spread.best_of_breed_total:.2f}")
