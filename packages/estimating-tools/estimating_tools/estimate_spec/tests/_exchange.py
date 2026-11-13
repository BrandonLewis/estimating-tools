"""The golden read model for fieldbook's exchange tests (fieldbook spec,
"Testing"), and the fieldbook config that lays it out -- what delivery 2's
``from_model`` must produce from it. The payload carries two items; an
item with two activities on one cost code; a labor resource timed in
HOURS; an equipment resource timed in DAYS; an unlinked labor resource
whose name a library rate has at another cost (a local rate, suffixed); an
activity with a two-line description; a quoted material line and a plugged
subcontract line. The estimate envelope is HeavyBook's fixture's, emptied
of its sections."""
from __future__ import annotations

import copy
from pathlib import Path

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import identity
from estimating_tools.estimate_spec.tests._fieldbook import fieldbook_pack
from estimating_tools.heavybook.tests import _readback as H

EXPORTED_AT = "2026-11-08T09:00:00Z"
HOST = "www.bidsheet.ai"
ITEM1, ITEM2 = "1 - MOBILIZATION", "2 - 8IN MAIN"


def _item(iid, number, description, unit, quantity):
    return {"id": iid, "item_number": number, "item_code": "", "description": description,
            "unit": unit, "quantity": quantity, "schedule_quantity": quantity,
            "quantity_override": None, "scope": "included", "scope_note": "",
            "section_id": None, "estimated_unit_price": None, "bid_unit_price_override": None,
            "v": f"a0000000000000{iid}"}


def _activity(aid, item_id, name, code, description, sort_order):
    return {"id": aid, "estimate_item_id": item_id, "parent_id": None,
            "assembly_type": "GENERIC", "name": name, "description": description,
            "activity_code": {"id": 70 + aid, "code": code}, "count": 1,
            "sort_order": sort_order, "hours_per_shift": "8.0", "production_rate": None,
            "production_unit": "DAYS", "crew_factor": "1.000", "duration_shifts": None,
            "crew_id": None, "steps": [], "cost": "0", "cost_split": {}, "manhours": "0",
            "v": f"b0000000000000{aid}"}


def _resource(rid, activity_id, ctype, name, quantity, unit_cost, sort_order, *, unit="",
              time_value=None, time_unit="", description="", labor=None, equipment=None):
    return {"id": rid, "activity_id": activity_id, "component_type": ctype, "name": name,
            "description": description, "trade": name if ctype == "labor" else "",
            "quantity": quantity, "unit": unit, "unit_cost": unit_cost,
            "time_value": time_value, "time_unit": time_unit, "includes_burden": False,
            "burden_percentage": None, "labor_cost_basis": "production",
            "sort_order": sort_order, "cost": "0", "managed_by": None, "labor_rate_id": labor,
            "equipment_rate_id": equipment, "material_cost_id": None,
            "activity_code_id": None, "pieces": None, "parent_component_id": None,
            "v": f"c0000000000000{rid}"}


def payload() -> dict:
    estimate = copy.deepcopy(H.fixture_doc()["estimate"])
    estimate["sections"] = []
    return {
        "estimate": estimate,
        "items": [_item(11, "1", "Mobilization", "LS", "1.00"),
                  _item(12, "2", "8-inch water main", "LF", "640.00")],
        "elements": [], "crews": [], "shares": [],
        "activities": [
            _activity(21, 11, "Mobilize crew and equipment", "01-100",
                      "Two days: yard load-out, haul\nSet up the yard", 1),
            _activity(22, 12, "Trench excavation", "02-100", "", 1),
            _activity(23, 12, "Trench excavation, second heading", "02-100", "", 2)],
        "resources": [
            _resource(31, 21, "labor", "Superintendent", "1", "95.00", 0, time_value="2",
                      time_unit="DAYS", labor=1),
            _resource(32, 22, "labor", "Pipelayer", "2", "81.20", 0, time_value="16",
                      time_unit="HOURS", labor=2),
            _resource(33, 22, "equipment", "Excavator, 320 class", "1", "145.00", 1,
                      time_value="8", time_unit="DAYS", equipment=5),
            _resource(34, 22, "material", "8-inch ductile iron pipe", "640", "42.00", 2,
                      unit="LF", description="QUOTE · Pipe Vendor A"),
            _resource(35, 23, "labor", "Laborer", "2", "40.00", 0, time_value="8",
                      time_unit="DAYS"),
            _resource(36, 23, "subcontractor", "Haul, import backfill", "460", "18.00", 1,
                      unit="CY", description="PLUG")],
        "rates": {"labor": [{"id": 1, "classification": "Superintendent", "unit": "HR",
                             "rate": "95.00"},
                            {"id": 2, "classification": "Pipelayer", "unit": "HR",
                             "rate": "81.20"},
                            {"id": 3, "classification": "Laborer", "unit": "HR",
                             "rate": "36.00"}],
                  "equipment": [{"id": 5, "name": "Excavator, 320 class", "unit": "HR",
                                 "rate": "145.00"}],
                  "material": []},
    }


def _ids(prefix, n, **more):
    return {"id": n, "v": f"{prefix}0000000000000{n}", **more}


def config() -> dict:
    zero = {"labor": 0, "equipment": 0, "material": 0, "subcontract": 0}
    return {
        "project": "Exchange golden", "shift_hours": 8,
        "markup": {"overhead": dict(zero), "insurance": dict(zero), "profit": dict(zero),
                   "bond_pct": 0},
        "rate_table": [
            {"trade": "Superintendent", "rate": 95, "kind": "labor",
             "exchange": {"tag": "RATE", "ref": "labor:1"}},
            {"trade": "Pipelayer", "rate": 81.2, "kind": "labor",
             "exchange": {"tag": "RATE", "ref": "labor:2"}},
            {"trade": "Laborer", "rate": 36, "kind": "labor",
             "exchange": {"tag": "RATE", "ref": "labor:3"}},
            {"trade": "Excavator, 320 class", "rate": 145, "kind": "equipment",
             "exchange": {"tag": "RATE", "ref": "equipment:5"}},
            {"trade": "Laborer (local)", "rate": 40, "kind": "labor"}],
        "items": [
            {"recipe": "lump_sum", "sheet": ITEM1, "item_no": "1", "description": "Mobilization",
             "qty": 1, "uom": "LS", "exchange": _ids("a", 11),
             "labor": [{"slot": "01", "cost_code": "01-100",
                        "description": "Mobilize crew and equipment",
                        "notes": ["Two days: yard load-out, haul", "Set up the yard"],
                        "exchange": _ids("b", 21),
                        "crew": [{"trade": "Superintendent", "count": 1, "days": 2,
                                  "exchange": _ids("c", 31, ref="labor:1",
                                                   time_unit="DAYS")}]}]},
            {"recipe": "lump_sum", "sheet": ITEM2, "item_no": "2",
             "description": "8-inch water main", "qty": 640, "uom": "LF",
             "notes": ["Trench to 6 ft max"],      # the item's scope note: local
             "exchange": _ids("a", 12),
             "labor": [
                 {"slot": "01", "cost_code": "02-100", "description": "Trench excavation",
                  "exchange": _ids("b", 22),
                  "crew": [{"trade": "Pipelayer", "count": 2, "days": 16,
                            "exchange": _ids("c", 32, ref="labor:2", time_unit="HOURS")},
                           {"trade": "Excavator, 320 class", "count": 1, "days": 8,
                            "exchange": _ids("c", 33, ref="equipment:5", time_unit="DAYS")}],
                  "lines": [{"cost_type": "material", "name": "8-inch ductile iron pipe",
                             "qty": 640, "uom": "LF", "unit_price": 42, "source": "quote",
                             "vendor": "Pipe Vendor A", "exchange": _ids("c", 34)}]},
                 {"slot": "02", "cost_code": "02-100",
                  "description": "Trench excavation, second heading",
                  "exchange": _ids("b", 23),
                  "crew": [{"trade": "Laborer (local)", "count": 2, "days": 8,
                            "exchange": _ids("c", 35, time_unit="DAYS")}],
                  "lines": [{"cost_type": "subcontract", "name": "Haul, import backfill",
                             "qty": 460, "uom": "CY", "unit_price": 18,
                             "exchange": _ids("c", 36)}]}]},
        ],
    }


def generate(*, exported_at: str = EXPORTED_AT, doc: dict | None = None):
    """The golden book, as an openpyxl workbook."""
    base = identity.Baseline(payload=doc or payload(), host=HOST, exported_at=exported_at)
    return B.generate(config(), fieldbook_pack(), exchange=base)


def book(where: Path, *, exported_at: str = EXPORTED_AT, doc: dict | None = None) -> Path:
    """The golden book, saved as ``where/golden.xlsx``."""
    where = Path(where)
    where.mkdir(parents=True, exist_ok=True)
    path = where / "golden.xlsx"
    generate(exported_at=exported_at, doc=doc).save(path)
    return path
