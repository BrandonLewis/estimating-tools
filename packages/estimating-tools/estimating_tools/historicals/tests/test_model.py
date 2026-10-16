import json

import pytest

from estimating_tools.historicals.model import (
    OUTCOMES,
    Bidder,
    CanonicalBidTab,
    HistoricalRecord,
    TabItem,
)


def test_outcomes_enum():
    assert OUTCOMES == ("estimated", "bid", "awarded", "actualized", "competitor_bid")


def test_bad_outcome_raises():
    with pytest.raises(ValueError, match="outcome"):
        HistoricalRecord(outcome="won")


def test_payload_drops_empties_keeps_zero():
    rec = HistoricalRecord(
        outcome="awarded", agency="caltrans", bid_item_code="510120",
        project_ref="sr-49-widening-2026", bid_date="2026-05-14",
        region="sierra", bidder="Ghilotti",
        bid_item={"item_number": "23", "description": "STRUCTURAL CONCRETE, BRIDGE"},
        quantity=0.0, unit="CY", unit_price_bid=1650.0,
        source={"kind": "bid_tab", "ref": "03-1J2304"},
    )
    p = rec.to_payload()
    assert p["quantity"] == 0.0          # 0 is a valid observation, must survive
    assert "unit_cost_actual" not in p   # None dropped
    assert "notes" not in p              # "" dropped
    assert p["agency"] == "caltrans"
    json.dumps(p)                        # payload is JSON-serializable


def _tab() -> CanonicalBidTab:
    return CanonicalBidTab(
        agency="caltrans", project_ref="sr-49-widening-2026",
        bid_date="2026-05-14", region="sierra", contract="03-1J2304",
        bidders=[Bidder(name="Ghilotti", rank=1, total_bid=684800.0),
                 Bidder(name="Teichert", rank=2, total_bid=712020.0)],
        items=[TabItem(item_number="2", bid_item_code="510120",
                       description="STRUCTURAL CONCRETE, BRIDGE",
                       quantity=412.0, unit="CY",
                       unit_prices={"Ghilotti": 1650.0, "Teichert": 1710.0})],
    )


def test_tab_roundtrip():
    tab = _tab()
    assert CanonicalBidTab.from_json(tab.to_json()) == tab


def test_to_records_outcomes_and_key():
    recs = _tab().to_records()
    assert len(recs) == 2
    by_bidder = {r.bidder: r for r in recs}
    assert by_bidder["Ghilotti"].outcome == "awarded"       # low bidder
    assert by_bidder["Teichert"].outcome == "competitor_bid"
    r = by_bidder["Ghilotti"]
    assert (r.agency, r.bid_item_code) == ("caltrans", "510120")
    assert r.unit_price_bid == 1650.0
    assert r.source == {"kind": "bid_tab", "ref": "03-1J2304"}
    assert r.bid_item["item_number"] == "2"


def test_to_records_skips_missing_price():
    tab = _tab()
    tab.items[0].unit_prices["Teichert"] = None
    assert [r.bidder for r in tab.to_records()] == ["Ghilotti"]


def test_low_bidder_falls_back_to_totals():
    tab = _tab()
    for b in tab.bidders:
        b.rank = None
    assert tab.low_bidder() == "Ghilotti"
