"""The open rate-library model — an org's labor/equipment/material rates.
Pure: stdlib only. Fields map to BidSheet.ai's create_labor_rate / create_equipment_rate /
create_material_cost."""
from __future__ import annotations

from dataclasses import dataclass, field

# The rate_type discriminator values the importer routes on.
VALID_RATE_TYPES = {"labor", "equipment", "material"}


@dataclass
class LaborRate:
    """A labor classification rate. base_hourly_rate is the unburdened wage; the burdened
    rate is auto-computed by BidSheet.ai from burden_percentage."""

    classification: str
    base_hourly_rate: float
    burden_percentage: float = 35.0
    region: str = ""
    trade: str = ""
    is_union: bool = False
    union_local: str = ""
    source: str = ""


@dataclass
class EquipmentRate:
    """An equipment hourly rate."""

    equipment_type: str
    hourly_rate: float
    description: str = ""
    region: str = ""
    includes_operator: bool = False
    source: str = ""


@dataclass
class MaterialCost:
    """A material unit cost."""

    material_name: str
    unit_cost: float
    unit: str = ""
    category: str = ""
    supplier: str = ""


@dataclass
class CanonicalRateLibrary:
    """An org's rate library — three typed lists, one per BidSheet.ai rate tool."""

    labor_rates: list[LaborRate] = field(default_factory=list)
    equipment_rates: list[EquipmentRate] = field(default_factory=list)
    material_costs: list[MaterialCost] = field(default_factory=list)
