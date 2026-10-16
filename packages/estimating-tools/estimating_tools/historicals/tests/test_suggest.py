from datetime import date

from estimating_tools.historicals.suggest import record_price, suggest

AS_OF = date(2026, 8, 5)


def _rec(**kw):
    base = {"outcome": "awarded", "agency": "caltrans", "bid_item_code": "510120",
            "bid_date": "2026-05-14", "region": "sierra", "quantity": 400.0,
            "unit": "CY", "unit_price_bid": 1650.0}
    base.update(kw)
    return base


def test_record_price_by_outcome():
    assert record_price(_rec()) == 1650.0
    assert record_price(_rec(outcome="estimated", unit_price_bid=None,
                             unit_cost_estimated=1400.0)) == 1400.0
    assert record_price(_rec(outcome="actualized", unit_cost_actual=1500.0)) == 1500.0


def test_deterministic():
    records = [_rec(), _rec(bidder="B", unit_price_bid=1700.0)]
    a = suggest(records, quantity=412.0, unit="CY", region="sierra", as_of=AS_OF)
    b = suggest(records, quantity=412.0, unit="CY", region="sierra", as_of=AS_OF)
    assert a == b


def test_newer_outweighs_older():
    old = _rec(bid_date="2021-05-14", unit_price_bid=1000.0)
    new = _rec(bid_date="2026-05-14", unit_price_bid=2000.0)
    result = suggest([old, new], quantity=400.0, unit="CY", as_of=AS_OF)
    assert result["comparables"][0]["unit_price"] == 2000.0   # newer ranked first
    assert result["suggested"]["median"] == 2000.0            # and dominates


def test_unit_mismatch_excluded():
    result = suggest([_rec(), _rec(unit="SY")], quantity=400.0, unit="CY", as_of=AS_OF)
    assert result["n"] == 1
    assert result["excluded"][0]["reason"] == "unit mismatch"


def test_no_history_and_thin_history():
    empty = suggest([], quantity=1.0, unit="CY", as_of=AS_OF)
    assert empty["status"] == "no_history" and "suggested" not in empty
    thin = suggest([_rec()], quantity=400.0, unit="CY", as_of=AS_OF)
    assert thin["status"] == "thin"


def test_median_of_three_known_prices():
    records = [_rec(unit_price_bid=p, bidder=f"b{p}") for p in (1500.0, 1650.0, 1800.0)]
    result = suggest(records, quantity=400.0, unit="CY", region="sierra", as_of=AS_OF)
    assert result["status"] == "ok"
    assert result["suggested"]["p25"] <= result["suggested"]["median"] <= result["suggested"]["p75"]
    assert result["suggested"]["median"] == 1650.0            # equal weights -> middle


def test_all_zero_weights_fall_back_to_unweighted_quantile():
    # Old enough that every weight rounds to 0.0 at 6 decimals: quantiles
    # must fall back to unweighted, not collapse onto the max price.
    records = [_rec(bid_date="1950-06-01", unit_price_bid=p, bidder=f"b{p}")
               for p in (1500.0, 1650.0, 1800.0)]
    result = suggest(records, quantity=400.0, unit="CY", region="sierra", as_of=AS_OF)
    assert all(c["weight"] == 0.0 for c in result["comparables"])
    assert result["suggested"]["p25"] == 1500.0
    assert result["suggested"]["median"] == 1650.0
    assert result["suggested"]["p75"] == 1800.0


def test_negative_quantity_record_does_not_crash():
    records = [_rec(), _rec(bidder="B", unit_price_bid=1700.0),
               _rec(bidder="C", quantity=-400.0, unit_price_bid=1600.0)]
    result = suggest(records, quantity=412.0, unit="CY", region="sierra", as_of=AS_OF)
    assert result["status"] == "ok"
    assert result["n"] == 3
    assert "suggested" in result


def test_non_positive_price_excluded():
    result = suggest([_rec(unit_price_bid=0.0)], quantity=400.0, unit="CY", as_of=AS_OF)
    assert result["n"] == 0
    assert result["excluded"][0]["reason"] == "non-positive price"


def test_missing_unit_excluded_and_comparables_carry_unit():
    result = suggest([_rec(), _rec(unit="", bidder="B")],
                     quantity=400.0, unit="CY", as_of=AS_OF)
    assert result["n"] == 1
    assert result["excluded"][0]["reason"] == "missing unit"
    assert result["comparables"][0]["unit"] == "CY"


def test_region_match_case_insensitive():
    mixed = suggest([_rec(region="Sierra")], quantity=400.0, unit="CY",
                    region="sierra", as_of=AS_OF)
    exact = suggest([_rec()], quantity=400.0, unit="CY",
                    region="sierra", as_of=AS_OF)
    assert mixed["comparables"][0]["weight"] == exact["comparables"][0]["weight"]
