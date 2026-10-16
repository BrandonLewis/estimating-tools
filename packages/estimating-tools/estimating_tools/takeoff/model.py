"""The open takeoff model — measured takeoff rows to bridge into BidSheet.ai.
Pure: stdlib only. A row resolves to a bid-item quantity (kind='quantity'), a
cloned assembly (kind='material'), or a structure (kind='structure').

A quantity row may carry `elements`: the per-element breakdown behind the
summed quantity, used to plan estimate-structure sections (the takeoff's home
in BidSheet.ai v2). Each entry is
    {"name": str, "global_id": str, "section_type": str, "count": int,
     "length_ft": float|None, "width_ft": float|None, "height_ft": float|None,
     "measure": str|None, "value_si": float|None,
     "cy": float|None, "volume_factor": float|None}
with dimensions in FEET (they drive the Structures grid's CY computation).
`global_id`/`measure`/`value_si` (added 0.1.32) tie an element back to the
IFC for `est-takeoff audit`; entries without them (older takeoffs) still
load. `cy` (SIGNED — a deduct is a negative CY) and `volume_factor` (e.g. 0.5
for a triangular wedge) are passed straight through to the section dimensions
so an element that knows its volume but not a full L×W×H box — or a deduct, or
a wedge — round-trips instead of being forced through the box formula
(issue #210). All optional and backward compatible: rows without them load
fine."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

VALID_KINDS = ("quantity", "material", "structure")


@dataclass
class TakeoffRow:
    description: str
    kind: str
    quantity: float
    unit: str = ""
    cost_code: str | None = None
    item_number: str | None = None
    schedule: str | None = None
    assembly_ref: str | None = None
    structure_id: str | None = None
    sections: list = field(default_factory=list)
    dimensions: dict | None = None
    waste_factor: float | None = None
    notes: str = ""
    # per-element breakdown behind a summed quantity row (see module docstring);
    # defaults empty, and from_json tolerates its absence.
    elements: list = field(default_factory=list)

    def __post_init__(self):
        if self.kind not in VALID_KINDS:
            raise ValueError(
                f"invalid takeoff kind {self.kind!r} for row {self.description!r} "
                f"(expected one of {list(VALID_KINDS)})"
            )


@dataclass
class CanonicalTakeoff:
    organization_id: int
    project_ref: str | None = None
    rows: list = field(default_factory=list)

    @classmethod
    def from_json(cls, text: str) -> "CanonicalTakeoff":
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(
                f"takeoff JSON must be a JSON object, got {type(data).__name__}"
            )
        if "organization_id" not in data:
            raise ValueError("takeoff JSON is missing required 'organization_id'")
        rows_data = data.get("rows", [])
        if not isinstance(rows_data, list):
            raise ValueError("takeoff 'rows' must be a list")
        rows = [TakeoffRow(**r) for r in rows_data]
        return cls(
            organization_id=data["organization_id"],
            project_ref=data.get("project_ref"),
            rows=rows,
        )
