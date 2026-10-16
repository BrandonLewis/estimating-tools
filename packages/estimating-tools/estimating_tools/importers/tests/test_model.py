from estimating_tools.importers.model import CanonicalEstimate, LineItem, Schedule


def _sample() -> CanonicalEstimate:
    return CanonicalEstimate(
        project={"name": "Demo", "source": "HCSS HeavyBid"},
        schedules=[
            Schedule(name="Base Bid", items=[
                LineItem(item_number="1", description="Mobilization", item_code="070-010",
                         quantity=1.0, unit="LS", unit_price=50000.0, total=50000.0),
                LineItem(item_number="2", description="Clearing", quantity=3.0, unit="AC"),
            ]),
            Schedule(name="Additive Alt 1", items=[
                LineItem(item_number="A1", description="Extra paving", quantity=100.0, unit="SY"),
            ]),
        ],
    )


def test_roundtrip_through_dict_and_json():
    est = _sample()
    again = CanonicalEstimate.from_dict(est.to_dict())
    assert again == est
    assert CanonicalEstimate.from_json(est.to_json()) == est


def test_item_code_optional_absent_is_none():
    est = _sample()
    d = est.to_dict()
    assert d["schedules"][0]["items"][0]["item_code"] == "070-010"
    assert d["schedules"][0]["items"][1].get("item_code") is None


def test_multi_schedule_preserved():
    est = _sample()
    d = est.to_dict()
    assert [s["name"] for s in d["schedules"]] == ["Base Bid", "Additive Alt 1"]
    assert len(d["schedules"][0]["items"]) == 2
