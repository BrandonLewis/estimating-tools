import pytest

from estimating_tools.historicals.estimates import estimate_to_records
from estimating_tools.importers.model import CanonicalEstimate, LineItem, Schedule


def _estimate(**project_extra):
    project = {"name": "Sample Bridge", "bid_date": "2026-08-05",
               "source": "hcss:sample-bridge.xlsx"}
    project.update(project_extra)
    return CanonicalEstimate(
        project=project,
        schedules=[
            Schedule(name="Base Bid", items=[
                LineItem(item_number="4", description="Structural Concrete",
                         item_code="0310.20", quantity=412.0, unit="CY",
                         unit_price=1650.0,
                         breakdown={"labor": 96000.0, "equipment": 31000.0,
                                    "material": 388000.0, "subcontractor": 0.0}),
                LineItem(item_number="5", description="Unpriced item",
                         quantity=10.0, unit="LS"),          # no unit_price
            ]),
            Schedule(name="Additive Alt 1", items=[
                LineItem(item_number="4", description="Alt concrete",
                         item_code="0310.21", quantity=50.0, unit="CY",
                         unit_price=1700.0),
            ]),
        ],
    )


def test_estimated_outcome_maps_to_unit_cost_estimated():
    records = estimate_to_records(_estimate(), outcome="estimated",
                                  agency="caltrans", region="sierra")
    assert len(records) == 2                       # null-price item skipped
    rec = records[0]
    assert rec.outcome == "estimated"
    assert rec.unit_cost_estimated == 1650.0
    assert rec.unit_price_bid is None
    assert rec.agency == "caltrans"
    assert rec.region == "sierra"
    assert rec.project_ref == "Sample Bridge"
    assert rec.bid_date == "2026-08-05"
    assert rec.quantity == 412.0 and rec.unit == "CY"
    assert rec.bid_item == {"item_number": "4", "schedule": "Base Bid",
                            "description": "Structural Concrete"}
    assert rec.source == {"kind": "own_estimate", "ref": "hcss:sample-bridge.xlsx"}


def test_bid_outcome_maps_to_unit_price_bid():
    records = estimate_to_records(_estimate(), outcome="bid")
    assert records[0].unit_price_bid == 1650.0
    assert records[0].unit_cost_estimated is None


def test_tab_outcomes_rejected():
    for outcome in ("awarded", "competitor_bid", "actualized", "nonsense"):
        with pytest.raises(ValueError):
            estimate_to_records(_estimate(), outcome=outcome)


def test_breakdown_converted_to_keying_schema():
    rec = estimate_to_records(_estimate())[0]
    assert rec.breakdown == [{"cost_code": "0310.20", "labor": 96000.0,
                              "equipment": 31000.0, "material": 388000.0,
                              "sub": 0.0}]
    # item without a breakdown carries none
    assert estimate_to_records(_estimate())[1].breakdown is None


def test_breakdown_without_item_code_omits_cost_code_key():
    # HCSS leaves item_code None when the cost-code column is blank; the
    # cost split is still a real observation — keep it, drop the empty key.
    est = _estimate()
    est.schedules[0].items[0].item_code = None
    rec = estimate_to_records(est)[0]
    assert rec.breakdown == [{"labor": 96000.0, "equipment": 31000.0,
                              "material": 388000.0, "sub": 0.0}]


def test_code_map_schedule_qualified_then_plain_then_item_code():
    code_map = {"Base Bid::4": "510120", "4": "999999"}
    records = estimate_to_records(_estimate(), code_map=code_map)
    assert records[0].bid_item_code == "510120"     # schedule-qualified wins
    assert records[1].bid_item_code == "999999"     # plain item_number fallback
    # no mapping at all -> item_code passes through
    records = estimate_to_records(_estimate())
    assert records[0].bid_item_code == "0310.20"


def test_zero_price_item_is_kept():
    est = _estimate()
    est.schedules[0].items[0].unit_price = 0.0
    records = estimate_to_records(est)
    assert records[0].unit_cost_estimated == 0.0


def test_project_ref_and_bidder_overrides():
    records = estimate_to_records(_estimate(), project_ref="sample-bridge",
                                  bidder="Acme")
    assert records[0].project_ref == "sample-bridge"
    assert records[0].bidder == "Acme"


def test_payloads_are_bulk_create_ready():
    for rec in estimate_to_records(_estimate(), agency="caltrans"):
        payload = rec.to_payload()
        assert payload["outcome"] == "estimated"
        assert "unit_price_bid" not in payload      # unset fields dropped
