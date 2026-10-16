"""Deterministic quantity-takeoff helpers.

Public surface: ``calculate_takeoff`` (dimension math per unit + material
waste factor, org-profile overrides), ``convert_units`` (SF/SY, CF/CY,
asphalt TON/CY), and ``check_dbe_requirements`` (goal amount + generic
checklist). CLI: ``est-takeoff convert 9 SF SY`` (see
``estimating_tools.takeoff.cli``). Each function's docstring carries its
call shape.

Re-authored from the three working tools of the Shared-agent-toolkit
construction-toolkit MCP. Agency-specific DBE text has been generalized.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

UNIT_CONVERSIONS = {
    "SF_to_SY": 1 / 9,
    "SY_to_SF": 9,
    "CF_to_CY": 1 / 27,
    "CY_to_CF": 27,
    "TON_to_CY_asphalt": 1 / 2.4,
    "CY_to_TON_asphalt": 2.4,
}

WASTE_FACTORS = {
    "concrete": 1.05,
    "asphalt": 1.03,
    "aggregate": 1.10,
    "rebar": 1.08,
    "lumber": 1.15,
    "pipe": 1.05,
    "default": 1.05,
}


def profile_waste_factors(profile=None) -> Dict[str, float]:
    """The active org profile's ``estimating.waste_factors`` mapping ({} when
    no profile sets one). Waste is item-dependent org judgment (e.g.
    footing_concrete 1.15, wall_concrete 1.10) — the profile governs;
    WASTE_FACTORS above are agnostic fallbacks only. Pass ``profile`` to skip
    ESTIMATING_PROFILES discovery. Discovery failures (profiles extras like
    jsonschema missing, malformed profile) degrade to {} — stay agnostic."""
    if profile is None:
        try:
            from estimating_tools.profiles.loader import load
            profile = load()
        except Exception:  # jsonschema missing, malformed profile — stay agnostic
            from estimating_tools.profiles.model import Profile
            profile = Profile(data={})
    wf = profile.section("estimating").get("waste_factors")
    return dict(wf) if isinstance(wf, dict) else {}


def calculate_takeoff(
    item_description: str,
    dimensions: Dict[str, float],
    unit: str,
    material_type: Optional[str] = None,
    waste_factors: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Calculate a quantity takeoff with a material waste factor.

    ``waste_factors``: org-convention overrides merged over WASTE_FACTORS
    (profile wins). None -> the active org profile's estimating.waste_factors.
    """
    if unit == "LF":
        base_qty = dimensions.get("length", 0)
    elif unit == "SF":
        base_qty = dimensions.get("length", 0) * dimensions.get("width", 0)
    elif unit == "SY":
        base_qty = (dimensions.get("length", 0) * dimensions.get("width", 0)) / 9
    elif unit == "CF":
        base_qty = (
            dimensions.get("length", 0)
            * dimensions.get("width", 0)
            * dimensions.get("depth", dimensions.get("height", 0))
        )
    elif unit == "CY":
        cf = (
            dimensions.get("length", 0)
            * dimensions.get("width", 0)
            * dimensions.get("depth", dimensions.get("height", 0))
        )
        base_qty = cf / 27
    elif unit == "EA":
        base_qty = dimensions.get("quantity", 1)
    else:
        raise ValueError(
            f"Unsupported unit {unit!r}. Supported: LF, SF, SY, CF, CY, EA."
        )

    overrides = (waste_factors if waste_factors is not None
                 else profile_waste_factors())
    merged = {**WASTE_FACTORS, **overrides}
    key = material_type if material_type in merged else "default"
    waste_factor = merged[key]
    waste_source = "profile" if key in overrides else "default"
    qty_with_waste = base_qty * waste_factor
    return {
        "item": item_description,
        "dimensions": dimensions,
        "base_quantity": round(base_qty, 2),
        "unit": unit,
        "waste_factor": waste_factor,
        "waste_source": waste_source,
        "quantity_with_waste": round(qty_with_waste, 2),
        "waste_amount": round(qty_with_waste - base_qty, 2),
        "calculation_notes": (
            f"Applied {int(round((waste_factor - 1) * 100))}% waste factor "
            + ("(org profile)" if waste_source == "profile"
               else "(agnostic default - confirm org convention)")),
    }


def convert_units(
    quantity: float, from_unit: str, to_unit: str, material_type: str = "general"
) -> Dict[str, Any]:
    """Convert between common construction units."""
    key = f"{from_unit}_to_{to_unit}"
    if material_type != "general":
        key_material = f"{key}_{material_type}"
    else:
        key_material = key
    factor = UNIT_CONVERSIONS.get(key_material)
    if factor is None:
        factor = UNIT_CONVERSIONS.get(key)
    if factor is None:
        material_note = (
            f" (material: {material_type})" if material_type != "general" else ""
        )
        raise ValueError(
            f"No conversion defined for {from_unit!r} -> {to_unit!r}{material_note}."
        )
    return {
        "original_quantity": quantity,
        "original_unit": from_unit,
        "converted_quantity": round(quantity * factor, 2),
        "converted_unit": to_unit,
        "conversion_factor": factor,
        "material_type": material_type,
    }


def check_dbe_requirements(
    project_id: str, project_value: float, dbe_goal_percent: float
) -> Dict[str, Any]:
    """Compute the DBE goal amount and a generic compliance checklist."""
    dbe_goal_amount = project_value * (dbe_goal_percent / 100)
    return {
        "project_id": project_id,
        "project_value": project_value,
        "dbe_goal_percent": dbe_goal_percent,
        "dbe_goal_amount": round(dbe_goal_amount, 2),
        "requirements": [
            "Submit DBE commitment letters with the bid",
            "Use certified DBE firms recognized by the contracting agency",
            "Document good-faith efforts if the goal is not met",
            "Report DBE payments per the contract schedule",
        ],
        "resources": [
            "Consult the contracting agency's DBE directory and certification rules",
            "Retain good-faith-effort documentation",
        ],
    }
