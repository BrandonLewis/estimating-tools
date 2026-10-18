from estimating_tools.spreads.model import Cell, Row, Spread
from estimating_tools.spreads.award import (
    AwardEntry, AwardPlan, ItemCoverage, plan_award, render_award_plan,
)


def _spread() -> Spread:
    # 2 items; item 11 full qty 100, item 12 full qty 50.
    rows = [
        Row(11, 101, "201", "1", "Base Bid", "Excavation", "CY", 100.0, cells={
            91: Cell(91, "bid", quote_line_item_id=1001, unit_price=10.0, quantity=100.0, extended_amount=1000.0),
            92: Cell(92, "bid", quote_line_item_id=2001, unit_price=9.0, quantity=40.0, extended_amount=360.0, is_partial=True),
        }),
        Row(12, 102, "202", "2", "Base Bid", "Backfill", "CY", 50.0, cells={
            91: Cell(91, "bid", quote_line_item_id=1002, unit_price=20.0, quantity=50.0, extended_amount=1000.0),
            92: Cell(92, "excluded", quote_line_item_id=2002, is_included=False, exclusion_notes="not our scope"),
        }),
    ]
    vendors = [
        {"vendor_id": 91, "quote_id": 1, "display_name": "Acme", "is_dbe": False, "status": "received"},
        {"vendor_id": 92, "quote_id": 2, "display_name": "Bravo", "is_dbe": True, "status": "received"},
    ]
    return Spread(vendors=vendors, rows=rows)


def test_vendor_strategy_full_and_partial_allocation_types():
    plan = plan_award(_spread(), "vendor", vendor_id=91)
    assert isinstance(plan, AwardPlan) and plan.strategy == "vendor"
    # Acme bid both items fully -> two "full" entries
    assert [(e.work_package_item_id, e.allocation_type, e.value, e.quote_line_item_id) for e in plan.entries] == [
        (11, "full", None, 1001),
        (12, "full", None, 1002),
    ]
    # both items fully allocated -> no remainder
    cov = {c.work_package_item_id: c for c in plan.coverage}
    assert cov[11].remainder == 0.0 and cov[11].fully_allocated is True
    assert cov[12].remainder == 0.0 and cov[12].fully_allocated is True


def test_vendor_strategy_partial_leaves_self_perform_remainder():
    plan = plan_award(_spread(), "vendor", vendor_id=92)
    # Bravo: item 11 partial (40 of 100); item 12 excluded -> not awarded
    assert [(e.work_package_item_id, e.allocation_type, e.value) for e in plan.entries] == [
        (11, "quantity", 40.0),
    ]
    cov = {c.work_package_item_id: c for c in plan.coverage}
    assert cov[11].allocated_quantity == 40.0 and cov[11].remainder == 60.0 and cov[11].fully_allocated is False
    # item 12 had no award from Bravo -> coverage with 0 allocated, full remainder
    assert cov[12].allocated_quantity == 0.0 and cov[12].remainder == 50.0


def test_manual_strategy_multiple_subs_on_one_item():
    # split item 11 between Acme (line 1001) and Bravo (line 2001)
    selection = [
        {"work_package_item_id": 11, "vendor_id": 91},
        {"work_package_item_id": 11, "vendor_id": 92},
    ]
    plan = plan_award(_spread(), "manual", selection=selection)
    # two entries for item 11
    assert [(e.work_package_item_id, e.vendor_id, e.allocation_type, e.value) for e in plan.entries] == [
        (11, 91, "full", None),     # Acme's cell covers full qty -> "full"
        (11, 92, "quantity", 40.0), # Bravo partial
    ]
    cov = {c.work_package_item_id: c for c in plan.coverage}
    # allocated = 100 (Acme full) + 40 (Bravo) = 140 -> over the full 100; remainder clamps to 0
    assert cov[11].allocated_quantity == 140.0 and cov[11].remainder == 0.0 and cov[11].fully_allocated is True


def test_excluded_and_missing_selection_not_awarded():
    # manual selection naming Bravo on item 12 (excluded) -> skipped, noted in coverage
    plan = plan_award(_spread(), "manual", selection=[{"work_package_item_id": 12, "vendor_id": 92}])
    assert plan.entries == []     # Bravo is excluded on item 12 -> no award
    cov = {c.work_package_item_id: c for c in plan.coverage}
    assert cov[12].allocated_quantity == 0.0 and cov[12].remainder == 50.0


def _plan() -> AwardPlan:
    return AwardPlan(
        entries=[
            AwardEntry(11, 1001, 91, "Acme", "1 (Base Bid)", "full", None, 10.0, 1000.0),
            AwardEntry(11, 2001, 92, "Bravo", "1 (Base Bid)", "quantity", 40.0, 9.0, 360.0),
        ],
        coverage=[
            ItemCoverage(11, "1 (Base Bid)", 100.0, 140.0, 0.0, True),
            ItemCoverage(12, "2 (Base Bid)", 50.0, 0.0, 50.0, False),
        ],
        strategy="manual",
        selection=[{"work_package_item_id": 11, "vendor_id": 91}],
    )


def test_render_award_plan_is_deterministic_markdown():
    out = render_award_plan(_plan())
    expected = (
        "Award plan (strategy: manual)\n"
        "\n"
        "| Item | Vendor | Allocation | Qty | Unit price |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 1 (Base Bid) | Acme | full |  | 10.00 |\n"
        "| 1 (Base Bid) | Bravo | quantity | 40 | 9.00 |\n"
        "\n"
        "Coverage (remainder = self-perform / unallocated):\n"
        "- 1 (Base Bid): allocated 140 of 100 — remainder 0\n"
        "- 2 (Base Bid): allocated 0 of 50 — remainder 50 (self-perform)\n"
    )
    assert out == expected


def test_no_bid_cell_is_never_awarded():
    # A vendor with a no_bid cell on an item must not be awarded under either strategy.
    rows = [
        Row(11, 101, "201", "1", "Base Bid", "Excavation", "CY", 100.0, cells={
            91: Cell(91, "bid", quote_line_item_id=1001, unit_price=10.0, quantity=100.0, extended_amount=1000.0),
            92: Cell(92, "no_bid"),   # Bravo did not bid item 11
        }),
    ]
    vendors = [
        {"vendor_id": 91, "quote_id": 1, "display_name": "Acme", "is_dbe": False, "status": "received"},
        {"vendor_id": 92, "quote_id": 2, "display_name": "Bravo", "is_dbe": True, "status": "received"},
    ]
    spread = Spread(vendors=vendors, rows=rows)
    # vendor strategy for the non-bidding vendor -> no entries
    assert plan_award(spread, "vendor", vendor_id=92).entries == []
    # manual selection naming the non-bidding vendor on that item -> no entries
    assert plan_award(spread, "manual", selection=[{"work_package_item_id": 11, "vendor_id": 92}]).entries == []


import pytest


def test_vendor_strategy_requires_vendor_id():
    with pytest.raises(ValueError):
        plan_award(_spread(), "vendor")        # vendor_id missing


def test_manual_strategy_requires_selection():
    with pytest.raises(ValueError):
        plan_award(_spread(), "manual")        # selection missing


def test_manual_strategy_rejects_malformed_selection():
    with pytest.raises(ValueError):
        plan_award(_spread(), "manual", selection=[{"vendor_id": 91}])   # no work_package_item_id


def test_alternate_cell_is_never_awarded():
    # A priced alternate cell is not in the base; awarding must skip it under
    # either strategy, even though it has a quote_line_item_id and a price
    # (accepting it requires accept_alternate=true on the MCP allocation call,
    # outside plan_award's scope -- see the apply-quotes skill).
    rows = [
        Row(11, 101, "201", "1", "Base Bid", "Excavation", "CY", 100.0, cells={
            91: Cell(91, "bid", quote_line_item_id=1001, unit_price=10.0, quantity=100.0, extended_amount=1000.0),
            92: Cell(92, "alternate", quote_line_item_id=2001, unit_price=5.0, quantity=100.0,
                     extended_amount=500.0, is_included=False, is_alternate=True),
        }),
    ]
    vendors = [
        {"vendor_id": 91, "quote_id": 1, "display_name": "Acme", "is_dbe": False, "status": "received"},
        {"vendor_id": 92, "quote_id": 2, "display_name": "Bravo", "is_dbe": True, "status": "received"},
    ]
    spread = Spread(vendors=vendors, rows=rows)
    assert plan_award(spread, "vendor", vendor_id=92).entries == []
    assert plan_award(spread, "manual", selection=[{"work_package_item_id": 11, "vendor_id": 92}]).entries == []


def test_awarding_bid_cell_without_line_id_raises():
    rows = [Row(11, 101, "201", "1", "Base Bid", "Excavation", "CY", 100.0, cells={
        91: Cell(91, "bid", quote_line_item_id=None, unit_price=10.0, quantity=100.0, extended_amount=1000.0),
    })]
    vendors = [{"vendor_id": 91, "quote_id": 1, "display_name": "Acme", "is_dbe": False, "status": "received"}]
    with pytest.raises(ValueError):
        plan_award(Spread(vendors=vendors, rows=rows), "vendor", vendor_id=91)
