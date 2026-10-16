"""IfcReinforcingBar authoring via IfcSweptDiskSolid (estimating_tools.rebar.ifc).

Bootstraps a minimal IFC4 model directly (project/unit/context/site) rather
than reusing ``bim.dxf2bim.build_ifc`` -- that helper's config/feature
plumbing is DXF-specific and would drag in ezdxf/shapely fixtures unrelated
to this module; the bootstrap below mirrors its unit/context idiom exactly
(SI-metres length unit, root Model context + Body/MODEL_VIEW subcontext) so
``add_reinforcing_bars``'s "reuse an existing Body context" path is exercised
against the same shape ``build_ifc`` produces.
"""
from __future__ import annotations

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

import ifcopenshell.util.element  # noqa: E402
import ifcopenshell.util.representation  # noqa: E402
from ifcopenshell.api import run  # noqa: E402

from estimating_tools.rebar.ifc import add_reinforcing_bars  # noqa: E402
from estimating_tools.rebar.model import BarSize  # noqa: E402


def _bootstrap_model():
    """Minimal IFC4 model: SI-metres units, Model+Body context, Site/Storey."""
    model = run("project.create_file", version="IFC4")
    project = run("root.create_entity", model, ifc_class="IfcProject", name="Rebar Test")
    run("unit.assign_unit", model, units=[
        run("unit.add_si_unit", model, unit_type="LENGTHUNIT"),
    ])
    ctx = run("context.add_context", model, context_type="Model")
    run("context.add_context", model, context_type="Model",
        context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)

    site = run("root.create_entity", model, ifc_class="IfcSite", name="Site")
    storey = run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Level 0")
    run("aggregate.assign_object", model, products=[site], relating_object=project)
    run("aggregate.assign_object", model, products=[storey], relating_object=site)
    return model, storey


@pytest.fixture(scope="module")
def authored(tmp_path_factory):
    """Author one straight 2-point bar and one bent 3-point bar, round-trip
    through a saved+reopened IFC file, and hand back both the fresh in-memory
    products and the reread model."""
    model, storey = _bootstrap_model()

    straight = {
        "points_m": [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0)],
        "size": BarSize(5),
        "mark": "A1",
        "count": 2,
    }
    bent = {
        "points_m": [(0.0, 0.0, 0.0), (0.0, 0.5, 0.0), (1.0, 0.5, 0.0)],
        "size": 8,
        "mark": "B1",
        "count": 1,
    }
    products = add_reinforcing_bars(model, [straight, bent], container=storey)

    out = tmp_path_factory.mktemp("rebar_ifc") / "bars.ifc"
    model.write(str(out))
    reread = ifcopenshell.open(str(out))
    return {"products": products, "path": out, "model": reread, "storey": storey}


def test_returns_ifc_reinforcing_bar_products(authored):
    products = authored["products"]
    assert len(products) == 2
    assert [p.is_a() for p in products] == ["IfcReinforcingBar", "IfcReinforcingBar"]
    assert [p.Name for p in products] == ["A1", "B1"]


def test_reread_products_are_reinforcing_bars(authored):
    model = authored["model"]
    bars = model.by_type("IfcReinforcingBar")
    assert len(bars) == 2
    assert {b.Name for b in bars} == {"A1", "B1"}


def test_directrix_point_counts(authored):
    model = authored["model"]
    by_name = {b.Name: b for b in model.by_type("IfcReinforcingBar")}
    for name, expected_points in (("A1", 2), ("B1", 3)):
        solid = by_name[name].Representation.Representations[0].Items[0]
        assert solid.is_a("IfcSweptDiskSolid")
        assert solid.Directrix.is_a("IfcPolyline")
        assert len(solid.Directrix.Points) == expected_points


def test_radius_is_diameter_over_two_in_metres(authored):
    model = authored["model"]
    by_name = {b.Name: b for b in model.by_type("IfcReinforcingBar")}
    solid_a1 = by_name["A1"].Representation.Representations[0].Items[0]
    # #5 diameter 0.625in -> metres: 0.625 * 0.0254 = 0.015875; radius half that.
    assert solid_a1.Radius == pytest.approx(0.0079375, abs=1e-7)

    solid_b1 = by_name["B1"].Representation.Representations[0].Items[0]
    # #8 diameter 1.000in -> metres 0.0254; radius half that.
    assert solid_b1.Radius == pytest.approx(0.0127, abs=1e-7)


def test_representation_type_is_advanced_swept_solid(authored):
    model = authored["model"]
    for bar in model.by_type("IfcReinforcingBar"):
        rep = bar.Representation.Representations[0]
        assert rep.RepresentationType == "AdvancedSweptSolid"


def test_nominal_diameter_and_bar_length_attributes(authored):
    model = authored["model"]
    by_name = {b.Name: b for b in model.by_type("IfcReinforcingBar")}
    a1 = by_name["A1"]
    # Schema exposes these on IFC4 IfcReinforcingBar (verified via
    # ifcopenshell.ifcopenshell_wrapper schema introspection); both are
    # IfcPositiveLengthMeasure, so they follow the project length unit --
    # metres here -- same as Radius. This model is bootstrapped as IFC4
    # (see _bootstrap_model), so the attributes must exist outright --
    # no guard, or a regression to a schema without them would pass silently.
    assert a1.attribute_type("NominalDiameter") is not None
    assert a1.NominalDiameter == pytest.approx(0.015875, abs=1e-6)
    assert a1.attribute_type("BarLength") is not None
    assert a1.BarLength == pytest.approx(3.0, abs=1e-6)


def test_epset_rebar_mark_count_weight(authored):
    model = authored["model"]
    by_name = {b.Name: b for b in model.by_type("IfcReinforcingBar")}

    a1 = by_name["A1"]
    psets = ifcopenshell.util.element.get_psets(a1)
    assert "EPset_Rebar" in psets
    props = psets["EPset_Rebar"]
    assert props["Mark"] == "A1"
    assert props["Count"] == 2
    # #5 weight 1.043 lb/ft * 3m (=9.8425ft) * count 2
    expected_weight = BarSize(5).weight_lb_per_ft * (3.0 / 0.3048) * 2
    assert props["WeightLb"] == pytest.approx(expected_weight, rel=1e-6)


def test_container_assignment(authored):
    model = authored["model"]
    storey = model.by_type("IfcBuildingStorey")[0]
    contained_names = set()
    for rel in model.by_type("IfcRelContainedInSpatialStructure"):
        if rel.RelatingStructure == storey:
            contained_names.update(e.Name for e in rel.RelatedElements)
    assert {"A1", "B1"} <= contained_names


def test_create_shape_triangulates_a_bar(authored):
    """Acceptance check from the plan: the written geometry should be usable
    by ifcopenshell.geom, not just re-readable."""
    import ifcopenshell.geom

    model = authored["model"]
    bar = model.by_type("IfcReinforcingBar")[0]
    settings = ifcopenshell.geom.settings()
    shape = ifcopenshell.geom.create_shape(settings, bar)
    assert len(shape.geometry.verts) > 0


def test_second_call_reuses_existing_body_context():
    """When context=None and the model already has a Body/MODEL_VIEW
    subcontext (e.g. one built by bim.dxf2bim.build_ifc), add_reinforcing_bars
    must reuse it rather than creating a duplicate."""
    model, storey = _bootstrap_model()
    before = len(model.by_type("IfcGeometricRepresentationSubContext"))

    add_reinforcing_bars(model, [{
        "points_m": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        "size": BarSize(4),
        "mark": "C1",
    }])
    add_reinforcing_bars(model, [{
        "points_m": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        "size": BarSize(4),
        "mark": "C2",
    }])

    after = len(model.by_type("IfcGeometricRepresentationSubContext"))
    assert after == before  # reused the bootstrap's Body context both times


def test_reuses_existing_root_model_context_when_no_body_subcontext():
    """A model with a root Model context but no Body subcontext (possible in
    hand-built or third-party IFCs) must get its Body subcontext parented
    under the existing root — not a duplicate root Model context."""
    model = run("project.create_file", version="IFC4")
    run("root.create_entity", model, ifc_class="IfcProject", name="Ctx Test")
    run("unit.assign_unit", model, units=[
        run("unit.add_si_unit", model, unit_type="LENGTHUNIT"),
    ])
    root_ctx = run("context.add_context", model, context_type="Model")

    add_reinforcing_bars(model, [{
        "points_m": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        "size": BarSize(4),
        "mark": "J1",
    }])

    roots = [c for c in model.by_type("IfcGeometricRepresentationContext",
                                      include_subtypes=False)
             if c.ContextType == "Model"]
    assert roots == [root_ctx]  # no duplicate root created
    subs = model.by_type("IfcGeometricRepresentationSubContext")
    assert len(subs) == 1
    assert subs[0].ParentContext == root_ctx


def test_no_container_means_no_spatial_assignment():
    model, storey = _bootstrap_model()
    add_reinforcing_bars(model, [{
        "points_m": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        "size": BarSize(3),
        "mark": "D1",
    }])
    assert not model.by_type("IfcRelContainedInSpatialStructure")


def test_default_count_is_one():
    model, storey = _bootstrap_model()
    [product] = add_reinforcing_bars(model, [{
        "points_m": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        "size": BarSize(6),
        "mark": "E1",
    }])
    psets = ifcopenshell.util.element.get_psets(product)
    assert psets["EPset_Rebar"]["Count"] == 1


def test_rejects_single_point_bar():
    model, storey = _bootstrap_model()
    with pytest.raises(ValueError, match="at least 2 points"):
        add_reinforcing_bars(model, [{
            "points_m": [(0.0, 0.0, 0.0)],
            "size": BarSize(5),
            "mark": "F1",
        }])


def test_rejects_zero_count():
    model, storey = _bootstrap_model()
    with pytest.raises(ValueError, match="count must be >= 1"):
        add_reinforcing_bars(model, [{
            "points_m": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
            "size": BarSize(5),
            "mark": "G1",
            "count": 0,
        }])


def test_rejects_non_int_count():
    model, storey = _bootstrap_model()
    with pytest.raises(ValueError, match=r"H1.*count must be an int"):
        add_reinforcing_bars(model, [{
            "points_m": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
            "size": BarSize(5),
            "mark": "H1",
            "count": 2.5,
        }])


def test_rejects_bad_size_with_mark_named_error():
    model, storey = _bootstrap_model()
    with pytest.raises(ValueError, match=r"I1.*unknown bar size"):
        add_reinforcing_bars(model, [{
            "points_m": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
            "size": 99,
            "mark": "I1",
        }])


def test_bars_have_object_placement(authored):
    """IfcProduct.PlacementForShapeRepresentation (express rule): a product
    with a shape representation must have an ObjectPlacement. Bars carry no
    real transform (centreline coordinates already encode position), so the
    placement is expected to be an identity IfcLocalPlacement."""
    model = authored["model"]
    for bar in model.by_type("IfcReinforcingBar"):
        assert bar.ObjectPlacement is not None
        assert bar.ObjectPlacement.is_a("IfcLocalPlacement")


# ---------------------------------------------------------------------------
# Spec quantities (issue #108 follow-through): weight belongs in
# Qto_ReinforcingElementBaseQuantities, not only the custom pset — and a
# classified bar rides the BIM->takeoff route end-to-end.
# ---------------------------------------------------------------------------
_KG_PER_LB = 0.45359237
_FT_PER_M = 1.0 / 0.3048


def _mark_weight_lb(size: BarSize, length_m: float, count: int) -> float:
    return size.weight_lb_per_ft * (length_m * _FT_PER_M) * count


def test_authors_reinforcing_base_quantities(authored):
    # straight A1: 3.0 m, #5, count 2 — the Qto carries the MARK TOTAL in
    # project units (metres / kg), matching Count semantics
    bar = next(e for e in authored["model"].by_type("IfcReinforcingBar")
               if e.Name == "A1")
    qtos = ifcopenshell.util.element.get_psets(bar, qtos_only=True)
    q = qtos["Qto_ReinforcingElementBaseQuantities"]
    assert q["Count"] == 2
    assert q["Length"] == pytest.approx(3.0)
    assert q["Weight"] == pytest.approx(
        _mark_weight_lb(BarSize(5), 3.0, 2) * _KG_PER_LB)
    # the custom pset stays for identity/back-compat
    psets = ifcopenshell.util.element.get_psets(bar)
    assert psets["EPset_Rebar"]["Mark"] == "A1"


def test_unclassified_bars_stay_unclassified(authored):
    # no code param -> no classification association (back-compat)
    assert not authored["model"].by_type("IfcRelAssociatesClassification")


def test_classified_bars_reach_the_takeoff(tmp_path):
    from bimforge.bim.ifc_takeoff import build_takeoff

    model, storey = _bootstrap_model()
    bars = [
        {"points_m": [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0)], "size": BarSize(5),
         "mark": "A1", "count": 2},
        {"points_m": [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)], "size": BarSize(8),
         "mark": "B1", "count": 3},
    ]
    add_reinforcing_bars(model, bars, container=storey, code="REBAR-BR")
    out = tmp_path / "classified.ifc"
    model.write(str(out))

    tmap = {"codes": {"REBAR-BR": {"measure": "Weight", "unit": "LBS",
                                   "item_number": "51"}}}
    takeoff, warnings = build_takeoff(str(out), tmap)
    (row,) = takeoff["rows"]
    expected_lb = (_mark_weight_lb(BarSize(5), 3.0, 2)
                   + _mark_weight_lb(BarSize(8), 2.0, 3))
    assert row["unit"] == "LBS"
    assert row["quantity"] == pytest.approx(expected_lb, rel=1e-6)
    # per-mark traceability behind the summed pay item (SI kg)
    by_mark = {e["name"]: e for e in row["elements"]}
    assert by_mark["A1"]["value_si"] == pytest.approx(
        _mark_weight_lb(BarSize(5), 3.0, 2) * _KG_PER_LB)
    assert not warnings


def test_reusing_an_existing_classification_system(tmp_path):
    # bars added into a model that already carries a BidSchedule system
    # (e.g. dxf2bim output) must reuse it, not author a duplicate
    model, storey = _bootstrap_model()
    run("classification.add_classification", model, classification="BidSchedule")
    add_reinforcing_bars(
        model, [{"points_m": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
                 "size": 5, "mark": "C1"}],
        container=storey, code="REBAR-BR")
    assert len(model.by_type("IfcClassification")) == 1
