from estimating_tools.costcodes.model import (
    ActivityCode, CanonicalCostCodeSystem, CostType,
)


def test_models_construct_with_defaults():
    ct = CostType(code="L")
    assert ct.name == "" and ct.sort_order == 0
    ac = ActivityCode(code="02-110")
    assert ac.description == "" and ac.category == "" and ac.cost_type_code == ""
    assert ac.parent_code == "" and ac.structure_tags == [] and ac.is_active is True
    assert ac.sort_order == 0
    sys = CanonicalCostCodeSystem(name="Std Codes 2026")
    assert sys.description == "" and sys.version == ""
    assert sys.cost_types == [] and sys.activity_codes == []


def test_system_holds_types_and_codes():
    sys = CanonicalCostCodeSystem(
        name="S",
        cost_types=[CostType(code="L", name="Labor")],
        activity_codes=[ActivityCode(code="02-110", description="Form Footings")],
    )
    assert sys.cost_types[0].name == "Labor"
    assert sys.activity_codes[0].code == "02-110"


def test_structure_tags_are_independent_lists():
    a = ActivityCode(code="A")
    b = ActivityCode(code="B")
    a.structure_tags.append("bridge")
    assert b.structure_tags == []   # no shared mutable default


def test_system_carries_source_and_composition_defaults():
    s = CanonicalCostCodeSystem(name="Std")
    assert s.source_system == ""
    assert s.edition == ""
    assert s.composition == "composed"


def test_activity_code_carries_source_code_and_level():
    a = ActivityCode(code="03 30 00")
    assert a.source_code == ""
    assert a.level == 0
    a2 = ActivityCode(code="03 30 00", source_code="03 30 00 ", level=2)
    assert a2.source_code == "03 30 00 "
    assert a2.level == 2
