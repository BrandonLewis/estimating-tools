"""Work-package spreads: what each `Sub <package>` sheet shows, and the config
transform that makes the item sheets read their package prices from it.

`build_package_frames(spec, quotes)` levels the vendor quote files against the
spec's `work_packages[]` into one `PackageFrame` per package: the package's
task lines (the lines tagged `package: <name>`), a column per quoting vendor
(then blank spare columns for quotes that arrive late), the bid conditions,
and the selector (`selected`, per-item `picks`, `carry`). Every defect a spread
could not be levelled with is a `PackageError` naming the package.

`apply_packages(config, frames)` returns a deep copy of the config in which
every package line's `unit_price`, `source` and `vendor` are `{ref:}`
placeholders into the package's sheet, and every `carry: self_perform` task of
a packaged item has its crew `days` and its non-package lines' `qty` scaled by
that item's self-perform factor (1 while ARR prices the item, 0 once a vendor
or CARRY does). An item listed by several packages is switched off by the
FIRST `kind: subcontract` package, in `work_packages` order, that lists it: its
self-perform tasks read that package's factor only. A supply package never
switches a self-perform task (the material is furnished; ARR still installs).

The keys the transform adds (`index`, `plug`, `qty_full`, `days_full`, the
renderer's hints `pkg_ref`, `u_tag`, `arr_qty`, `arr_price`, `arr_days` and a
task's `sp_note`, and the top-level `_packages`) exist only on the transformed
copy; the schema never sees them. A package line's `source` becomes `pkg`.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace

from estimating_tools.quotes.model import CanonicalQuote

ARR = "ARR"
CARRY = "CARRY"


class PackageError(ValueError):
    pass


@dataclass
class VendorColumn:
    name: str
    quote_ref: str
    surcharge: float
    lump_sum: bool
    cells: dict[str, float | str]  # line key -> price, "incl" or "excl"
    is_spare: bool = False
    #: line key -> the share of a lump sum prorated onto that line (lump sums only).
    prorated: dict[str, float] = field(default_factory=dict)
    #: The quote's lump-sum total (lump sums only).
    lump_amount: float | None = None
    conditions: dict[str, str] = field(default_factory=dict)
    #: The `amount - priced extensions` remainder prorated over the unpriced
    #: lines, when the quote has an amount AND priced lines (else None).
    remainder: float | None = None
    #: The conditions-grid rows this vendor's alternates add ("Alternate: <line>").
    alternates: list[str] = field(default_factory=list)


@dataclass
class PackageLine:
    key: str  # f"{item_no}/{slot}/{line_index}"
    item_no: str
    item_sheet: str
    slot: str
    line_index: int
    name: str
    uom: str
    qty: float | str
    plug_price: float
    task_key: str


@dataclass
class PackageFrame:
    name: str
    kind: str
    title: str
    items: list[str]
    lines: list[PackageLine]
    vendors: list[VendorColumn]
    selected: str
    picks: dict[str, str]
    carry: dict[str, float]
    conditions: list[str]
    detail_rows: list[tuple[str, float | str, str, str]]
    item_sheets: dict[str, str] = field(default_factory=dict)
    frames_notes: list[str] = field(default_factory=list)
    strategy: str = ""
    #: item_no -> the task keys of its `carry: self_perform` tasks this package
    #: switches off (the first package listing the item; see `apply_packages`).
    sp_tasks: dict[str, list[str]] = field(default_factory=dict)

    def effective_source(self, item_no) -> str:
        return self.picks.get(str(item_no), self.selected)

    def carry_for(self, ln: PackageLine) -> float | None:
        """The CARRY $/unit of a package line: `carry["<item_no>/<line name>"]`,
        else `carry["<item_no>"]` (validation allows the bare item key only on
        an item with one package line), else None."""
        return self.carry.get(f"{ln.item_no}/{ln.name}", self.carry.get(ln.item_no))

    def as_scope(self) -> dict:
        """The package as the pack's renderer reads it.

        Besides the by-name maps (`cells`, `prorated`, condition `cells`), a
        line and a condition carry one flat field per vendor column, by the
        column's position `i` in `vendors`: a line's `c<i>` (its price,
        "incl"/"excl", or "" when that vendor did not quote it) and `n<i>`
        (the "prorated from $<lump sum> lump sum" note, or ""), a condition's `t<i>`. A template
        reads them as `{it.c{v.idx}}` inside a band over `vendors`.
        """
        from estimating_tools.estimate_spec.build import literal

        quoted = [v for v in self.vendors if not v.is_spare]
        lines = []
        for ln in self.lines:
            line = {
                "key": ln.key, "item_no": ln.item_no, "item_sheet": ln.item_sheet,
                "task_key": ln.task_key, "line_index": ln.line_index, "name": ln.name,
                "code": ln.task_key[len("task["):-1],
                "uom": ln.uom, "qty": ln.qty, "plug_price": ln.plug_price,
                "pick": self.effective_source(ln.item_no), "carry": self.carry_for(ln),
                "item_pick": literal(self.picks.get(ln.item_no, "")),
                "carry_price": "" if self.carry_for(ln) is None else self.carry_for(ln),
                "cells": {v.name: v.cells[ln.key] for v in quoted if ln.key in v.cells},
            }
            prorated = {v.name: v.prorated[ln.key] for v in quoted if ln.key in v.prorated}
            if prorated:
                line["prorated"] = prorated
                line["prorated_from"] = {v.name: v.lump_amount for v in quoted
                                         if ln.key in v.prorated}
            for i, v in enumerate(self.vendors):
                line[f"c{i}"] = v.cells.get(ln.key, "")
                line[f"n{i}"] = _prorated_note(v, ln.key)
                # the cell's style: a prorated share is derived, a typed price input
                line[f"p{i}"] = "derived" if ln.key in v.prorated else "input"
            lines.append(line)
        conditions = []
        # Condition texts and answers come from the quote files: their braces
        # are literal (`build.literal`), never placeholders.
        for text in self.conditions:
            cond = {"text": literal(text),
                    "cells": {v.name: literal(v.conditions[_fold(text)]) for v in quoted
                              if _fold(text) in v.conditions}}
            for i, v in enumerate(self.vendors):
                cond[f"t{i}"] = literal(v.conditions.get(_fold(text), ""))
            conditions.append(cond)
        return {
            "name": self.name, "title": self.title, "kind": self.kind,
            "strategy": self.strategy, "selected": literal(self.selected),
            "vendor_names": [v.name for v in self.vendors],
            "vendors": [{"idx": i, "name": literal(v.name), "quote_ref": literal(v.quote_ref),
                         "role": "spare" if v.is_spare else "lump" if v.lump_sum else "quoted",
                         # a lump sum's per-line prices are derived, every other column's typed
                         "price": "derived" if v.lump_sum else "input",
                         "lump": "LUMP SUM" if v.lump_sum else "", "surcharge": v.surcharge}
                        for i, v in enumerate(self.vendors)],
            "lump_flag": "LUMP SUM" if any(v.lump_sum for v in quoted) else "",
            "items": [{"item_no": n, "item_sheet": self.item_sheets.get(n, ""),
                       "source": self.effective_source(n),
                       "arr_sp": "+".join(f"{{ref:{self.item_sheets.get(n, '')}!{key}.arr_cost}}"
                                          for key in self.sp_tasks.get(n, [])) or "0"}
                      for n in self.items],
            "lines": lines,
            "conditions": conditions,
            "surcharges": [{"vendor": v.name, "pct": v.surcharge} for v in quoted],
            "detail_rows": [{"label": label, "qty": qty, "unit": unit, "source": source}
                            for label, qty, unit, source in self.detail_rows],
        }


def _prorated_note(v: VendorColumn, key: str) -> str:
    if key not in v.prorated:
        return ""
    if v.remainder is not None:
        return (f"prorated from ${v.remainder:,.2f} remainder of ${v.lump_amount:,.2f} "
                "lump sum")
    return f"prorated from ${v.lump_amount:,.2f} lump sum"


def _money(value) -> str:
    return f"${value:,.2f}"


def _alternate_text(ql, target: PackageLine) -> str:
    """An alternate's price as the conditions grid shows it."""
    if not ql.is_included:
        text = "excl"
    elif ql.folded_into:
        text = f"incl in {ql.folded_into}"
    elif ql.unit_price is not None:
        text = f"{_money(ql.unit_price)} / {target.uom}" if target.uom else _money(ql.unit_price)
    elif ql.amount is not None:
        text = f"{_money(ql.amount)} lump sum"
    else:
        text = "no price"
    if ql.exclusion_notes:
        text += f" ({ql.exclusion_notes})"
    return text


def _fold(name: str) -> str:
    return str(name).strip().casefold()


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _package_lines(name: str, item: dict) -> list[PackageLine]:
    item_no = str(item["item_no"])
    out = []
    seen = set()
    for block in item.get("labor") or []:
        slot = str(block.get("slot", ""))
        for i, line in enumerate(block.get("lines") or []):
            if line.get("package") != name:
                continue
            if line["name"] in seen:
                raise PackageError(f"{name}: item '{item_no}' has duplicate package line name "
                                   f"{line['name']!r} -- rename the lines so quotes and CARRY "
                                   "can identify each one")
            seen.add(line["name"])
            out.append(PackageLine(
                key=f"{item_no}/{slot}/{i}", item_no=item_no,
                item_sheet=str(item.get("sheet", "")), slot=slot, line_index=i,
                name=line["name"], uom=line.get("uom", ""), qty=line["qty"],
                plug_price=line["unit_price"], task_key=f"task[{block.get('cost_code', '')}]"))
    return out


def _measured_qty(line: dict, unit: str):
    """A measured takeoff line's quantity in `unit`, as the quantity unit's formula reads it."""
    def g(k):
        v = line.get(k)
        return v if _is_number(v) else 0
    cy = g("footing_cy") + g("wall_cy") + g("deck_cy") + g("other_cy")
    u = unit.upper()
    if u in ("CY", "CUYD"):
        q = cy
    elif u in ("CF", "CUFT"):
        q = cy * 27
    elif u in ("SF", "SQFT"):
        q = g("count") * g("length") * g("width")
    elif u in ("SY", "SQYD"):
        q = g("count") * g("length") * g("width") / 9
    elif u in ("LF", "LNFT"):
        q = g("count") * g("length")
    elif u in ("LB", "LBS"):
        q = g("weight_lb")
    elif u == "TON":
        q = g("weight_lb") / 2000
    elif u == "EA":
        q = g("count")
    else:
        q = 0
    return g("adjust") + q


def _detail_rows(item: dict) -> list[tuple]:
    takeoff = item.get("takeoff") or {}
    kind, uom = takeoff.get("kind"), str(item.get("uom", ""))
    if kind == "linear":
        return [(s["label"], s["length_lf"], "LF", "takeoff") for s in takeoff.get("segments") or []]
    if kind == "count":
        return [(u["label"], u["count"], "EA", "takeoff") for u in takeoff.get("units") or []]
    if kind == "measured":
        rows = []
        for ln in takeoff.get("lines") or []:
            unit = ln.get("unit") or uom
            rows.append((ln["label"], _measured_qty(ln, unit), unit, "takeoff"))
        return rows
    return []


def _latest_per_vendor(name: str, quotes: list[CanonicalQuote]) -> tuple[list[CanonicalQuote], list[str]]:
    """One quote per vendor (the later `quote_date`), in first-seen vendor order."""
    kept: dict[str, CanonicalQuote] = {}
    notes = []
    for q in quotes:
        v = _fold(q.vendor_name)
        prev = kept.get(v)
        if prev is None:
            kept[v] = q
            continue
        if (prev.quote_date or "") == (q.quote_date or ""):
            if replace(prev, vendor_name=v) != replace(q, vendor_name=v):
                raise PackageError(
                    f"{name}: two quote files for {prev.vendor_name.strip()} with the same date")
            continue
        newer, older = (q, prev) if (q.quote_date or "") > (prev.quote_date or "") else (prev, q)
        kept[v] = newer
        notes.append(f"{name}: {older.vendor_name.strip()} quote of {older.quote_date or 'no date'} "
                     f"superseded by {newer.quote_date}")
    return list(kept.values()), notes


def _line_value(name: str, vendor: str, ql, target: PackageLine):
    if not ql.is_included:
        return "excl"
    if ql.folded_into:
        return "incl"
    if ql.unit_price is not None:
        return ql.unit_price
    if ql.amount is not None:
        qty = ql.quantity if ql.quantity is not None else target.qty
        if not _is_number(qty) or not qty:
            raise PackageError(f"{name}: {vendor} prices '{target.name}' as an amount, but the "
                               f"line's qty {target.qty!r} is not a number to divide it by")
        return ql.amount / qty
    raise PackageError(f"{name}: {vendor} line for '{target.name}' has no price")


def _default_ref(q: CanonicalQuote, package: str) -> str:
    """A quoted vendor's quote-ref cell is never blank (read-back tells a
    column built from a quote file from a vendor typed into a spare by it):
    the quote's date, else the file it was read from, else its file slug."""
    from estimating_tools.quotes.files import quote_file_slug

    return (q.quote_date or getattr(q, "source_file", None)
            or quote_file_slug(q.vendor_name.strip(), package))


def _vendor_column(name: str, q: CanonicalQuote, lines: list[PackageLine],
                   surcharges: dict[str, float]) -> VendorColumn:
    vendor = q.vendor_name.strip()
    if "{" in vendor or "}" in vendor:
        raise PackageError(f"{name}: vendor name '{vendor}' may not contain '{{' or '}}'")
    by_item: dict[str, list[PackageLine]] = {}
    for ln in lines:
        by_item.setdefault(ln.item_no, []).append(ln)
    col = VendorColumn(
        name=vendor, quote_ref=q.quote_ref or _default_ref(q, name),
        surcharge=float(surcharges.get(_fold(vendor), q.surcharge or 0.0)),
        lump_sum=False, cells={},
        conditions={_fold(k): v for k, v in (q.conditions or {}).items()})
    where = getattr(q, "source_file", None) or f"{vendor}'s quote"
    claimed: dict[str, int] = {}     # package line key -> the quote line (1-based) pricing it
    for n, ql in enumerate(q.lines, start=1):
        item_no = str(ql.item_number)
        cands = by_item.get(item_no)
        if not cands:
            raise PackageError(f"{name}: {vendor} quotes item '{item_no}', which is not in the package")
        if ql.line_name is not None:
            match = [ln for ln in cands if ln.name == ql.line_name]
            if not match:
                raise PackageError(f"{name}: {vendor} quotes line '{ql.line_name}' on item "
                                   f"'{item_no}', which has no such package line")
            target = match[0]
        elif len(cands) == 1:
            target = cands[0]
        else:
            raise PackageError(f"{name}: {vendor} quotes item '{item_no}' without a line_name, "
                               f"but the item has {len(cands)} package lines")
        if ql.is_alternate:
            # An alternate never prices the bid: it is shown in the conditions
            # grid, under this vendor, for the estimator to weigh.
            text = f"Alternate: {target.name}"
            if _fold(text) in col.conditions:
                col.conditions[_fold(text)] += "; " + _alternate_text(ql, target)
            else:
                col.conditions[_fold(text)] = _alternate_text(ql, target)
                col.alternates.append(text)
            continue
        if target.key in claimed:
            raise PackageError(f"{name}: {where}: lines {claimed[target.key]} and {n} both price "
                               f"item '{item_no}' line '{target.name}' -- keep one (mark the "
                               "other is_alternate if it is an alternate)")
        claimed[target.key] = n
        if (q.amount is not None and ql.is_included and not ql.folded_into
                and ql.unit_price is None and ql.amount is None):
            continue                 # unpriced: its share of the remainder (below)
        col.cells[target.key] = _line_value(name, vendor, ql, target)
    if q.amount is not None:
        # Lump sum: `amount` prorated over every package line the quote does
        # not price (all of them when it has no lines), by plug extension.
        # With priced lines, what is prorated is the remainder: amount minus
        # the priced lines' extensions. Excluded (excl) and folded (incl)
        # lines take no share.
        unpriced = [ln for ln in lines if ln.key not in col.cells]
        if not unpriced:
            return col
        remainder = float(q.amount)
        if q.lines:
            for ln in lines:
                price = col.cells.get(ln.key)
                if not _is_number(price):
                    continue
                if not _is_number(ln.qty):
                    raise PackageError(f"{name}: {vendor} quotes a lump sum with priced lines, and "
                                       f"line '{ln.name}' needs a numeric qty to take its "
                                       "extension off the lump sum")
                remainder -= price * ln.qty
            if remainder <= 0:
                raise PackageError(
                    f"{name}: {where}: the lump sum {_money(q.amount)} less the priced lines' "
                    f"extensions leaves {_money(remainder)} for the unpriced lines "
                    f"({', '.join(ln.name for ln in unpriced)}) -- nothing to prorate")
        exts = {}
        for ln in unpriced:
            if not (_is_number(ln.qty) and _is_number(ln.plug_price)):
                raise PackageError(f"{name}: {vendor} quotes a lump sum, and line '{ln.name}' "
                                   f"needs a numeric qty and plug price to prorate it over")
            exts[ln.key] = ln.plug_price * ln.qty
        total = sum(exts.values())
        if not total:
            raise PackageError(f"{name}: {vendor} quotes a lump sum, but the package's plug "
                               f"extensions total 0, so there is nothing to prorate it by")
        col.lump_sum = True
        col.lump_amount = float(q.amount)
        if q.lines:
            col.remainder = remainder
        for ln in unpriced:
            share = remainder * exts[ln.key] / total
            col.prorated[ln.key] = share
            col.cells[ln.key] = share / ln.qty if ln.qty else 0.0
    return col


def _selector(name: str, label: str, value: str, vendors: list[VendorColumn]) -> str:
    folded = _fold(value)
    for fixed in (ARR, CARRY):
        if folded == fixed.casefold():
            return fixed
    for v in vendors:
        if not v.is_spare and _fold(v.name) == folded:
            return v.name
    names = ", ".join(v.name for v in vendors if not v.is_spare) or "none"
    raise PackageError(f"{name}: {label} '{value}' is not ARR, CARRY or a quoted vendor "
                       f"(vendors: {names})")


def build_package_frames(spec: dict, quotes: list[CanonicalQuote], *, spare_columns: int,
                         taken: set[str] | None = None) -> list[PackageFrame]:
    """One `PackageFrame` per `spec["work_packages"]` entry, in order.

    `taken` holds sheet titles already in the book (the pack's static book
    sheets); each frame's title is `sheet_title("Sub <name>", taken)` and is
    added to it, so the titles match what the book entry lays out.
    """
    from estimating_tools.estimate_spec.build import sheet_title

    taken = set() if taken is None else set(taken)
    items = {str(i["item_no"]): i for i in spec.get("items") or []}
    out = []
    switched: set[str] = set()       # items a previous package already switches off
    for pkg in spec.get("work_packages") or []:
        name = pkg["name"]
        title = sheet_title(f"Sub {name}", taken)
        taken.add(title)
        pkg_items = [str(n) for n in pkg["items"]]
        lines: list[PackageLine] = []
        detail: list[tuple] = []
        for n in pkg_items:
            item = items.get(n)
            if item is None:
                raise PackageError(f"{name}: item '{n}' is not in the spec")
            mine = _package_lines(name, item)
            if not mine:
                raise PackageError(f"{name}: item '{n}' has no line tagged package: {name} "
                                   f"(run est-estimate packages sync)")
            lines.extend(mine)
            if pkg.get("detail"):
                detail.extend(_detail_rows(item))
        own = [q for q in quotes if _fold(q.work_package_name) == _fold(name)]
        own, notes = _latest_per_vendor(name, own)
        surcharges = {_fold(k): v for k, v in (pkg.get("surcharge") or {}).items()}
        vendors = [_vendor_column(name, q, lines, surcharges) for q in own]
        vendors += [VendorColumn(name="", quote_ref="", surcharge=0.0, lump_sum=False, cells={},
                                 is_spare=True) for _ in range(spare_columns)]
        selected = _selector(name, "selected", pkg.get("selected", ARR), vendors)
        picks = {str(n): _selector(name, f"pick for item '{n}'", v, vendors)
                 for n, v in (pkg.get("picks") or {}).items()}
        conditions = list(pkg.get("conditions") or [])
        listed = {_fold(c) for c in conditions}
        for q in own:  # a condition a vendor states that the package does not list is kept
            for c in q.conditions or {}:
                if _fold(c) not in listed:
                    listed.add(_fold(c))
                    conditions.append(c)
        for v in vendors:  # then the vendors' alternates, one row per alternate line
            for c in v.alternates:
                if _fold(c) not in listed:
                    listed.add(_fold(c))
                    conditions.append(c)
        sp_tasks = {}
        # Only a subcontract package replaces ARR's own work: a supply
        # package (material furnished) never switches a self-perform task off,
        # so an item in both follows the subcontract package.
        for n in pkg_items if pkg.get("kind", "subcontract") == "subcontract" else ():
            if n in switched:
                continue
            switched.add(n)
            sp_tasks[n] = [f"task[{b.get('cost_code', '')}]" for b in items[n].get("labor") or []
                           if b.get("carry") == "self_perform"]
        out.append(PackageFrame(
            name=name, kind=pkg.get("kind", "subcontract"), title=title, items=pkg_items,
            strategy=pkg.get("strategy", ""), sp_tasks=sp_tasks,
            lines=lines, vendors=vendors, selected=selected, picks=picks,
            carry={str(n): float(v) for n, v in (pkg.get("carry") or {}).items()},
            conditions=conditions, detail_rows=detail,
            item_sheets={n: str(items[n].get("sheet", "")) for n in pkg_items},
            frames_notes=notes))
    return out


def _paren(value) -> str:
    """A spec number or `=formula` as a parenthesised term of another formula."""
    if isinstance(value, str) and value.startswith("="):
        return f"({value[1:]})"
    return f"({value})"


#: The task head's note on a self-perform task the package switches.
SP_NOTE = "(self-perform: off when a vendor is carried)"


def _scaled(value, factor_ref: str) -> str:
    if isinstance(value, str) and value.startswith("="):
        return f"=({value[1:]})*{factor_ref}"
    return f"={value}*{factor_ref}"


def apply_packages(config: dict, frames: list[PackageFrame], *, shift_hours: float) -> dict:
    """A deep copy of `config` whose package-driven cells read the package sheets.

    `shift_hours` is part of the interface (the generator passes the spec's);
    the factor is applied to days, so the transform itself does not use it.
    """
    out = copy.deepcopy(config)
    items = {str(i["item_no"]): i for i in out.get("items") or []}
    for item in items.values():
        for block in item.get("labor") or []:
            for i, line in enumerate(block.get("lines") or []):
                line["index"] = i
    for f in frames:
        for ln in f.lines:
            item = items[ln.item_no]
            (block,) = [b for b in item.get("labor") or [] if str(b.get("slot", "")) == ln.slot]
            line = block["lines"][ln.line_index]
            ref = f"{f.title}!lines.line[{ln.key}]"
            line["plug"] = line["unit_price"]
            line["qty_full"] = line["qty"]
            line["unit_price"] = f"={{ref:{ref}.rate}}"
            # `source: pkg` makes the item sheet's Source cell read the package
            # sheet's QUOTE/PLUG label at `{pkg_ref}.src_label` (the task unit's
            # `src_pkg`); the vendor cell reads the package sheet's source.
            line["source"] = "pkg"
            line["pkg_ref"] = ref
            line["vendor"] = f"={{ref:{ref}.src}}"
            line["u_tag"] = "PKG"
            line["arr_qty"] = _paren(line["qty_full"])
            line["arr_price"] = _paren(line["plug"])
        for n in f.sp_tasks:         # the items this package switches (see build_package_frames)
            factor = f"{{ref:{f.title}!items.item[{n}].sp_factor}}"
            for block in items[n].get("labor") or []:
                if block.get("carry") != "self_perform":
                    continue
                block["sp_note"] = SP_NOTE
                for member in block.get("crew") or []:
                    if "days" in member:
                        member["days_full"] = member["days"]
                        member["days"] = _scaled(member["days"], factor)
                        member["u_tag"] = "SP"
                        member["arr_days"] = _paren(member["days_full"])
                for line in block.get("lines") or []:
                    if line.get("package") is None:
                        line["qty_full"] = line["qty"]
                        line["qty"] = _scaled(line["qty"], factor)
                        line["u_tag"] = "SP"
                        line["arr_qty"] = _paren(line["qty_full"])
    out["_packages"] = [f.as_scope() for f in frames]
    return out
