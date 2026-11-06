"""Shared builders for the bm-sync tests: a two-package spec, quotes, and a BidSheet.ai export."""
from __future__ import annotations

from estimating_tools.quotes.model import CanonicalQuote, QuoteLine


def _line(cost_type, name, qty, uom, unit_price, package=None):
    line = {"cost_type": cost_type, "name": name, "qty": qty, "uom": uom, "unit_price": unit_price,
            "source": "quote" if package else "plug"}
    if package:
        line["package"] = package
    return line


def _crew(*rows):
    return [{"trade": t, "count": c, "days": d} for t, c, d in rows]


def _takeoff(qty):
    return {"kind": "count", "units": [{"label": "Total", "count": qty}]}


def spec_two_packages() -> dict:
    """Items 61 (rebar), 62 (ready-mix) and 39 (no package); two work packages."""
    return {
        "project": "Fixture Bridge",
        "bid_date": "2026-10-28",
        "shift_hours": 8,
        "markup": {
            "overhead": {"labor": 0.12, "equipment": 0.10, "material": 0.05, "subcontract": 0.03},
            "insurance": {"labor": 0.02, "equipment": 0.01, "material": 0.0, "subcontract": 0.0},
            "profit": {"labor": 0.12, "equipment": 0.10, "material": 0.06, "subcontract": 0.04},
            "bond_pct": 0.012,
        },
        "rate_table": [
            {"trade": "Foreman", "rate": 136.46},
            {"trade": "Laborer", "rate": 88.37},
            {"trade": "Equipment Operator", "rate": 101.0},
            {"trade": "Excavator, 320 class", "rate": 66.0, "kind": "equipment"},
            {"trade": "Foreman pickup, 3/4-ton 4x4", "rate": 8.5, "kind": "equipment"},
            {"trade": "Fuel and lube, Excavator, 320 class", "rate": 28.0, "kind": "equipment"},
        ],
        "items": [
            {"item_no": "61", "sheet": "61", "description": "Reinforcing steel", "uom": "LB", "qty": 1000,
             "recipe": "line_item", "takeoff": _takeoff(1000),
             "labor": [
                 {"slot": "01", "cost_code": "51-100", "description": "Place rebar",
                  "crew": _crew(("Foreman", 1, 2), ("Laborer", 2, 2),
                                ("Excavator, 320 class", 1, 1),
                                ("Foreman pickup, 3/4-ton 4x4", 1, 2),
                                ("Fuel and lube, Excavator, 320 class", 1, 1)),
                  "lines": [
                      _line("subcontract", "Rebar furnished and placed", 1000, "LB", 1.8,
                            "Reinforcing steel"),
                      _line("material", "Couplers", 40, "EA", 12.5, "Reinforcing steel"),
                      _line("other", "Small tools", 48, "HR", 1.25)]},
                 {"slot": "02", "cost_code": "51-100", "description": "Place rebar, self-performed",
                  "carry": "self_perform", "crew": _crew(("Laborer", 1, 1)), "lines": []},
             ]},
            {"item_no": "62", "sheet": "62", "description": "Structural concrete", "uom": "CY", "qty": 139,
             "recipe": "line_item", "takeoff": _takeoff(139),
             "labor": [
                 {"slot": "01", "cost_code": "51-200", "description": "Place concrete",
                  "crew": _crew(("Foreman", 1, 1)),
                  "lines": [
                      _line("material", "Ready-mix 4000 psi", 146, "CY", 185, "Ready-mix concrete"),
                      _line("equipment", "Pump truck", 1, "LS", 1800)]}]},
            {"item_no": "39", "sheet": "39", "description": "Dewatering", "uom": "CY", "qty": 837,
             "recipe": "line_item", "takeoff": _takeoff(837),
             "labor": [
                 {"slot": "01", "cost_code": "39-100", "description": "Dewater",
                  "crew": _crew(("Foreman", 1, 2)),
                  "lines": [_line("equipment", "Dewatering", 1, "LS", 5400)]}]},
        ],
        "work_packages": [
            {"name": "Reinforcing steel", "kind": "subcontract", "items": ["61"], "selected": "ARR"},
            {"name": "Ready-mix concrete", "kind": "supply", "items": ["62"], "selected": "ARR"},
        ],
    }


def quote(vendor, package, lines, **header) -> CanonicalQuote:
    return CanonicalQuote(vendor_name=vendor, work_package_name=package, lines=list(lines), **header)


def acme_rebar() -> CanonicalQuote:
    return quote("Acme Rebar", "Reinforcing steel",
                 [QuoteLine(schedule_name="Base", item_number="61", unit_price=1.65, quantity=1000)],
                 quote_date="2026-10-27", quote_ref="Q-100", conditions={"Couplers included": "yes"})


def bolt_rebar() -> CanonicalQuote:
    return quote("Bolt Rebar", "Reinforcing steel",
                 [QuoteLine(schedule_name="Base", item_number="61", unit_price=1.72, quantity=1000)],
                 amount=1720.0)


class ExportBuilder:
    """Builds the documented export dict."""

    def __init__(self):
        self._packages: list[dict] = []
        self._orgs: list[dict] = []

    def _pkg(self, name):
        return next(p for p in self._packages if p["name"] == name)

    def package(self, name, work_package_id, items=None, carry_mode="automatic",
                selected_quote=None, self_perform=False, new_quotes_since_carry=False):
        self._packages.append({
            "name": name, "work_package_id": work_package_id,
            "estimate_package_id": work_package_id + 1000,
            "items": [{"item_number": n, "work_package_item_id": w, "project_bid_item_id": w + 2000,
                       "estimate_item_id": w + 3000, "schedule_name": "Base"}
                      for n, w in (items or {}).items()],
            "carry_mode": carry_mode, "selected_quote": selected_quote,
            "self_perform": self_perform, "new_quotes_since_carry": new_quotes_since_carry,
            "quotes": [], "components": {}})
        return self

    def quote(self, package, quote_id, vendor_name, vendor_id, revision=1, status="received",
              amount=None, lines=(), allocations=(), separate_acceptance_permitted=None,
              acceptance_notes=None, is_current=True):
        line_items = [{"amount": None, "is_included": True, "is_alternate": False, **ln}
                      for ln in lines]
        self._pkg(package)["quotes"].append({
            "quote_id": quote_id, "vendor_name": vendor_name, "vendor_id": vendor_id,
            "revision": revision, "status": status, "amount": amount,
            "separate_acceptance_permitted": separate_acceptance_permitted,
            "acceptance_notes": acceptance_notes, "is_current": is_current,
            "line_items": line_items,
            "allocations": [{"accept_alternate": False, **a} for a in allocations]})
        return self

    def organization(self, id, name):
        self._orgs.append({"id": id, "name": name})
        return self

    def components(self, work_package_item_id_or_item_no, assembly_id, comps):
        """Components of one assembly on an item; the assembly joins the item's `assemblies`."""
        key = work_package_item_id_or_item_no
        for p in self._packages:
            for it in p["items"]:
                if key in (it["work_package_item_id"], it["item_number"]):
                    p["components"].setdefault(it["item_number"], []).extend(
                        {"assembly_id": assembly_id, **c} for c in comps)
                    ids = p.setdefault("assemblies", {}).setdefault(it["item_number"], [])
                    if assembly_id not in ids:
                        ids.append(assembly_id)
                    return self
        raise KeyError(key)

    def build(self) -> dict:
        return {"project_id": 1234, "estimate_id": 100, "organizations": list(self._orgs),
                "packages": list(self._packages)}


def export_builder() -> ExportBuilder:
    return ExportBuilder()
