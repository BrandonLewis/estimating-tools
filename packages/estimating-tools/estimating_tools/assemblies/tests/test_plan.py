import pytest

from estimating_tools.assemblies.model import (
    Assembly, CanonicalAssemblyLibrary, Component,
)
from estimating_tools.assemblies.plan import AssemblyPushPlan, plan_assembly_push


def _library() -> CanonicalAssemblyLibrary:
    return CanonicalAssemblyLibrary(assemblies=[
        Assembly(
            name="Cast-in-place wall", assembly_type="concrete", cost_code="03-300",
            description="CIP wall", components=[
                Component("labor", "Form/pour/strip", quantity=8.0, unit="HR", unit_cost=65.0, trade="carpenter"),
                Component("material", "Ready-mix", quantity=1.0, unit="CY", unit_cost=145.0),
            ],
        ),
        Assembly(
            name="Striping", assembly_type="paving", components=[
                # rate_ref with NO unit_cost -> unit_cost 0.0 + flagged
                Component("subcontractor", "Stripe sub", quantity=1.0, unit="LS", rate_ref="STRIPE-STD"),
            ],
        ),
    ])


def test_plan_shapes_v2_template_assemblies():
    plan = plan_assembly_push(_library(), org_id=42)
    assert isinstance(plan, AssemblyPushPlan) and plan.org_id == 42
    a0 = plan.assemblies[0]
    assert a0["name"] == "Cast-in-place wall"
    assert a0["assembly_type"] == "concrete"
    assert a0["context"] == "template" and a0["context_id"] == 42
    assert a0["cost_code"] == "03-300"          # passed through for the skill to resolve
    assert a0["description"] == "CIP wall"


def test_component_payload_carries_create_component_params_plus_rate_resolution():
    plan = plan_assembly_push(_library(), org_id=42)
    comps = plan.assemblies[0]["components"]
    assert comps[0] == {
        "component_type": "labor", "name": "Form/pour/strip", "quantity": 8.0,
        "unit": "HR", "unit_cost": 65.0, "trade": "carpenter", "description": "",
        "rate_resolution": None,
    }
    assert comps[1]["component_type"] == "material" and comps[1]["unit_cost"] == 145.0


def test_rate_ref_without_unit_cost_is_zeroed_and_flagged():
    plan = plan_assembly_push(_library(), org_id=42)
    striping = plan.assemblies[1]
    comp = striping["components"][0]
    assert comp["unit_cost"] == 0.0            # not None, not dropped
    # the rate_ref is recorded as a flag on the assembly, not silently lost
    assert "STRIPE-STD" in striping["rate_refs"]


def test_invalid_component_type_raises():
    lib = CanonicalAssemblyLibrary(assemblies=[
        Assembly(name="Bad", components=[Component("widget", "x")]),
    ])
    with pytest.raises(ValueError):
        plan_assembly_push(lib, org_id=1)


def test_cost_code_none_and_no_rate_refs_when_absent():
    lib = CanonicalAssemblyLibrary(assemblies=[
        Assembly(name="Plain", components=[Component("other", "misc", unit_cost=10.0)]),
    ])
    a = plan_assembly_push(lib, org_id=7).assemblies[0]
    assert a["cost_code"] is None and a["rate_refs"] == []
    assert a["components"][0]["unit_cost"] == 10.0


def test_component_with_both_unit_cost_and_rate_ref_uses_cost_and_does_not_flag():
    # Explicit unit_cost wins over rate_ref: cost passes through, rate_ref NOT flagged.
    lib = CanonicalAssemblyLibrary(assemblies=[
        Assembly(name="Both", components=[
            Component("labor", "Crew", quantity=1.0, unit="HR", unit_cost=5.0, rate_ref="LAB-STD"),
        ]),
    ])
    a = plan_assembly_push(lib, org_id=3).assemblies[0]
    assert a["components"][0]["unit_cost"] == 5.0   # explicit cost kept
    assert a["rate_refs"] == []                      # routable rate_ref goes to rate_resolution, not rate_refs


def test_rate_resolution_routes_by_component_type():
    lib = CanonicalAssemblyLibrary(assemblies=[
        Assembly(name="A", components=[
            Component("labor", "Crew", rate_ref="CARP"),
            Component("equipment", "Hoe", rate_ref="EXCAVATOR"),
            Component("material", "Mix", rate_ref="CONCRETE-3000"),
        ]),
    ])
    comps = plan_assembly_push(lib, 7).assemblies[0]["components"]
    assert comps[0]["rate_resolution"] == {"kind": "labor", "key": "CARP"}
    assert comps[1]["rate_resolution"] == {"kind": "equipment", "key": "EXCAVATOR"}
    assert comps[2]["rate_resolution"] == {"kind": "material", "key": "CONCRETE-3000"}
    # routable refs are carried by rate_resolution, NOT flagged in rate_refs
    assert plan_assembly_push(lib, 7).assemblies[0]["rate_refs"] == []


def test_routable_rate_ref_with_unit_cost_still_routes():
    lib = CanonicalAssemblyLibrary(assemblies=[
        Assembly(name="A", components=[
            Component("labor", "Crew", unit_cost=5.0, rate_ref="LAB-STD"),
        ]),
    ])
    a = plan_assembly_push(lib, 7).assemblies[0]
    assert a["components"][0]["rate_resolution"] == {"kind": "labor", "key": "LAB-STD"}
    assert a["components"][0]["unit_cost"] == 5.0   # inline cost kept
    assert a["rate_refs"] == []                      # routable -> not in rate_refs


def test_non_routable_rate_ref_is_none_and_flagged():
    lib = CanonicalAssemblyLibrary(assemblies=[
        Assembly(name="A", components=[
            Component("subcontractor", "Stripe sub", rate_ref="STRIPE-STD"),
            Component("other", "Misc", rate_ref="MISC-1"),
        ]),
    ])
    a = plan_assembly_push(lib, 7).assemblies[0]
    assert a["components"][0]["rate_resolution"] is None
    assert a["components"][1]["rate_resolution"] is None
    assert "STRIPE-STD" in a["rate_refs"] and "MISC-1" in a["rate_refs"]


def test_non_routable_rate_ref_flagged_even_with_unit_cost():
    # a subcontractor/other rate_ref is flagged in rate_refs regardless of inline unit_cost
    lib = CanonicalAssemblyLibrary(assemblies=[
        Assembly(name="A", components=[
            Component("subcontractor", "Sub", unit_cost=50.0, rate_ref="SUB-1"),
        ]),
    ])
    a = plan_assembly_push(lib, 7).assemblies[0]
    assert a["components"][0]["rate_resolution"] is None
    assert a["components"][0]["unit_cost"] == 50.0   # inline cost kept
    assert "SUB-1" in a["rate_refs"]                 # still flagged (non-routable)


# ---- render_assembly_push_plan tests (Phase 3) ----

from estimating_tools.assemblies.plan import (
    AssemblyPushPlan, render_assembly_push_plan,
)


def _flag_asm(name, cost_code, rate_refs, components):
    return {
        "name": name, "assembly_type": "structural", "context": "template",
        "context_id": 42, "description": "", "cost_code": cost_code,
        "components": components, "rate_refs": rate_refs,
    }


def _comp(component_type="labor", name="Carpenter", quantity=4.0, unit="HR",
          unit_cost=0.0, rate_resolution=None):
    return {"component_type": component_type, "name": name, "quantity": quantity,
            "unit": unit, "unit_cost": unit_cost, "trade": "", "description": "",
            "rate_resolution": rate_resolution}


def test_render_assembly_push_plan_shape():
    plan = AssemblyPushPlan(
        org_id=42,
        assemblies=[_flag_asm("Manhole Base", "03-3000", [], [
            _comp(rate_resolution={"kind": "labor", "key": "carpenter_base"}),
            _comp(component_type="material", name="Concrete", quantity=2.0, unit="CY",
                  unit_cost=175.0),
        ])],
    )
    out = render_assembly_push_plan(plan)
    assert out.startswith("# Assembly push plan\n\n")
    assert "1 assembly, 2 components" in out
    assert "\n## Assemblies\n\n" in out
    assert "\n## Components\n\n" in out
    assert "## Flagged" not in out                                # no non-routable rate_refs
    assert out.endswith("Confirm to write to BidSheet.ai.")
    # Component table has an assembly column
    assert "| assembly | component_type | name | quantity | unit | unit_cost | rate_ref |" in out
    # rate_resolution -> rate_ref cell shows the key
    assert "| Manhole Base | labor | Carpenter | 4 | HR | 0.00 | carpenter_base |" in out
    # non-routable component with no rate_resolution -> '-' in rate_ref cell
    assert "| Manhole Base | material | Concrete | 2 | CY | 175.00 | - |" in out


def test_render_assembly_push_plan_empty():
    plan = AssemblyPushPlan()
    out = render_assembly_push_plan(plan)
    assert out.startswith("# Assembly push plan\n\n")
    assert "0 assemblies, 0 components" in out
    assert "## Flagged" not in out
    assert out.endswith("Confirm to write to BidSheet.ai.")


def test_render_assembly_push_plan_flags_non_routable_rate_refs():
    plan = AssemblyPushPlan(
        org_id=42,
        assemblies=[
            _flag_asm("A", "03-1000", ["ACME sub"], [
                _comp(component_type="subcontractor", name="ACME"),
            ]),
            _flag_asm("B", "04-2000", ["other_ref"], []),
        ],
    )
    out = render_assembly_push_plan(plan)
    assert "\n## Flagged\n\n" in out
    assert "- assembly 'A': non-routable rate_ref 'ACME sub'" in out
    assert "- assembly 'B': non-routable rate_ref 'other_ref'" in out
    # Flag count reflected in the summary
    assert "2 non-routable rate refs" in out


def test_render_assembly_push_plan_escapes_pipe():
    plan = AssemblyPushPlan(
        org_id=1,
        assemblies=[_flag_asm("a|b", "03-3000", [], [])],
    )
    out = render_assembly_push_plan(plan)
    assert "a\\|b" in out
