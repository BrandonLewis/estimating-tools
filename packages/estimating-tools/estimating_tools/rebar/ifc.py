"""IfcReinforcingBar authoring: swept-disk-solid rebar geometry from a bar's
centreline points -- a BIM-interop bridge for ``rebar`` marks (or any
point-list bars), so a bar list can be viewed/coordinated in Bonsai or other
IFC viewers alongside a ``bim.dxf2bim``-authored model. This is geometry
authoring, not design/detailing (see ``rebar/detailing.py`` and
``rebar/develop.py``); only the centreline and nominal diameter are drawn --
no bend/hook shape.

API idiom follows ``bim/dxf2bim.py``'s ``build_ifc`` (``ifcopenshell.api.run``
for everything expressible that way). ``IfcSweptDiskSolid`` has no ``api.run``
helper in ifcopenshell 0.8.5, so its geometry -- and the ``IfcShapeRepresentation``
that wraps it -- are authored manually with ``model.create_entity`` and then
handed to ``geometry.assign_representation``, which accepts any
pre-built ``IfcShapeRepresentation`` (verified against the installed
``ifcopenshell.api.geometry.assign_representation`` source: it just appends the
given representation to the product's ``IfcProductDefinitionShape``).
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

import ifcopenshell
import ifcopenshell.util.representation
from ifcopenshell.api import run

from estimating_tools.rebar.model import BarSize

_M_PER_IN = 0.0254
_FT_PER_M = 1.0 / 0.3048
_KG_PER_LB = 0.45359237

#: IFC4 buildingSMART geometry-use convention: IfcExtrudedAreaSolid/
#: IfcRevolvedAreaSolid use "SweptSolid"; IfcSweptDiskSolid (and
#: IfcSurfaceCurveSweptAreaSolid) use "AdvancedSweptSolid". Verified in-venv
#: against ifcopenshell 0.8.5: ifcopenshell.geom.create_shape() successfully
#: triangulates an IfcReinforcingBar whose IfcShapeRepresentation carries this
#: RepresentationType (156 verts for a 2-point straight bar).
_REPRESENTATION_TYPE = "AdvancedSweptSolid"


def _get_or_create_body_context(model: ifcopenshell.file) -> ifcopenshell.entity_instance:
    """Reuse an existing Body/MODEL_VIEW subcontext if the model already has
    one (e.g. a model built by ``bim.dxf2bim.build_ifc``); otherwise create
    one the same way ``build_ifc`` does — reusing any existing root Model
    context as the parent (``get_context`` with no identifier matches root
    contexts only, ``include_subtypes=False``) so a model that has a Model
    context but no Body subcontext doesn't grow a duplicate root."""
    existing = ifcopenshell.util.representation.get_context(
        model, "Model", "Body", "MODEL_VIEW")
    if existing is not None:
        return existing
    ctx = ifcopenshell.util.representation.get_context(model, "Model")
    if ctx is None:
        ctx = run("context.add_context", model, context_type="Model")
    return run("context.add_context", model, context_type="Model",
               context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)


def _polyline_length_m(points_m: list[tuple[float, float, float]]) -> float:
    total = 0.0
    for (x0, y0, z0), (x1, y1, z1) in zip(points_m, points_m[1:]):
        total += ((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2) ** 0.5
    return total


def _set_if_supported(product: ifcopenshell.entity_instance, name: str, value: float) -> None:
    """Set a schema attribute only if the product's IFC class actually
    exposes it (IfcReinforcingBar's NominalDiameter/BarLength are IFC4-only
    additions; guard so this stays schema-version tolerant)."""
    try:
        setattr(product, name, value)
    except AttributeError:
        pass


def _get_or_add_classification(model: ifcopenshell.file, name: str) -> ifcopenshell.entity_instance:
    """Reuse an existing classification system of this name (a dxf2bim model
    already carries one) rather than authoring a duplicate."""
    for c in model.by_type("IfcClassification"):
        if c.Name == name:
            return c
    return run("classification.add_classification", model, classification=name)


def add_reinforcing_bars(
    model: ifcopenshell.file,
    bars: Iterable[dict[str, Any]],
    *,
    context: Optional[ifcopenshell.entity_instance] = None,
    container: Optional[ifcopenshell.entity_instance] = None,
    code: Optional[str] = None,
    classification_system: str = "BidSchedule",
) -> list[ifcopenshell.entity_instance]:
    """Author each ``bars`` entry as an ``IfcReinforcingBar`` with an
    ``IfcSweptDiskSolid`` body swept along the bar's centreline.

    ``bars`` items: ``{"points_m": [(x, y, z), ...], "size": BarSize | int,
    "mark": str, "count": int = 1}``. Points are in metres, matching the
    ``bimforge.bim`` modelling convention (see ``dxf2bim``); the
    model's length unit is assumed metres, so a bar's ``Radius`` -- and the
    Directrix coordinates -- are written directly in metres with no
    conversion factor.

    Per bar:
      * product: ``root.create_entity(ifc_class="IfcReinforcingBar", name=mark)``.
      * placement: identity ``IfcLocalPlacement`` via ``geometry.edit_object_placement``
        (no matrix arg) -- required by the IfcProduct.PlacementForShapeRepresentation
        express rule once a shape representation is assigned below.
      * geometry: manual ``IfcSweptDiskSolid`` (Directrix = IfcPolyline of
        IfcCartesianPoints, Radius = nominal diameter / 2 in metres) wrapped
        in an ``IfcShapeRepresentation`` and assigned via
        ``geometry.assign_representation``.
      * schema attributes ``NominalDiameter``/``BarLength`` set when the
        schema exposes them (IFC4 IfcReinforcingBar; both are
        IfcPositiveLengthMeasure). NOTE: IfcPositiveLengthMeasure values
        follow the PROJECT length unit -- here metres, matching ``Radius``
        and the Directrix coordinates -- not a fixed millimetre convention;
        a conforming viewer/consumer (e.g. Tekla, Revit) converts to its
        preferred display unit itself. The mm-looking values (e.g. #5 ->
        15.875) seen in some other BIM-authoring tools reflect THEIR
        project running in millimetre units, not a schema rule -- writing
        mm literals into a metre-unit model here would be a unit bug (a
        15.875 m bar diameter to any conforming reader).
      * spec quantities: ``Qto_ReinforcingElementBaseQuantities`` with
        ``Count``, ``Length`` (project metres) and ``Weight`` (kilograms —
        the file declares no MASSUNIT, which the takeoff reader treats as
        kg). ``Weight`` is the MARK TOTAL, consistent with ``Count``: one
        product represents the whole mark set even though the geometry
        draws a single bar. This is what makes bars visible to
        ``est-bim takeoff`` (map ``measure: Weight``) and QTO tools.
      * a custom ``EPset_Rebar`` pset: ``Mark`` (identity — properly pset
        data), ``Count`` and ``WeightLb`` (DEPRECATED duplicates kept for
        back-compat; the Qto is the contractual home for quantities).
      * classification: when ``code`` is given (or a per-bar ``"code"``
        key overrides it), an ``IfcClassificationReference`` under
        ``classification_system`` — the pay-item key ``ifc_takeoff`` sums
        by. Reuses an existing same-named system rather than duplicating.
      * ``spatial.assign_container`` when ``container`` is given.

    Returns the created IfcReinforcingBar products, in input order.
    """
    body = context if context is not None else _get_or_create_body_context(model)

    products: list[ifcopenshell.entity_instance] = []
    for bar in bars:
        points_m = list(bar["points_m"])
        if len(points_m) < 2:
            raise ValueError(
                f"bar {bar.get('mark')!r}: points_m needs at least 2 points, "
                f"got {len(points_m)}"
            )
        mark = bar["mark"]
        size = bar["size"]
        if not isinstance(size, BarSize):
            try:
                size = BarSize(size)
            except ValueError as exc:
                raise ValueError(f"bar {mark!r}: {exc}") from exc

        count = bar.get("count", 1)
        if not isinstance(count, int) or isinstance(count, bool):
            raise ValueError(f"bar {mark!r}: count must be an int, got {count!r}")
        if count < 1:
            raise ValueError(f"bar {mark!r}: count must be >= 1, got {count}")

        radius_m = size.diameter_in * _M_PER_IN / 2.0

        product = run("root.create_entity", model, ifc_class="IfcReinforcingBar", name=mark)
        # IfcProduct.PlacementForShapeRepresentation (express rule): a product
        # with a shape representation requires an ObjectPlacement. No matrix
        # arg -> identity (verified against the installed ifcopenshell.api
        # .geometry.edit_object_placement source: matrix defaults to np.eye(4)
        # when None).
        run("geometry.edit_object_placement", model, product=product)

        cart_points = [
            model.create_entity("IfcCartesianPoint", Coordinates=(float(x), float(y), float(z)))
            for x, y, z in points_m
        ]
        directrix = model.create_entity("IfcPolyline", Points=cart_points)
        solid = model.create_entity("IfcSweptDiskSolid", Directrix=directrix, Radius=radius_m)
        rep = model.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=body,
            RepresentationIdentifier=getattr(body, "ContextIdentifier", None) or "Body",
            RepresentationType=_REPRESENTATION_TYPE,
            Items=[solid],
        )
        run("geometry.assign_representation", model, product=product, representation=rep)

        length_m = _polyline_length_m(points_m)
        _set_if_supported(product, "NominalDiameter", size.diameter_in * _M_PER_IN)
        _set_if_supported(product, "BarLength", length_m)

        weight_lb = size.weight_lb_per_ft * (length_m * _FT_PER_M) * count
        pset = run("pset.add_pset", model, product=product, name="EPset_Rebar")
        run("pset.edit_pset", model, pset=pset, properties={
            "Mark": mark,
            "Count": count,
            "WeightLb": weight_lb,
        })

        qto = run("pset.add_qto", model, product=product,
                  name="Qto_ReinforcingElementBaseQuantities")
        run("pset.edit_qto", model, qto=qto, properties={
            "Count": count,
            "Length": length_m,
            "Weight": weight_lb * _KG_PER_LB,
        })

        bar_code = bar.get("code", code)
        if bar_code:
            system = _get_or_add_classification(model, classification_system)
            run("classification.add_reference", model, products=[product],
                identification=str(bar_code), name="",
                classification=system)

        if container is not None:
            run("spatial.assign_container", model, products=[product], relating_structure=container)

        products.append(product)

    return products
