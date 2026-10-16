from estimating_tools.importers.model import CanonicalEstimate, LineItem, Schedule
from estimating_tools.importers.pricing import PricingPlan, plan_pricing


def _sample() -> CanonicalEstimate:
    return CanonicalEstimate(
        project={"name": "Demo Job", "source": "HCSS HeavyBid"},
        schedules=[
            Schedule(name="Base Bid", items=[
                LineItem(item_number="1", description="Mobilization", quantity=1.0, unit="LS", unit_price=50000.0),
                LineItem(item_number="2", description="Clearing", quantity=3.0, unit="AC"),  # no price -> omitted
            ]),
            Schedule(name="Additive Alt 1", items=[
                LineItem(item_number="A1", description="Extra paving", quantity=100.0, unit="SY", unit_price=42.5),
            ]),
        ],
    )


def test_estimate_name_derived_from_project():
    plan = plan_pricing(_sample())
    assert isinstance(plan, PricingPlan)
    assert plan.estimate_name == "Demo Job — Imported Estimate"


def test_only_priced_items_with_provenance_and_confidence():
    plan = plan_pricing(_sample())
    # item "2" (no unit_price) is omitted; "1" and "A1" are priced
    assert [it["item_number"] for it in plan.items] == ["1", "A1"]
    first = plan.items[0]
    assert first["unit_price"] == 50000.0
    assert first["confidence_level"] == "medium"
    assert first["notes"] == "imported from HCSS HeavyBid"   # source from project.source
    assert first["schedule_name"] == "Base Bid"              # schedule context carried through


def test_explicit_source_overrides_and_no_source_blank_notes():
    plan = plan_pricing(_sample(), source="Manual")
    assert plan.items[0]["notes"] == "imported from Manual"
    no_src = CanonicalEstimate(project={"name": "P"},
                               schedules=[Schedule(name="Base Bid",
                                          items=[LineItem(item_number="1", unit_price=10.0)])])
    assert plan_pricing(no_src).items[0]["notes"] == ""       # no source -> blank notes


def test_all_null_price_yields_empty_items():
    est = CanonicalEstimate(project={"name": "P"},
                            schedules=[Schedule(name="Base Bid",
                                       items=[LineItem(item_number="1"), LineItem(item_number="2")])])
    assert plan_pricing(est).items == []


def test_same_item_number_across_schedules_kept_with_schedule_name():
    est = CanonicalEstimate(
        project={"name": "P", "source": "X"},
        schedules=[
            Schedule(name="Base Bid", items=[LineItem(item_number="1", unit_price=10.0)]),
            Schedule(name="Additive Alt 1", items=[LineItem(item_number="1", unit_price=20.0)]),
        ],
    )
    items = plan_pricing(est).items
    assert [(i["item_number"], i["schedule_name"], i["unit_price"]) for i in items] == [
        ("1", "Base Bid", 10.0),
        ("1", "Additive Alt 1", 20.0),
    ]


# ---- render_pricing_plan tests (Phase 3) ----

from estimating_tools.importers.pricing import PricingPlan, render_pricing_plan


def test_render_pricing_plan_shape():
    plan = PricingPlan(
        estimate_name="Riverbend Ph. 1 — Imported Estimate",
        items=[{
            "schedule_name": "Base Bid",
            "item_number": "1",
            "unit_price": 125.50,
            "confidence_level": "medium",
            "notes": "imported from HeavyBid",
        }],
    )
    out = render_pricing_plan(plan)
    assert out.startswith("# Pricing plan\n\n")
    assert "1 item to price" in out
    assert "\n## Estimate\n\n" in out
    assert "\n## Priced items\n\n" in out
    assert out.endswith("Confirm to write to BidSheet.ai.")
    assert not out.endswith("\n")
    # money formatted with 2 decimals via format_money
    assert "125.50" in out


def test_render_pricing_plan_empty():
    plan = PricingPlan()
    out = render_pricing_plan(plan)
    assert out.startswith("# Pricing plan\n\n")
    assert "0 items to price" in out
    assert out.endswith("Confirm to write to BidSheet.ai.")


def test_render_pricing_plan_escapes_pipe():
    plan = PricingPlan(estimate_name="est|1", items=[])
    out = render_pricing_plan(plan)
    assert "est\\|1" in out
