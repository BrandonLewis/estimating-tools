from estimating_tools.rates.model import (
    CanonicalRateLibrary, EquipmentRate, LaborRate, MaterialCost, VALID_RATE_TYPES,
)


def test_models_construct_with_defaults():
    lr = LaborRate(classification="CARP", base_hourly_rate=45.0)
    assert lr.burden_percentage == 35.0 and lr.is_union is False and lr.region == ""
    er = EquipmentRate(equipment_type="EXCAVATOR", hourly_rate=120.0)
    assert er.includes_operator is False and er.description == ""
    mc = MaterialCost(material_name="Concrete 3000 PSI", unit_cost=145.0)
    assert mc.unit == "" and mc.category == ""
    lib = CanonicalRateLibrary()
    assert lib.labor_rates == [] and lib.equipment_rates == [] and lib.material_costs == []


def test_library_holds_typed_lists():
    lib = CanonicalRateLibrary(
        labor_rates=[LaborRate(classification="LAB", base_hourly_rate=30.0)],
        material_costs=[MaterialCost(material_name="Rebar #4", unit_cost=0.85)],
    )
    assert lib.labor_rates[0].classification == "LAB"
    assert lib.material_costs[0].material_name == "Rebar #4"


def test_valid_rate_types():
    assert VALID_RATE_TYPES == {"labor", "equipment", "material"}
