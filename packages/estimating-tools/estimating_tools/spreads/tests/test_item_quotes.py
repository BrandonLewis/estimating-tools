from estimating_tools.spreads.item_quotes import build_item_spread
from estimating_tools.spreads.model import Spread
from estimating_tools.spreads.render import render_spread


def _bid_items():
    return [
        {"id": 101, "item_number": "1", "item_code": "201", "description": "Excavation", "unit": "CY", "quantity": "100", "schedule_name": "Base Bid"},
        {"id": 102, "item_number": "2", "item_code": "202", "description": "Backfill", "unit": "CY", "quantity": "50", "schedule_name": "Base Bid"},
        {"id": 103, "item_number": "3", "item_code": "203", "description": "Paving", "unit": "SY", "quantity": "0", "schedule_name": "Base Bid"},
    ]


def _quotes():
    # item 101: Acme 1000 vs Bravo 900 (Bravo best); item 102: only Acme 1200;
    # item 103: full_qty 0 -> fallback. item 101 Acme has an OLDER revision (1500) that must lose.
    return [
        {"id": 1, "vendor": "Acme", "vendor_id": 91, "amount": "1500", "status": "received", "received_date": "2026-06-01", "bid_item_id": 101, "item_code": "201"},
        {"id": 2, "vendor": "Acme", "vendor_id": 91, "amount": "1000", "status": "received", "received_date": "2026-06-10", "bid_item_id": 101, "item_code": "201"},
        {"id": 3, "vendor": "Bravo", "vendor_id": 92, "amount": "900", "status": "received", "received_date": "2026-06-05", "bid_item_id": 101, "item_code": "201"},
        {"id": 4, "vendor": "Acme", "vendor_id": 91, "amount": "1200", "status": "received", "received_date": "2026-06-02", "bid_item_id": 102, "item_code": "202"},
        {"id": 5, "vendor": "Bravo", "vendor_id": 92, "amount": "400", "status": "received", "received_date": "2026-06-03", "bid_item_id": 103, "item_code": "203"},
    ]


def test_reshapes_into_spread_rows_per_quoted_item():
    s = build_item_spread(_bid_items(), _quotes())
    assert isinstance(s, Spread)
    # rows are the quoted bid items (101, 102, 103), keyed/identified by item number+schedule
    assert [(r.project_bid_item_id, r.item_number) for r in s.rows] == [(101, "1"), (102, "2"), (103, "3")]
    # item 101 cell for Acme: unit_price = 1000/100 = 10.0, extended = 1000
    row101 = s.rows[0]
    assert row101.cells[91].unit_price == 10.0 and row101.cells[91].extended_amount == 1000.0
    # Bravo 900/100 = 9.0 -> Bravo is best on item 101
    assert row101.best_vendor_id == 92 and row101.best_unit_price == 9.0


def test_dedupes_most_recent_received_date_wins():
    s = build_item_spread(_bid_items(), _quotes())
    row101 = s.rows[0]
    # Acme had 1500 (2026-06-01) AND 1000 (2026-06-10) on item 101 -> the most RECENT (1000) survives
    assert row101.cells[91].extended_amount == 1000.0   # not 1500


def test_quantity_fallback_when_zero_or_none():
    s = build_item_spread(_bid_items(), _quotes())
    # item 103 has quantity "0" -> fallback unit_price = amount (400), quantity 1, extended 400
    row103 = s.rows[2]
    assert row103.cells[92].unit_price == 400.0
    assert row103.cells[92].quantity == 1.0
    assert row103.cells[92].extended_amount == 400.0


def test_only_quoted_items_are_rows_and_totals_from_core():
    bid_items = _bid_items() + [
        {"id": 104, "item_number": "4", "item_code": "204", "description": "Striping", "unit": "LF", "quantity": "10", "schedule_name": "Base Bid"},
    ]
    s = build_item_spread(bid_items, _quotes())  # item 104 has no quote
    assert all(r.project_bid_item_id != 104 for r in s.rows)   # un-quoted item is not a row
    # per-vendor totals came out of build_spread: Acme = 1000 (item101) + 1200 (item102) = 2200
    totals = {vt.vendor_id: vt.total for vt in s.vendor_totals}
    assert totals[91] == 2200.0


def test_quantity_fallback_when_none():
    bid_items = [{"id": 201, "item_number": "9", "item_code": "209", "description": "Mobilization", "unit": "LS", "quantity": None, "schedule_name": "Base Bid"}]
    quotes = [{"id": 9, "vendor": "Acme", "vendor_id": 91, "amount": "5000", "status": "received", "received_date": "2026-06-01", "bid_item_id": 201, "item_code": "209"}]
    s = build_item_spread(bid_items, quotes)
    cell = s.rows[0].cells[91]
    assert cell.unit_price == 5000.0 and cell.quantity == 1.0 and cell.extended_amount == 5000.0


def test_dedupe_equal_date_tie_breaks_lowest_amount():
    # Same vendor, same item, SAME received_date, different amounts -> the LOWER wins.
    bid_items = [{"id": 301, "item_number": "1", "item_code": "201", "description": "Excavation", "unit": "CY", "quantity": "100", "schedule_name": "Base Bid"}]
    quotes = [
        {"id": 1, "vendor": "Acme", "vendor_id": 91, "amount": "1000", "status": "received", "received_date": "2026-06-05", "bid_item_id": 301, "item_code": "201"},
        {"id": 2, "vendor": "Acme", "vendor_id": 91, "amount": "800", "status": "received", "received_date": "2026-06-05", "bid_item_id": 301, "item_code": "201"},
    ]
    s = build_item_spread(bid_items, quotes)
    # tie on date -> lower amount (800) survives, not 1000
    assert s.rows[0].cells[91].extended_amount == 800.0


def test_dbe_vendor_carries_through_and_renders_star():
    # A per-item quote row carrying is_dbe: True must flow into the spread's vendor
    # column (same key convention as level.py quote headers) and render the "*" star.
    bid_items = [{"id": 401, "item_number": "1", "item_code": "201", "description": "Excavation", "unit": "CY", "quantity": "100", "schedule_name": "Base Bid"}]
    quotes = [
        {"id": 1, "vendor": "Acme", "vendor_id": 91, "amount": "1000", "status": "received", "received_date": "2026-06-01", "bid_item_id": 401, "item_code": "201", "is_dbe": True},
        {"id": 2, "vendor": "Bravo", "vendor_id": 92, "amount": "900", "status": "received", "received_date": "2026-06-01", "bid_item_id": 401, "item_code": "201"},
    ]
    s = build_item_spread(bid_items, quotes)
    dbe_by_vendor = {v["vendor_id"]: v["is_dbe"] for v in s.vendors}
    assert dbe_by_vendor[91] is True
    assert dbe_by_vendor[92] is False          # absence tolerated -> False
    totals = {vt.vendor_id: vt for vt in s.vendor_totals}
    assert totals[91].is_dbe is True and totals[92].is_dbe is False
    rendered = render_spread(s)
    assert "Acme*" in rendered
    assert "Bravo*" not in rendered


def test_dbe_true_on_any_of_a_vendors_quotes_wins():
    # DBE is a vendor-level fact; if any of the vendor's quote rows carries it, keep it
    # (even when the first-seen row omits the key).
    bid_items = [
        {"id": 501, "item_number": "1", "item_code": "201", "description": "Excavation", "unit": "CY", "quantity": "100", "schedule_name": "Base Bid"},
        {"id": 502, "item_number": "2", "item_code": "202", "description": "Backfill", "unit": "CY", "quantity": "50", "schedule_name": "Base Bid"},
    ]
    quotes = [
        {"id": 1, "vendor": "Acme", "vendor_id": 91, "amount": "1000", "status": "received", "received_date": "2026-06-01", "bid_item_id": 501, "item_code": "201"},
        {"id": 2, "vendor": "Acme", "vendor_id": 91, "amount": "500", "status": "received", "received_date": "2026-06-01", "bid_item_id": 502, "item_code": "202", "is_dbe": True},
    ]
    s = build_item_spread(bid_items, quotes)
    assert {v["vendor_id"]: v["is_dbe"] for v in s.vendors}[91] is True


def test_dedupe_missing_received_date_loses_to_dated():
    # One quote has no received_date (sorts oldest) and a LOWER amount; the DATED one must still win.
    bid_items = [{"id": 302, "item_number": "2", "item_code": "202", "description": "Backfill", "unit": "CY", "quantity": "50", "schedule_name": "Base Bid"}]
    quotes = [
        {"id": 1, "vendor": "Acme", "vendor_id": 91, "amount": "100", "status": "received", "received_date": None, "bid_item_id": 302, "item_code": "202"},
        {"id": 2, "vendor": "Acme", "vendor_id": 91, "amount": "900", "status": "received", "received_date": "2026-06-01", "bid_item_id": 302, "item_code": "202"},
    ]
    s = build_item_spread(bid_items, quotes)
    # the dated quote (900) wins over the undated one (100), because missing date sorts oldest
    assert s.rows[0].cells[91].extended_amount == 900.0
