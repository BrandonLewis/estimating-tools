from estimating_tools.importers.model import CanonicalEstimate, LineItem, Schedule
from estimating_tools.importers.push import PushPlan, diff_new_items, plan_push


def _sample() -> CanonicalEstimate:
    return CanonicalEstimate(
        project={"name": "Demo Job", "bid_date": "2026-04-28", "source": "HCSS HeavyBid"},
        schedules=[
            Schedule(name="Base Bid", items=[
                LineItem(item_number="1", description="Mobilization", item_code="070-010",
                         quantity=1.0, unit="LS", unit_price=50000.0),
                LineItem(item_number="2", description="Clearing", item_code="170-101",
                         quantity=3.0, unit="AC", unit_price=4200.0),
                # duplicate template (same code/desc/unit as item 1) -> dedup to one template
                LineItem(item_number="3", description="Mobilization", item_code="070-010",
                         quantity=1.0, unit="LS"),
            ]),
            Schedule(name="Additive Alt 1", items=[
                LineItem(item_number="A1", description="Extra paving", item_code="390-100",
                         quantity=100.0, unit="SY"),
            ]),
        ],
    )


def test_plan_push_maps_project_and_schedules():
    plan = plan_push(_sample())
    assert isinstance(plan, PushPlan)
    assert plan.project["title"] == "Demo Job"
    assert plan.project["bid_date"] == "2026-04-28"
    assert [(s["name"], s["display_order"]) for s in plan.schedules] == [("Base Bid", 0), ("Additive Alt 1", 1)]


def test_plan_push_dedupes_templates_first_seen_order():
    plan = plan_push(_sample())
    triples = [(t["item_code"], t["description"], t["unit"]) for t in plan.templates]
    # item 1 and item 3 share (070-010, Mobilization, LS) -> one template; order = first seen
    assert triples == [
        ("070-010", "Mobilization", "LS"),
        ("170-101", "Clearing", "AC"),
        ("390-100", "Extra paving", "SY"),
    ]


def test_plan_push_items_carry_quantity_and_schedule_no_price():
    plan = plan_push(_sample())
    first = plan.items[0]
    assert first["item_number"] == "1"
    assert first["item_code"] == "070-010"
    assert first["estimated_quantity"] == 1.0   # mapped from quantity
    assert first["unit"] == "LS"
    assert first["schedule_name"] == "Base Bid"
    # unit_price is dropped from EVERY item payload
    assert all("unit_price" not in it for it in plan.items)
    # all items present (one per line item across schedules)
    assert [it["item_number"] for it in plan.items] == ["1", "2", "3", "A1"]


def test_diff_new_items_dedupes_per_schedule():
    items = [
        {"item_number": "1", "schedule_name": "Base Bid"},
        {"item_number": "2", "schedule_name": "Base Bid"},
        {"item_number": "1", "schedule_name": "Additive Alt 1"},  # same number, other schedule
    ]
    existing = {"Base Bid": {"1"}}  # item 1 already in Base Bid only
    out = diff_new_items(items, existing)
    # Base Bid item 1 skipped; Base Bid item 2 kept; Additive Alt 1 item 1 KEPT (different schedule)
    assert [(i["item_number"], i["schedule_name"]) for i in out] == [
        ("2", "Base Bid"), ("1", "Additive Alt 1"),
    ]
    assert diff_new_items(items, {}) == items  # nothing existing -> all returned


# ---- render_push_plan tests (Phase 3) ----

from estimating_tools.artifacts import md_table
from estimating_tools.importers.push import PushPlan, render_push_plan


def test_render_push_plan_shape():
    plan = PushPlan(
        project={"title": "Riverbend Ph. 1", "bid_date": "2026-08-15"},
        schedules=[{"name": "Base Bid", "display_order": 0}],
        templates=[{"item_code": "01-1000", "description": "Mobilization", "unit": "LS"}],
        items=[{"item_number": "1", "item_code": "01-1000", "description": "Mobilization",
                "unit": "LS", "estimated_quantity": 1.0, "schedule_name": "Base Bid"}],
    )
    out = render_push_plan(plan)
    # heading + summary + sections + footer
    assert out.startswith("# Push plan\n\n")
    assert "1 schedule, 1 template, 1 item" in out                # summary line
    assert "\n## Project\n\n" in out
    assert "\n## Schedules\n\n" in out
    assert "\n## Templates\n\n" in out
    assert "\n## Items\n\n" in out
    assert out.endswith("Confirm to write to BidSheet.ai.")
    # No trailing newline after the footer
    assert not out.endswith("\n")
    # Table shape check on one section (proves md_table use)
    assert "| item_number | item_code | description | unit | estimated_quantity | schedule_name |" in out
    assert "| 1 | 01-1000 | Mobilization | LS | 1 | Base Bid |" in out


def test_render_push_plan_empty():
    plan = PushPlan()
    out = render_push_plan(plan)
    assert out.startswith("# Push plan\n\n")
    assert "0 schedules, 0 templates, 0 items" in out
    assert out.endswith("Confirm to write to BidSheet.ai.")
    # Empty tables have header + separator only (no body rows)
    # -- Project has an empty title; still emits a single-row kv table with '-' cells
    assert "| Project title |" in out
    # Sections tables all still render their headers even when empty
    assert "| item_number | item_code | description | unit | estimated_quantity | schedule_name |" in out


def test_render_push_plan_escapes_pipe_in_cell():
    plan = PushPlan(
        project={"title": "a|b"},
        schedules=[{"name": "Sch|1", "display_order": 0}],
        templates=[],
        items=[],
    )
    out = render_push_plan(plan)
    assert "a\\|b" in out                                          # escape survives to output
    assert "Sch\\|1" in out
