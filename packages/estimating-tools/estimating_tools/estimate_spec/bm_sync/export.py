"""The BidSheet.ai export a skill hands to the planners (stdlib only).

Shape::

    {"project_id", "estimate_id", "organizations": [{"id", "name"}],
     "packages": [{<get_work_package detail incl. items[], carry_mode, selected_quote,
                    self_perform, new_quotes_since_carry>,
                   "quotes": [{<quote detail>, "line_items": [...], "allocations": [...]}],
                   "components": {"<item_number>": [{...}]},
                   "assemblies": {"<item_number>": [<assembly ids now on the item>]}}]}

``assemblies`` is optional: when present, a sidecar ``plugs_removed`` record naming an
assembly that is not among the item's is stale (replaced by a push-assemblies re-push).

A quote dict with ``is_current`` false is a superseded revision and is dropped; a missing
key means current. Keys read, per row (``id`` stands in for a missing ``quote_id``,
``line_id`` or ``allocation_id``, as MCP rows carry it)::

    package     name, work_package_id, estimate_package_id, carry_mode, selected_quote,
                self_perform, new_quotes_since_carry, items[], quotes[], components{}
    item        item_number, work_package_item_id, project_bid_item_id, estimate_item_id,
                schedule_name
    quote       quote_id, vendor_name, vendor_id, revision, status, amount,
                separate_acceptance_permitted, acceptance_notes, notes, is_current,
                line_items[], allocations[]
    line_item   item_number, line_id, unit_price, quantity, amount, is_included,
                is_alternate, exclusion_notes
    allocation  allocation_id, quote_line_item_id, allocation_type, accept_alternate
    organization  id, name (a row with no name is skipped)
"""
from __future__ import annotations

from dataclasses import dataclass, field


class ExportError(ValueError):
    """The export is not usable (stale BidSheet.ai or empty)."""


@dataclass
class ExportItem:
    work_package_item_id: int | None
    project_bid_item_id: int | None
    estimate_item_id: int | None
    schedule_name: str | None


@dataclass
class ExportQuote:
    quote_id: int
    vendor_name: str
    vendor_id: int | None
    revision: int
    status: str | None
    amount: float | None
    separate_acceptance_permitted: bool | None
    acceptance_notes: str | None
    notes: str | None
    lines: dict[str, dict] = field(default_factory=dict)    # item_number -> line


@dataclass
class ExportPackage:
    name: str
    work_package_id: int | None
    estimate_package_id: int | None
    carry_mode: str
    selected_quote: dict | None
    self_perform: bool
    new_quotes_since_carry: bool
    items: dict[str, ExportItem] = field(default_factory=dict)
    quotes: list[ExportQuote] = field(default_factory=list)
    allocations: list[dict] = field(default_factory=list)
    components: dict[str, list[dict]] = field(default_factory=dict)
    assemblies: dict[str, list[int]] = field(default_factory=dict)   # item_number -> assembly ids now on it


_LINE_KEYS = ("line_id", "unit_price", "quantity", "amount", "is_included", "is_alternate",
              "exclusion_notes")
_ALLOC_KEYS = ("allocation_id", "quote_line_item_id", "allocation_type", "accept_alternate")


def _id(row: dict, key: str):
    """`row[key]`, else its `id` (MCP rows name the primary key `id`)."""
    value = row.get(key)
    return row.get("id") if value is None else value


def _quote(q: dict) -> ExportQuote:
    lines = {str(li["item_number"]): {**{k: li.get(k) for k in _LINE_KEYS}, "line_id": _id(li, "line_id")}
             for li in q.get("line_items") or []}
    return ExportQuote(
        quote_id=_id(q, "quote_id"), vendor_name=q.get("vendor_name"), vendor_id=q.get("vendor_id"),
        revision=q.get("revision", 1), status=q.get("status"), amount=q.get("amount"),
        separate_acceptance_permitted=q.get("separate_acceptance_permitted"),
        acceptance_notes=q.get("acceptance_notes"), notes=q.get("notes"), lines=lines)


def _package(p: dict) -> ExportPackage:
    name = p.get("name")
    if "carry_mode" not in p:
        raise ExportError(f"export lacks carry_mode on package '{name}'; BidSheet.ai must be on #1556")
    items = {str(i["item_number"]): ExportItem(
        i.get("work_package_item_id"), i.get("project_bid_item_id"),
        i.get("estimate_item_id"), i.get("schedule_name")) for i in p.get("items") or []}
    quotes, allocations = [], []
    for q in p.get("quotes") or []:
        for a in q.get("allocations") or []:
            allocations.append({"quote_id": _id(q, "quote_id"), **{k: a.get(k) for k in _ALLOC_KEYS},
                                "allocation_id": _id(a, "allocation_id")})
        if q.get("is_current", True):
            quotes.append(_quote(q))
    return ExportPackage(
        name=name, work_package_id=p.get("work_package_id"),
        estimate_package_id=p.get("estimate_package_id"), carry_mode=p["carry_mode"],
        selected_quote=p.get("selected_quote"), self_perform=bool(p.get("self_perform")),
        new_quotes_since_carry=bool(p.get("new_quotes_since_carry")), items=items,
        quotes=quotes, allocations=allocations,
        components={str(k): list(v) for k, v in (p.get("components") or {}).items()},
        assemblies={str(k): list(v) for k, v in (p.get("assemblies") or {}).items()})


@dataclass
class BmExport:
    project_id: int | None
    estimate_id: int | None
    organizations: list[dict]
    packages: dict[str, ExportPackage]      # casefold name -> package

    @classmethod
    def from_dict(cls, data: dict) -> "BmExport":
        raw = data.get("packages") or []
        if not raw:
            raise ExportError("export has no packages")
        packages = {}
        for p in raw:
            pkg = _package(p)
            packages[(pkg.name or "").casefold()] = pkg
        return cls(data.get("project_id"), data.get("estimate_id"),
                   list(data.get("organizations") or []), packages)

    def package(self, name: str) -> ExportPackage | None:
        return self.packages.get(name.casefold())

    def organizations_by_name(self) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for o in self.organizations:
            name = (o.get("name") or "").strip().casefold()
            if name:
                out.setdefault(name, []).append(o["id"])
        return out
