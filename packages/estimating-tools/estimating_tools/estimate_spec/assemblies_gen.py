"""Generate BidSheet.ai ``bulk_create_assemblies`` payloads from an estimate spec.

Per labor block (task) of each item: a CREW assembly from the crew and a
GENERIC "lines" assembly from the cost lines, package-tagged lines included,
following the conventions of the bid's first push. Pure: spec in, dicts out.
Also the re-push plan against a bid's ``bm-assembly-ids.json`` and the compare
against an earlier push's payload files (the regression check).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from estimating_tools.estimate_spec._names import same_name
from estimating_tools.estimate_spec.bm_sync.sidecar import plug_entry, plug_text
from estimating_tools.estimate_spec.summarize import build_ctx, evaluate

SOURCE = "ESTIMATING_PLUGIN"
LINES_DESCRIPTION = "cost lines from the fieldbook task (plugs unless a vendor is named)"
_LINE_TYPES = {"material": "material", "subcontract": "subcontractor",
               "other": "other", "equipment": "equipment"}
_TOTAL_TYPES = ("labor", "equipment", "material", "subcontractor", "other")
NAME_MAX = 255      # BidSheet.ai Assembly.name / Component.name max_length
_POSITION_PREFIX = re.compile(r"^\d{2} ")   # "02 Couplers": the line's position, as the push planner strips it


def _strip_prefix(name: str) -> str:
    return _POSITION_PREFIX.sub("", name, count=1)


class GenError(ValueError):
    """The spec cannot be turned into assemblies (e.g. a trade with no rate)."""


@dataclass(frozen=True)
class PackageLineRow:
    item_no: str
    slot: str
    line_name: str
    qty: float
    unit_price: float
    value: float
    component_name: str


@dataclass
class GenResult:
    payloads: dict[str, list[dict]]
    report: str
    package_lines: dict[str, list[PackageLineRow]]


def _r4(x):
    return round(x, 4)


def _name(text: str) -> str:
    return text[:NAME_MAX]


def _fmt(x) -> str:
    x = float(x)
    return str(int(x)) if x.is_integer() else f"{x:g}"


def _days(blk: dict, ctx: dict, pack, tag: str, carries: list | None = None) -> list[float]:
    """Each crew member's days, by the three rules of ``summarize.price_item``."""
    acts = blk.get("activities") or []
    prod_days = 0.0
    if acts:
        crew_factor = blk.get("crew_factor")
        if crew_factor is None:
            crew_factor = (pack.labor or {}).get("crew_factor_default")
        if crew_factor is None:
            raise GenError(f"item {tag} slot {blk['slot']}: activities need a crew_factor "
                           "(on the block, or the format pack's labor.crew_factor_default)")
        prod_days = sum(a["factor"] for a in acts) * crew_factor
    ctx[f"labor[{blk['slot']}].prod_days"] = prod_days
    out: list[float] = []
    for member in blk.get("crew") or []:
        raw = member["days"]
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            days = float(raw)
        elif "prod_days" in str(raw):
            days = prod_days
        elif "crew_first" in str(raw):
            days = out[0] if out else 0.0
        else:
            days = evaluate(raw, ctx, carries=carries, where=f"{tag} labor[{blk['slot']}] {member['trade']} days")
        out.append(days)
    return out


def _crew_assembly(item: dict, blk: dict, days: list[float], rates: dict, *,
                   bid: str, hours: float) -> dict | None:
    crew = blk.get("crew") or []
    if not crew or not any(days):
        return None
    full = max(days)
    components = []
    for member, d in zip(crew, days):
        trade = member["trade"]
        entry = rates.get(trade)
        if entry is None:
            raise GenError(f"item {item['item_no']} slot {blk['slot']}: "
                           f"trade {trade!r} is in no rate table")
        if not d:
            continue                        # a zero-day member contributes nothing
        n = len(components)
        count = member.get("count", 1)
        basis = f"{_fmt(count)} x {_fmt(d)} days x {_fmt(hours)} h"
        comp = {"component_type": "labor", "name": _name(f"{n + 1:02d} {trade}")}
        if entry.get("kind") == "equipment":
            comp.update(component_type="equipment", quantity=_r4(count * d * hours), unit="HR",
                        unit_cost=_r4(entry["rate"]), trade=trade, description=basis)
        elif d >= full:
            comp.update(quantity=_r4(count), unit="EA", unit_cost=_r4(entry["rate"]),
                        trade=trade, description=f"{basis}, production basis")
        else:
            comp.update(quantity=_r4(count * d * hours), unit="MH", unit_cost=_r4(entry["rate"]),
                        trade=trade, labor_cost_basis="flat", description=f"{basis}, flat")
        comp["sort_order"] = n
        components.append(comp)
    return {
        "name": _name(f"{blk['slot']} {blk.get('cost_code', '')} crew: {blk.get('description', '')}"),
        "assembly_type": "CREW",
        "description": blk.get("description", ""),
        "production_rate": _r4(full * hours),
        "production_unit": "HOURS",
        "hours_per_shift": hours,
        "basis_quantity": item.get("qty"),
        "basis_unit": item.get("uom"),
        "external_source": SOURCE,
        "external_id": f"{bid}:{item['item_no']}:{blk['slot']}:crew",
        "components": components,
    }


def _line_description(line: dict) -> str:
    vendor = line.get("vendor")
    desc = f"quote {vendor}" if line.get("source") == "quote" and vendor else "plug"
    if line.get("package"):
        desc += f"; package {line['package']}"
    return desc


def _lines_assembly(item: dict, blk: dict, *, bid: str) -> dict | None:
    lines = blk.get("lines") or []
    if not lines:
        return None
    components = []
    for n, line in enumerate(lines):
        cost_type = line.get("cost_type")
        if cost_type not in _LINE_TYPES:
            raise GenError(f"item {item['item_no']} slot {blk['slot']}: line "
                           f"{line.get('name')!r} has unknown cost_type {cost_type!r}")
        components.append({
            "component_type": _LINE_TYPES[cost_type],
            "name": _name(f"{n + 1:02d} {line['name']}"),
            "quantity": _r4(line["qty"]),
            "unit": line.get("uom"),
            "unit_cost": _r4(line["unit_price"]),
            "description": _line_description(line),
            "sort_order": n,
        })
    return {
        "name": _name(f"{blk['slot']} {blk.get('cost_code', '')} lines: material / sub / other"),
        "assembly_type": "GENERIC",
        "description": LINES_DESCRIPTION,
        "external_source": SOURCE,
        "external_id": f"{bid}:{item['item_no']}:{blk['slot']}:lines",
        "components": components,
    }


def totals_by_type(payloads_for_item: list[dict]) -> dict[str, float]:
    """Cost per component type across one item's assemblies, to cents."""
    totals = dict.fromkeys(_TOTAL_TYPES, 0.0)
    for asm in payloads_for_item:
        rate = asm.get("production_rate") or 0.0
        for c in asm["components"]:
            value = c["quantity"] * c["unit_cost"]
            if c["component_type"] == "labor" and c.get("labor_cost_basis") != "flat":
                value *= rate
            totals[c["component_type"]] = totals.get(c["component_type"], 0.0) + value
    return {k: round(v, 2) for k, v in totals.items()}


def _report(bid: str, payloads: dict, package_lines: dict, self_perform: list, skipped: list) -> str:
    n_asm = sum(len(v) for v in payloads.values())
    out = [f"# Assemblies {bid}: {len(payloads)} items, {n_asm} assemblies", ""]
    for pkg, rows in package_lines.items():
        out.append(f"## {pkg}")
        out.append("")
        for r in rows:
            out.append(f"- {r.item_no} · {r.component_name} · {_fmt(r.qty)} × "
                       f"{r.unit_price:,.2f} = {r.value:,.2f}")
        out.append(f"- total {sum(r.value for r in rows):,.2f}")
        out.append("")
    if self_perform:
        out += ["## Self-perform tasks", ""]
        out += [f"- {i} slot {s}: switched off in the workbook when {p} is carried"
                for i, s, p in self_perform]
        out.append("")
    if skipped:
        out += ["## Skipped", ""]
        out += [f"- {i} slot {s}: no crew and no lines" for i, s in skipped]
        out.append("")
    return "\n".join(out)


def generate_assemblies(spec: dict, *, bid: str, pack=None,
                        carries: list | None = None) -> GenResult:
    """Per-item CREW + GENERIC payloads, the package-line rows and a Markdown report.

    *pack* (the format pack) supplies ``labor.crew_factor_default`` for blocks
    whose activities drive ``prod_days`` without their own ``crew_factor``;
    it defaults to the bundled pack. *carries* collects formula days that
    carried forward a default, as in ``summarize.price_item``.
    """
    from estimating_tools.estimate_spec.format_pack import bundled_pack

    pack = pack or bundled_pack()
    hours = spec.get("shift_hours", 8)
    rates = {r["trade"]: r for r in spec.get("rate_table") or []}
    sub_package_of: dict[str, str] = {}
    for wp in spec.get("work_packages") or []:
        if wp.get("kind") == "subcontract":
            for no in wp.get("items") or []:
                sub_package_of.setdefault(str(no), wp["name"])
    package_lines: dict[str, list[PackageLineRow]] = {
        wp["name"]: [] for wp in spec.get("work_packages") or []}

    payloads: dict[str, list[dict]] = {}
    self_perform: list[tuple] = []
    skipped: list[tuple] = []
    for item in spec.get("items") or []:
        item_no = str(item["item_no"])
        ctx = build_ctx(item)
        out: list[dict] = []
        for blk in item.get("labor") or []:
            days = _days(blk, ctx, pack, item_no, carries)
            crew = _crew_assembly(item, blk, days, rates, bid=bid, hours=hours)
            lines = _lines_assembly(item, blk, bid=bid)
            if crew is None and lines is None:
                skipped.append((item_no, blk["slot"]))
                continue
            out += [a for a in (crew, lines) if a is not None]
            if blk.get("carry") == "self_perform" and item_no in sub_package_of:
                self_perform.append((item_no, blk["slot"], sub_package_of[item_no]))
            for line, comp in zip(blk.get("lines") or [], (lines or {}).get("components", [])):
                if line.get("package"):
                    package_lines.setdefault(line["package"], []).append(PackageLineRow(
                        item_no, blk["slot"], line["name"], line["qty"], line["unit_price"],
                        round(line["qty"] * line["unit_price"], 2), comp["name"]))
        if out:
            payloads[item_no] = out
    package_lines = {k: v for k, v in package_lines.items() if v}
    return GenResult(payloads, _report(bid, payloads, package_lines, self_perform, skipped),
                     package_lines)


# --- re-push plan ----------------------------------------------------------

def _ids_by_item(existing_ids: dict) -> dict[str, dict[str, int]]:
    """``existing_ids["assemblies"]`` as item_no -> {external_id: assembly_id}.

    Accepts the nested layout and the flat ``{external_id: id}`` one the
    2026-10-18 push wrote (item_no read from ``<bid>:<item>:<slot>:<kind>``)."""
    out: dict[str, dict[str, int]] = {}
    for key, value in (existing_ids.get("assemblies") or {}).items():
        if isinstance(value, dict):
            out.setdefault(str(key), {}).update(value)
        else:
            out.setdefault(key.split(":")[1], {})[key] = value
    return out


def _re_removals(item_no: str, payloads: list[dict], ext_of: dict[int, str],
                 sidecar) -> list[str]:
    """The ``re-remove`` lines for an item: per package and assembly, the generated
    GENERIC components tagged with that package. A record that carries the component
    name (#428) re-removes exactly the generated line named like it. A nameless record
    (written before #428) cannot, so when fewer were removed than the assembly has
    package lines, all are listed with a note to confirm. Records whose assembly is not
    in the existing ids, or not generated, are listed last."""
    by_ext = {p["external_id"]: p for p in payloads}
    out: list[str] = []
    unmatched: list[str] = []
    for pkg, ps in sorted((sidecar.packages if sidecar else {}).items()):
        groups: dict[str, list[dict]] = {}
        for rec in (plug_entry(e) for e in ps.plugs_removed.get(item_no) or []):
            aid = rec["assembly_id"]
            ext = ext_of.get(aid) if isinstance(aid, int) else None
            if ext is None:
                unmatched.append(f"- re-remove: {item_no} · {plug_text(rec)} (assembly not in the existing ids)")
            elif ext not in by_ext:
                unmatched.append(f"- re-remove: {item_no} · {plug_text(rec)} ({ext} is not generated)")
            else:
                groups.setdefault(ext, []).append(rec)
        for ext, recs in groups.items():
            names = [c["name"] for c in by_ext[ext]["components"]
                     if (c.get("description") or "").endswith(f"; package {pkg}")]
            texts = ", ".join(plug_text(r) for r in recs)
            if not names:
                out.append(f"- re-remove: {item_no} · {texts} (no {pkg} line on {ext} in the generated payload)")
                continue
            if all(r.get("name") for r in recs):
                for r in recs:
                    hits = [n for n in names if same_name(n, r["name"])]
                    if not hits:   # push matches with the position prefix stripped; so do we
                        hits = [n for n in names if same_name(_strip_prefix(n), _strip_prefix(r["name"]))]
                    if len(hits) == 1:
                        out.append(f"- re-remove: {item_no} · {hits[0]}")
                    elif not hits:
                        out.append(f"- re-remove: {item_no} · {plug_text(r)} (no {pkg} line named like it on {ext})")
                    else:
                        out += [f"- re-remove: {item_no} · {n}" for n in hits]
                        out.append(f"- note: {plug_text(r)} matches {len(hits)} {pkg} line(s) on {ext} "
                                   f"({', '.join(hits)}); confirm which to remove again")
                continue
            out += [f"- re-remove: {item_no} · {n}" for n in names]
            if len(recs) != len(names):
                out.append(f"- note: {len(recs)} of {len(names)} {pkg} line(s) on {ext} were "
                           f"removed ({texts}); confirm which to remove again")
    return out + unmatched


def repush_plan(result: GenResult, existing_ids: dict, sidecar=None) -> str:
    """Markdown: per item the ``delete_assembly`` ids, then ``bulk_create_assemblies``,
    then the plug removals (from the sidecar's ``plugs_removed``) to apply again."""
    ids = _ids_by_item(existing_ids)
    ext_of = {aid: ext for per in ids.values() for ext, aid in per.items()}
    out = ["## Re-push plan", ""]
    for item_no in list(result.payloads) + [n for n in ids if n not in result.payloads]:
        payloads = result.payloads.get(item_no)
        out += [f"### {item_no}", ""]
        out += [f"- delete_assembly {aid} ({ext})" for ext, aid in (ids.get(item_no) or {}).items()]
        if payloads is None:
            out += [f"- note: no generated payload for {item_no}", ""]
            continue
        out.append(f"- bulk_create_assemblies {item_no} ({len(payloads)} assemblies)")
        out += _re_removals(item_no, payloads, ext_of, sidecar)
        out.append("")
    return "\n".join(out)


# --- compare against an earlier push's payload files ------------------------

def _unmatched(names: list[str], others: list[str]) -> list[str]:
    left = list(others)
    out = []
    for n in names:
        hit = next((i for i, o in enumerate(left) if same_name(n, o)), None)
        if hit is None:
            out.append(n)
        else:
            left.pop(hit)
    return out


@dataclass
class CompareReport:
    n_items: int = 0
    differences: dict[str, list[str]] = field(default_factory=dict)   # item_no -> bullets

    @property
    def ok(self) -> bool:
        return not any(self.differences.values())

    def render(self) -> str:
        bad = {k: v for k, v in self.differences.items() if v}
        out = [f"compare: {self.n_items} item(s), {self.n_items - len(bad)} ok, "
               f"{len(bad)} with differences"]
        for item_no, bullets in bad.items():
            out += ["", f"## {item_no}", ""] + [f"- {b}" for b in bullets]
        return "\n".join(out) + "\n"


def _compare_item(item_no: str, gen: list[dict], old: list[dict]) -> list[str]:
    out: list[str] = []
    old_by = {p.get("external_id"): p for p in old}
    gen_by = {p["external_id"]: p for p in gen}
    out += [f"assembly missing in existing: {e}" for e in gen_by if e not in old_by]
    out += [f"assembly only in existing: {e}" for e in old_by if e not in gen_by]
    for ext, g in gen_by.items():
        o = old_by.get(ext)
        if o is None:
            continue
        if len(g["components"]) != len(o.get("components") or []):
            out.append(f"{ext}: component count {len(g['components'])} vs {len(o.get('components') or [])}")
        gt, ot = totals_by_type([g]), totals_by_type([o])
        for t in gt:
            if round(gt[t] - ot.get(t, 0.0), 2):
                out.append(f"{item_no} {ext} {t} {gt[t]:,.2f} vs {ot.get(t, 0.0):,.2f}")
    gen_names = [c["name"] for p in gen for c in p["components"]]
    old_names = [c.get("name", "") for p in old for c in p.get("components") or []]
    out += [f"name only in generated: {n}" for n in _unmatched(gen_names, old_names)]
    out += [f"name only in existing: {n}" for n in _unmatched(old_names, gen_names)]
    return out


def compare_payloads(result: GenResult, existing_dir: Path) -> CompareReport:
    """Compare the generated payloads with ``existing_dir/<item_no>.json`` (each a JSON
    list of payloads): assemblies by external_id, component counts, totals by type to
    the cent, and component names (a name cut at >= 100 characters still matches).
    Raises OSError / ValueError on an unreadable file."""
    existing_dir = Path(existing_dir)
    if not existing_dir.is_dir():
        raise FileNotFoundError(f"no such directory: {existing_dir}")
    files = {p.stem: p for p in sorted(existing_dir.glob("*.json"))}
    rep = CompareReport()
    for item_no, gen in result.payloads.items():
        rep.n_items += 1
        path = files.get(item_no)
        if path is None:
            rep.differences[item_no] = [f"file missing in existing: {item_no}.json"]
            continue
        old = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(old, list):
            raise ValueError(f"{path}: expected a JSON list of assembly payloads")
        rep.differences[item_no] = _compare_item(item_no, gen, old)
    for stem in files:
        if stem not in result.payloads:
            rep.n_items += 1
            rep.differences[stem] = [f"file only in existing: {stem}.json"]
    return rep
