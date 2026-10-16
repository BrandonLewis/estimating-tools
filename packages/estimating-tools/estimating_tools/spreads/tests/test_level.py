from estimating_tools.spreads.level import build_spread, _num, OUTLIER_FACTOR
from estimating_tools.spreads.model import Spread


# --- fixtures: minimal MCP-shaped dicts ---------------------------------
def _items():
    # work-package items (rows). id = work_package_item_id.
    return [
        {"id": 11, "project_bid_item_id": 101, "item_code": "201", "item_number": "1", "schedule_name": "Base Bid"},
        {"id": 12, "project_bid_item_id": 102, "item_code": "202", "item_number": "2", "schedule_name": "Base Bid"},
        # same item_number "1" in a different schedule -> distinct row
        {"id": 13, "project_bid_item_id": 103, "item_code": "201", "item_number": "1", "schedule_name": "Alt 1"},
    ]


def _bid_items():
    return [
        {"id": 101, "item_number": "1", "item_code": "201", "description": "Excavation", "unit": "CY", "quantity": "100", "schedule_name": "Base Bid"},
        {"id": 102, "item_number": "2", "item_code": "202", "description": "Backfill", "unit": "CY", "quantity": "50", "schedule_name": "Base Bid"},
        {"id": 103, "item_number": "1", "item_code": "201", "description": "Excavation", "unit": "CY", "quantity": "40", "schedule_name": "Alt 1"},
    ]


def _quotes():
    return [
        {"id": 1, "vendor_display_name": "Acme", "vendor_name": "Acme", "vendor_id": 91, "is_dbe": False, "status": "received", "amount": "0"},
        {"id": 2, "vendor_display_name": "Bravo", "vendor_name": "Bravo", "vendor_id": 92, "is_dbe": True, "status": "received", "amount": "0"},
    ]


def _lines_by_quote():
    return {
        1: [  # Acme: full bids on items 11 & 12, no line for 13
            {"id": 1001, "quote_id": 1, "work_package_item_id": 11, "unit_price": "10", "quantity": "100", "amount": "1000", "is_included": True, "exclusion_notes": ""},
            {"id": 1002, "quote_id": 1, "work_package_item_id": 12, "unit_price": "20", "quantity": "50", "amount": "1000", "is_included": True, "exclusion_notes": ""},
        ],
        2: [  # Bravo: cheaper rate on 11 but PARTIAL qty (40<100); excluded on 12; outlier-priced on 13
            {"id": 2001, "quote_id": 2, "work_package_item_id": 11, "unit_price": "9", "quantity": "40", "amount": None, "is_included": True, "exclusion_notes": ""},
            {"id": 2002, "quote_id": 2, "work_package_item_id": 12, "unit_price": "0", "quantity": "0", "amount": None, "is_included": False, "exclusion_notes": "not our scope"},
            {"id": 2003, "quote_id": 2, "work_package_item_id": 13, "unit_price": "100", "quantity": "40", "amount": None, "is_included": True, "exclusion_notes": ""},
        ],
    }


def test_returns_spread_with_rows_keyed_per_item_incl_cross_schedule():
    s = build_spread(_items(), _bid_items(), _quotes(), _lines_by_quote())
    assert isinstance(s, Spread)
    # 3 distinct rows; the same item_number "1" appears in Base Bid AND Alt 1
    keyed = [(r.item_number, r.schedule_name) for r in s.rows]
    assert keyed == [("1", "Base Bid"), ("2", "Base Bid"), ("1", "Alt 1")]
    # rows enriched from bid_items
    assert s.rows[0].description == "Excavation" and s.rows[0].unit == "CY" and s.rows[0].quantity == 100.0


def test_best_per_item_on_unit_price_and_partial_flag():
    s = build_spread(_items(), _bid_items(), _quotes(), _lines_by_quote())
    row11 = s.rows[0]
    # Bravo (9) beats Acme (10) on unit_price even though Bravo bid only 40 of 100
    assert row11.best_vendor_id == 92
    assert row11.best_unit_price == 9.0
    # best-of-breed extended uses the FULL row quantity (100), not Bravo's 40
    assert row11.best_extended == 900.0
    # Bravo's cell on row11 is a partial bid
    assert row11.cells[92].is_partial is True
    assert row11.cells[92].extended_amount == 360.0  # 9 * 40 (its own qty)


def test_no_bid_and_excluded_are_gaps_not_zero():
    s = build_spread(_items(), _bid_items(), _quotes(), _lines_by_quote())
    row12, row13 = s.rows[1], s.rows[2]
    assert row12.cells[92].status == "excluded"      # Bravo excluded item 12
    assert row13.cells[91].status == "no_bid"        # Acme has no line for item 13
    # excluded/no_bid never become a candidate for best
    assert row12.best_vendor_id == 91                # only Acme bid item 12
    # gaps list names the missing coverage
    gap_pairs = {(g["vendor_id"], g["work_package_item_id"]) for g in s.gaps}
    assert (91, 13) in gap_pairs and (92, 12) in gap_pairs


def test_vendor_totals_coverage_and_best_of_breed():
    s = build_spread(_items(), _bid_items(), _quotes(), _lines_by_quote())
    totals = {vt.vendor_id: vt for vt in s.vendor_totals}
    # Acme: 1000 + 1000 = 2000 over 2 of 3 items
    assert totals[91].total == 2000.0 and totals[91].items_bid == 2 and totals[91].items_total == 3
    # Bravo: 360 (item11 partial) + 4000 (item13 100*40) = 4360 over 2 of 3 (item12 excluded)
    assert totals[92].total == 4360.0 and totals[92].items_bid == 2
    # best-of-breed: item11 9*100=900, item12 20*50=1000, item13 100*40=4000 -> 5900
    assert s.best_of_breed_total == 5900.0


def test_outlier_flagged_at_factor():
    s = build_spread(_items(), _bid_items(), _quotes(), _lines_by_quote())
    assert OUTLIER_FACTOR == 1.5
    # item13 only has Bravo (100) -> it is its own best, not an outlier
    # construct an outlier: add a second bidder on item13 far above best
    lines = _lines_by_quote()
    quotes = _quotes() + [{"id": 3, "vendor_display_name": "Costly", "vendor_name": "Costly", "vendor_id": 93, "is_dbe": False, "status": "received", "amount": "0"}]
    lines[3] = [{"id": 3001, "quote_id": 3, "work_package_item_id": 13, "unit_price": "60", "quantity": "40", "amount": None, "is_included": True, "exclusion_notes": ""}]
    s2 = build_spread(_items(), _bid_items(), quotes, lines)
    # best on item13 is now Costly? no: 60 < 100, so Costly best (60); Bravo (100) >= 1.5*60=90 -> outlier
    outlier_keys = {(o["vendor_id"], o["work_package_item_id"]) for o in s2.outliers}
    assert (92, 13) in outlier_keys


def test_best_ranks_on_unit_price_not_extended_amount():
    # Vendor A: cheaper unit rate (10) but huge qty -> high extended (2000).
    # Vendor B: pricier unit rate (12) but tiny qty -> low extended (120).
    # Best must be A (lowest unit_price); ranking on extended would wrongly pick B.
    items = [{"id": 11, "project_bid_item_id": 101, "item_code": "201", "item_number": "1", "schedule_name": "Base Bid"}]
    bid_items = [{"id": 101, "item_number": "1", "item_code": "201", "description": "Excavation", "unit": "CY", "quantity": "200", "schedule_name": "Base Bid"}]
    quotes = [
        {"id": 1, "vendor_display_name": "A", "vendor_name": "A", "vendor_id": 91, "is_dbe": False, "status": "received", "amount": "0"},
        {"id": 2, "vendor_display_name": "B", "vendor_name": "B", "vendor_id": 92, "is_dbe": False, "status": "received", "amount": "0"},
    ]
    lines_by_quote = {
        1: [{"id": 1001, "quote_id": 1, "work_package_item_id": 11, "unit_price": "10", "quantity": "200", "amount": None, "is_included": True, "exclusion_notes": ""}],
        2: [{"id": 2001, "quote_id": 2, "work_package_item_id": 11, "unit_price": "12", "quantity": "10", "amount": None, "is_included": True, "exclusion_notes": ""}],
    }
    s = build_spread(items, bid_items, quotes, lines_by_quote)
    row = s.rows[0]
    assert row.best_vendor_id == 91          # the lower UNIT price, despite higher extended (2000 > 120)
    assert row.best_unit_price == 10.0
    assert row.cells[91].extended_amount == 2000.0 and row.cells[92].extended_amount == 120.0


def test_extended_prefers_unit_price_times_quantity_over_stored_amount():
    items = [{"id": 11, "project_bid_item_id": 101, "item_code": "201", "item_number": "1", "schedule_name": "Base Bid"}]
    bid_items = [{"id": 101, "item_number": "1", "item_code": "201", "description": "Excavation", "unit": "CY", "quantity": "100", "schedule_name": "Base Bid"}]
    quotes = [{"id": 1, "vendor_display_name": "A", "vendor_name": "A", "vendor_id": 91, "is_dbe": False, "status": "received", "amount": "0"}]
    # stored amount (999) disagrees with unit_price*quantity (10*100=1000); computed must win
    lines_by_quote = {1: [{"id": 1001, "quote_id": 1, "work_package_item_id": 11, "unit_price": "10", "quantity": "100", "amount": "999", "is_included": True, "exclusion_notes": ""}]}
    s = build_spread(items, bid_items, quotes, lines_by_quote)
    assert s.rows[0].cells[91].extended_amount == 1000.0     # NOT 999 (the stored amount)


def test_num_parses_or_none():
    assert _num("100") == 100.0
    assert _num(None) is None
    assert _num("") is None
    assert _num("N/A") is None      # non-numeric string -> None, no crash


def test_amount_only_included_line_totals_but_is_never_best():
    items = [{"id": 11, "project_bid_item_id": 101, "item_code": "201", "item_number": "1", "schedule_name": "Base Bid"}]
    bid_items = [{"id": 101, "item_number": "1", "item_code": "201", "description": "Excavation", "unit": "CY", "quantity": "100", "schedule_name": "Base Bid"}]
    quotes = [
        {"id": 1, "vendor_display_name": "A", "vendor_name": "A", "vendor_id": 91, "is_dbe": False, "status": "received", "amount": "0"},
        {"id": 2, "vendor_display_name": "B", "vendor_name": "B", "vendor_id": 92, "is_dbe": False, "status": "received", "amount": "0"},
    ]
    lines_by_quote = {
        # A: normal priced line
        1: [{"id": 1001, "quote_id": 1, "work_package_item_id": 11, "unit_price": "10", "quantity": "100", "amount": None, "is_included": True, "exclusion_notes": ""}],
        # B: amount-only included line (null unit_price) -> totals via amount, but never best
        2: [{"id": 2001, "quote_id": 2, "work_package_item_id": 11, "unit_price": None, "quantity": None, "amount": "800", "is_included": True, "exclusion_notes": ""}],
    }
    s = build_spread(items, bid_items, quotes, lines_by_quote)
    row = s.rows[0]
    # B's amount-only cell totals via its stored amount and counts toward coverage
    totals = {vt.vendor_id: vt for vt in s.vendor_totals}
    assert row.cells[92].status == "bid" and row.cells[92].extended_amount == 800.0
    assert totals[92].total == 800.0 and totals[92].items_bid == 1
    # ...but it is NEVER the per-item best (best ranks on unit_price; B has none)
    assert row.best_vendor_id == 91 and row.best_unit_price == 10.0


def test_cell_carries_quote_line_item_id():
    s = build_spread(_items(), _bid_items(), _quotes(), _lines_by_quote())
    row11 = s.rows[0]
    # Acme bid line id 1001 on item 11; Bravo bid line id 2001
    assert row11.cells[91].quote_line_item_id == 1001
    assert row11.cells[92].quote_line_item_id == 2001
    # excluded cell still carries its line id; no_bid carries None
    row12, row13 = s.rows[1], s.rows[2]
    assert row12.cells[92].quote_line_item_id == 2002      # Bravo excluded line on item 12
    assert row13.cells[91].quote_line_item_id is None      # Acme no_bid on item 13
