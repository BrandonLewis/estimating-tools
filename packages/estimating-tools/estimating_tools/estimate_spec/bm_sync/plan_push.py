"""The push planner: the spec's work packages and quote files as BidSheet.ai ops (spec §1.2).

Pure: it reads the spec, the loaded quote files, the export and the sidecar and returns
a `Plan`; the skill runs the ops. Per package in `work_packages` order: create the
package when the export lacks it and assign the spec items it lacks, then per quote
file a new quote (vendor, header, one line per item), a revision of the changed one,
or nothing; then the choice (spec §1.3) and plug ops (Task 6), then a recalc.

The choice: a vendor in `selected` is carried pinned, `ARR` pinned is self-perform,
`ARR` unpinned leaves BidSheet.ai automatic (and returns a pinned package to automatic
only when the spec moved since the sidecar), any `picks` send the whole package by
hand allocation, `CARRY` has no BidSheet.ai form. Unpinned `picks` that give every item
ARR read as `ARR` unpinned: on an automatic package they push nothing (ruling 46). The
last choice op records `bm_choice` in the sidecar; `Plan.meta["bm_choice"]` holds the
snapshot each package is pushed to (`{"carry_mode", "selected_quote_id", "hand_items"}`)
and, for a package with ops but no choice op, BidSheet.ai's observed choice, which
`--apply` writes as the baseline (ruling 41). A push that changes a BidSheet.ai pin
with no conflict says so in a notice. A package whose choice is a conflict records
neither `spec_choice` nor `bm_choice`, so the conflict stands until it is settled.

Plug removal is offered only for the items a vendor carry covers: one this plan
plans, or one BidSheet.ai already has as the spec says; the items are those the
vendor's current quote includes as this plan leaves it (export lines replaced by the
plan's). Component names match spec line names by `_names.same_name`.

A file with no sidecar record whose quote BidSheet.ai already has, unchanged, is
adopted: `Plan.meta["adopt"][pkg][file]` holds its ids for `--apply` (ruling 44).
`Plan.meta["package_ids"][pkg]` holds the export's `work_package_id` / `estimate_package_id`
for every spec package BidSheet.ai already has, so `--apply` can record them for a package
that needs no ensure op (#421).

The unit-mismatch flag: `QuoteLine` has no unit field. The intake importer writes a
quoted unit that differs from the package line's as the line's `exclusion_notes` prefix
`unit <X> vs <Y>` (e.g. "unit TON vs LB"); such a line pushes `amount` only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from estimating_tools.estimate_spec._names import same_name
from estimating_tools.estimate_spec.bm_sync.export import BmExport, ExportPackage, ExportQuote
from estimating_tools.estimate_spec.bm_sync.ops import Entry, Op, Plan, next_id, reset_ids
from estimating_tools.estimate_spec.bm_sync.sidecar import (
    QuoteSync, Sidecar, choice_of, plug_entry, plug_key, plug_text)
from estimating_tools.estimate_spec.package_frames import (
    ARR, CARRY, PackageError, PackageFrame, build_package_frames, vendor_total)
from estimating_tools.quotes.model import CanonicalQuote, QuoteLine
from estimating_tools.quotes.plan import plan_quote
from estimating_tools.quotes.revision import diff_quote_lines

DERIVED_AMOUNT_NOTE = "amount derived from the quote's lines by the estimating plugin; the document states no total"

# Either unit may contain spaces ("unit 100 LB vs LB"); the prefix ends at "; " or the end.
_UNIT_MISMATCH = re.compile(r"^unit ([^;]+?) vs ([^;]+?)\s*(?:;|$)", re.IGNORECASE)
_LINE_KEYS = ("unit_price", "quantity", "amount")


def _fold(name) -> str:
    return str(name or "").strip().casefold()


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _ref(op: Op, path: str = "$.id") -> dict:
    return {"$ref": op.id, "path": path}


def _items_path(item_no: str, field: str) -> str:
    return f"$.items[?item_number=='{item_no}'].{field}"


def _line_path(item_no: str) -> str:
    return f"$.line_items[?item_number=='{item_no}'].id"


# ---------- lines ----------

def _target_qty(ql: QuoteLine, frame: PackageFrame) -> float | str | None:
    """The spec package line `ql` prices: its qty, or None when the item has several
    lines and `ql` names none. Raises ValueError for an item outside the package."""
    item_no = str(ql.item_number)
    cands = [ln for ln in frame.lines if ln.item_no == item_no]
    if not cands:
        raise ValueError(f"item '{item_no}' is not in package '{frame.name}'")
    if ql.line_name is not None:
        match = [ln for ln in cands if ln.name == ql.line_name]
        if not match:
            raise ValueError(f"item '{item_no}' has no package line '{ql.line_name}'")
        return match[0].qty
    return cands[0].qty if len(cands) == 1 else None


def _prepared_lines(q: CanonicalQuote, frame: PackageFrame) -> list[QuoteLine]:
    """The quote's lines as pushed: folded lines dropped, a missing quantity filled
    with the spec package line's qty, a unit-mismatched line reduced to its amount."""
    out = []
    for ql in q.lines:
        qty = _target_qty(ql, frame)
        if ql.folded_into:
            continue
        where = f"item '{ql.item_number}'"
        if _UNIT_MISMATCH.match(ql.exclusion_notes or ""):
            amount = ql.amount
            if amount is None and ql.unit_price is not None:
                if ql.quantity is None:
                    raise ValueError(f"{where} is priced in another unit with no quantity or amount")
                amount = round(ql.unit_price * ql.quantity, 2)
            out.append(replace(ql, unit_price=None, quantity=None, amount=amount))
        elif ql.unit_price is not None and ql.quantity is None:
            if qty is None:
                raise ValueError(f"{where} has several package lines; the quote line names none "
                                 "and states no quantity")
            if not _is_number(qty):
                raise ValueError(f"{where}: the quote line states no quantity and the spec package "
                                 f"line's qty is a formula ({qty}); state the quantity in the file")
            out.append(replace(ql, quantity=qty))
        else:
            out.append(ql)
    return out


def _extension(ql: QuoteLine) -> float:
    if ql.amount is not None:
        return ql.amount
    if ql.unit_price is not None and ql.quantity is not None:
        return ql.unit_price * ql.quantity
    return 0.0


def _in_base(ql: QuoteLine) -> bool:
    return ql.is_included and not ql.is_alternate and not ql.folded_into


def _frame_for(frames: list[PackageFrame], name: str) -> PackageFrame | None:
    return next((f for f in frames if _fold(f.name) == _fold(name)), None)


def quote_amount(q: CanonicalQuote, frames: list[PackageFrame]) -> tuple[float, bool]:
    """The header amount pushed and whether it is derived: the file's `amount`, else the
    sum of its included, non-alternate line extensions (derived)."""
    if q.amount is not None:
        return q.amount, False
    frame = _frame_for(frames, q.work_package_name)
    base = [ql for ql in _prepared_lines(q, frame) if _in_base(ql)]
    return round(sum(_extension(ql) for ql in base), 2), True


def line_payloads(q: CanonicalQuote, pkg_frame: PackageFrame,
                  export_pkg: ExportPackage | None) -> list[dict]:
    """One BidSheet.ai line per item, keyed `item_number`. `work_package_item_id` is
    None for an item the export's package lacks (the caller references the assign op)."""
    lines = _prepared_lines(q, pkg_frame)
    counts: dict[str, int] = {}
    for ql in lines:
        counts[str(ql.item_number)] = counts.get(str(ql.item_number), 0) + 1
    out = []
    for p in plan_quote(replace(q, lines=lines)).lines:
        item_no = str(p["item_number"])
        item = export_pkg.items.get(item_no) if export_pkg else None
        payload = {"item_number": item_no,
                   "work_package_item_id": item.work_package_item_id if item else None}
        for key in _LINE_KEYS:
            if key in p:
                payload[key] = p[key]
        if counts[item_no] > 1 and "amount" in payload:
            payload["amount"] = round(payload["amount"], 2)   # summed by _merge
        payload["is_included"] = p["is_included"]
        payload["is_alternate"] = bool(p.get("is_alternate"))
        if "exclusion_notes" in p:
            payload["exclusion_notes"] = p["exclusion_notes"]
        out.append(payload)
    return out


def _bm_value(payloads: list[dict], header_amount: float) -> float:
    """What BidSheet.ai values the quote at: its included lines, else its amount."""
    if not payloads:
        return header_amount
    total = 0.0
    for p in payloads:
        if p["is_included"] and not p["is_alternate"]:
            if p.get("amount") is not None:
                total += p["amount"]
            elif p.get("unit_price") is not None and p.get("quantity") is not None:
                total += p["unit_price"] * p["quantity"]
    return total


def _notes(q: CanonicalQuote, derived: bool) -> str | None:
    """The notes pushed: the derived-amount note, the file's notes, a `k: v` line per
    condition and the `ref X, dated D` line. A piece already a line of the file's notes
    is not added again (a file pull wrote copies BidSheet.ai's notes, which carry them)."""
    have = {ln.strip() for ln in (q.notes or "").splitlines()}
    ref = ", ".join(([f"ref {q.quote_ref}"] if q.quote_ref else [])
                    + ([f"dated {q.quote_date}"] if q.quote_date else []))
    pieces = [f"{k}: {v}" for k, v in (q.conditions or {}).items()] + ([ref] if ref else [])
    parts = [DERIVED_AMOUNT_NOTE] if derived and DERIVED_AMOUNT_NOTE not in have else []
    if q.notes:
        parts.append(q.notes)
    parts += [p for p in pieces if p not in have]
    return "\n".join(parts) or None


# ---------- planning ----------

def _priced(line: dict) -> bool:
    """A line that can be carried: included and not an alternate."""
    return line.get("is_included") is not False and not line.get("is_alternate")


@dataclass
class _VendorQuote:
    """A vendor's current quote as it stands after this plan's quote ops."""
    name: str
    quote_id: object                       # int, or a $ref to the op creating/revising it
    export_id: int | None                  # the export's quote id, None for a new quote
    op: Op | None                          # the op making it current in this plan
    lines: dict[str, tuple[object, Op | None]]   # item_no -> (line id or $ref, op making it)
    separate_acceptance_permitted: bool | None = None
    acceptance_notes: str | None = None
    last: Op | None = None                 # this plan's last op on the quote (a carry follows it)


class _Pkg:
    """One package's planning state: its ops, how to reference its ids, and each
    vendor's current quote (the export's, replaced by the one this plan creates)."""

    def __init__(self, name: str, export_pkg: ExportPackage | None):
        self.name = name
        self.export = export_pkg
        self.ops: list[Op] = []
        self.ensure: Op | None = None
        self.assign: Op | None = None
        self.vendors: dict[str, _VendorQuote] = {}
        for eq in export_pkg.quotes if export_pkg else []:
            self.vendors[_fold(eq.vendor_name)] = _VendorQuote(
                eq.vendor_name, eq.quote_id, eq.quote_id, None,
                {n: (ln["line_id"], None) for n, ln in eq.lines.items() if _priced(ln)},
                eq.separate_acceptance_permitted, eq.acceptance_notes)

    def add(self, kind: str, tool: str, args: dict, **kw) -> Op:
        op = Op(id=next_id("p"), kind=kind, tool=tool, args=args, package=self.name, **kw)
        self.ops.append(op)
        return op

    def work_package_id(self):
        return _ref(self.ensure) if self.ensure else self.export.work_package_id

    def item_id(self, payload: dict):
        if payload["work_package_item_id"] is not None:
            return payload["work_package_item_id"]
        return _ref(self.assign, _items_path(payload["item_number"], "work_package_item_id"))

    def key(self, file: str, field: str) -> str:
        return f"packages.{self.name}.quotes.{file}.{field}"


def _plan_package(st: _Pkg, spec_pkg: dict, project_id) -> None:
    """Create the package when the export lacks it; assign the spec items it lacks."""
    if st.export is None:
        st.ensure = st.add("ensure_package", "create_work_package",
                           {"project_id": project_id, "name": st.name},
                           sidecar={f"packages.{st.name}.work_package_id": "$.id",
                                    f"packages.{st.name}.estimate_package_id": "$.estimate_package_id"})
    have = st.export.items if st.export else {}
    missing = [str(n) for n in spec_pkg["items"] if str(n) not in have]
    if missing:
        st.assign = st.add("assign_items", "assign_items_to_package",
                           {"work_package_id": st.work_package_id(), "item_numbers": missing},
                           note=f"assign items {', '.join(missing)} (the skill maps item numbers "
                                "to project bid item ids)",
                           after=st.ensure.id if st.ensure else None)


def _vendor(st: _Pkg, q: CanonicalQuote, export: BmExport, vendors: dict):
    """The quote's vendor id, or a reference to the op that finds or creates it."""
    key = _fold(q.vendor_name)
    if key in vendors:
        return vendors[key]
    ids = export.organizations_by_name().get(key) or []
    name = q.vendor_name.strip()
    if len(ids) == 1:
        value = (ids[0], None)
    elif ids:
        op = st.add("resolve_vendor", "", {"vendor_name": name, "candidates": ids},
                    note=f"{name} matches organizations {', '.join(map(str, ids))}: ask which one")
        value = (_ref(op, "$.vendor_id"), op)
    else:
        op = st.add("create_vendor", "create_organization", {"name": name, "is_dbe": q.is_dbe})
        value = (_ref(op), op)
    vendors[key] = value
    return value


def _quote_note(vendor: str, amount: float, derived: bool, payloads: list[dict]) -> str:
    return f"{vendor}, amount {amount:,.2f}{', derived' if derived else ''}, {len(payloads)} line(s)"


def _create_quote(st: _Pkg, file: str, q: CanonicalQuote, payloads: list[dict],
                  amount: float, derived: bool, notes: str | None, export: BmExport, vendors: dict) -> None:
    vendor_id, vendor_op = _vendor(st, q, export, vendors)
    header = plan_quote(replace(q, lines=[])).quote_header
    args = {"work_package_id": st.work_package_id(), "vendor_name": q.vendor_name.strip(),
            "amount": amount, "vendor_id": vendor_id, "is_dbe": header["is_dbe"]}
    if notes:
        args["notes"] = notes
    if header.get("contact_info"):
        args["contact_info"] = header["contact_info"]
    after = vendor_op or st.assign or st.ensure
    cq = st.add("create_quote", "create_work_package_quote", args,
                note=_quote_note(q.vendor_name.strip(), amount, derived, payloads),
                sidecar={st.key(file, "quote_id"): "$.id", st.key(file, "revision"): "$.revision"},
                after=after.id if after else None)
    lines = {}
    for p in payloads:
        cl = _create_line(st, file, cq, p)
        if _priced(p):
            lines[p["item_number"]] = (_ref(cl), cl)
    st.vendors[_fold(q.vendor_name)] = _VendorQuote(q.vendor_name.strip(), _ref(cq), None, cq, lines,
                                                    last=st.ops[-1])


def _create_line(st: _Pkg, file: str, quote_op: Op, p: dict) -> Op:
    args = {"quote_id": _ref(quote_op), **{k: v for k, v in p.items() if k != "item_number"},
            "work_package_item_id": st.item_id(p)}
    return st.add("create_line", "create_work_package_quote_line_item", args,
                  sidecar={st.key(file, f"lines.{p['item_number']}"): "$.id"}, after=quote_op.id)


def _revise(st: _Pkg, file: str, eq: ExportQuote, payloads: list[dict],
            amount: float, derived: bool, notes: str | None) -> bool:
    """A revision carrying the changed, added and dropped lines and the header, or
    nothing when none changed (False). A line the file dropped is deleted from the
    revision (the revision copies every line); an exclusion note the file cleared is
    sent as ""."""
    planned = [{**p, "work_package_item_id": p["item_number"]} for p in payloads]
    existing = [{**ln, "work_package_item_id": n, "id": ln.get("line_id")} for n, ln in eq.lines.items()]
    diff = diff_quote_lines(planned, existing)
    header_changed = (eq.amount is None or float(eq.amount) != float(amount)) or (eq.notes or None) != notes
    dropped = sorted(set(eq.lines) - {p["item_number"] for p in payloads})
    if diff.unchanged and not header_changed and not dropped:
        return False
    sidecar = {st.key(file, "quote_id"): "$.id", st.key(file, "revision"): "$.revision"}
    sidecar.update({st.key(file, f"lines.{n}"): _line_path(n) for n in eq.lines
                    if n not in dropped})
    rev = st.add("create_revision", "create_quote_revision",
                 {"quote_id": eq.quote_id, "copy_line_items": True, "amount": amount, "notes": notes},
                 note=_quote_note(eq.vendor_name, amount, derived, payloads), sidecar=sidecar)
    for p in diff.changed:
        n = p["item_number"]
        fields = {k: p.get(k) for k in (*_LINE_KEYS, "is_included", "is_alternate", "exclusion_notes")}
        args = {"line_item_id": _ref(rev, _line_path(n)),
                **{k: v for k, v in fields.items() if v is not None}}
        if fields["exclusion_notes"] is None and (eq.lines.get(n) or {}).get("exclusion_notes"):
            args["exclusion_notes"] = ""
        st.add("update_line", "update_work_package_quote_line_item", args,
               sidecar={st.key(file, f"lines.{n}"): "$.id"}, after=rev.id)
    by_item = {p["item_number"]: p for p in payloads}
    added = {p["item_number"]: _create_line(st, file, rev, by_item[p["item_number"]])
             for p in diff.added}
    for n in dropped:
        st.add("delete_line", "delete_work_package_quote_line_item",
               {"line_item_id": _ref(rev, _line_path(n))},
               note=f"line {n} not in the quote file", after=rev.id)
    lines = {n: ((_ref(added[n]), added[n]) if n in added else (_ref(rev, _line_path(n)), rev))
             for n, p in by_item.items() if _priced(p)}
    st.vendors[_fold(eq.vendor_name)] = _VendorQuote(
        eq.vendor_name, _ref(rev), eq.quote_id, rev, lines,
        eq.separate_acceptance_permitted, eq.acceptance_notes, last=st.ops[-1])
    return True


def _current_quote(export_pkg: ExportPackage | None, sync: QuoteSync | None,
                   vendor: str) -> ExportQuote | None:
    """The export's current quote for this file: by the synced id, else by vendor name."""
    if export_pkg is None:
        return None
    quotes = export_pkg.quotes
    if sync is not None:
        found = next((eq for eq in quotes if eq.quote_id == sync.quote_id), None)
        if found:
            return found
    return next((eq for eq in quotes if _fold(eq.vendor_name) == _fold(vendor)), None)


def _unselected(spec: dict) -> dict:
    """The spec with every package's `selected` and `picks` dropped: the frames the
    quote ops need do not depend on the choice, which may name a vendor whose quote
    file is not loaded (the choice is resolved against the export instead)."""
    pkgs = [{k: v for k, v in p.items() if k not in ("selected", "picks")}
            for p in spec.get("work_packages") or []]
    return {**spec, "work_packages": pkgs}


def _reconcile(spec: dict, q: CanonicalQuote, frame: PackageFrame, bm_value: float) -> str:
    vendor = q.vendor_name.strip()
    try:
        frames = build_package_frames(_unselected(spec), [q], spare_columns=0)
    except PackageError as err:
        return (f"{vendor}: BidSheet.ai value {bm_value:,.2f}; {frame.title} carried subtotal "
                f"not available ({err})")
    wb = vendor_total(_frame_for(frames, frame.name), vendor)
    sign = "=" if abs(wb - bm_value) < 0.005 else "≠"
    return f"{vendor}: BidSheet.ai value {bm_value:,.2f} {sign} {frame.title} carried subtotal {wb:,.2f}"


def _plan_quote_file(st: _Pkg, entries: list[Entry], spec: dict, frame: PackageFrame,
                     file: str, q: CanonicalQuote, sha: str, sync: QuoteSync | None,
                     export: BmExport, vendors: dict, force: str | None, adopt: dict) -> None:
    """A new quote, a revision, a conflict, an adoption or nothing for one quote file.
    An unsynced file equal to BidSheet.ai's quote of its vendor goes into `adopt`."""
    try:
        payloads = line_payloads(q, frame, st.export)
        amount, derived = quote_amount(q, [frame])
    except ValueError as err:
        entries.append(Entry("refused", st.name, f"{file}: {err}"))
        return
    notes = _notes(q, derived)
    entries.append(Entry("reconcile", st.name, _reconcile(spec, q, frame, _bm_value(payloads, amount))))
    eq = _current_quote(st.export, sync, q.vendor_name)
    if eq is None:
        if sync is not None:
            entries.append(Entry("notice", st.name, f"{file}: BidSheet.ai no longer has quote "
                                                    f"{sync.quote_id}; pushed as a new quote"))
        _create_quote(st, file, q, payloads, amount, derived, notes, export, vendors)
        return
    if sync is not None:
        file_moved = sha != sync.file_sha
        bm_moved = (eq.quote_id, eq.revision) != (sync.quote_id, sync.revision)
        if not file_moved:
            if bm_moved:
                entries.append(Entry("notice", st.name, f"{file}: unchanged; BidSheet.ai is at revision "
                                                        f"{eq.revision} (synced {sync.revision}); pull to take it"))
            return
        if bm_moved and force != "spec":
            entries.append(Entry("conflict", st.name, f"{file}: the file changed since the last push and "
                                                      f"BidSheet.ai moved from revision {sync.revision} to "
                                                      f"revision {eq.revision}; not pushed (force spec pushes it)"))
            return
    planned = _revise(st, file, eq, payloads, amount, derived, notes)
    if sync is None and planned:
        entries.append(Entry("notice", st.name, f"{file}: no sidecar record; matched BidSheet.ai "
                                                f"quote {eq.quote_id} (revision {eq.revision}) by vendor name"))
    elif sync is None:
        adopt.setdefault(st.name, {})[file] = {
            "quote_id": eq.quote_id, "revision": eq.revision, "vendor_id": eq.vendor_id,
            "lines": {n: ln["line_id"] for n, ln in eq.lines.items() if ln.get("line_id") is not None}}
        entries.append(Entry("notice", st.name, f"{file}: adopted BidSheet.ai quote {eq.quote_id} "
                                                f"rev {eq.revision}"))


# ---------- choice ----------

def _source(value) -> str:
    """A selector value as the frames read it: ARR, CARRY or the vendor name."""
    folded = _fold(value)
    for fixed in (ARR, CARRY):
        if folded == fixed.casefold():
            return fixed
    return str(value).strip()


def _bm_state(export_pkg: ExportPackage | None) -> dict:
    """BidSheet.ai's choice in the sidecar's `bm_choice` shape."""
    if export_pkg is None:
        return {"carry_mode": "automatic", "selected_quote_id": None, "hand_items": []}
    sq = export_pkg.selected_quote
    hand: list[str] = []
    if sq is None:
        item_of = {ln["line_id"]: n for eq in export_pkg.quotes for n, ln in eq.lines.items()}
        hand = sorted({item_of[a["quote_line_item_id"]] for a in export_pkg.allocations
                       if a["quote_line_item_id"] in item_of})
    return {"carry_mode": export_pkg.carry_mode,
            "selected_quote_id": sq.get("id") if sq else None, "hand_items": hand}


def _bm_moved(current: dict, baseline: dict) -> bool:
    """Whether BidSheet.ai's choice moved from the baseline. An automatic package whose
    automatic carry was re-evaluated (a quote write) has not: nobody chose."""
    if current["carry_mode"] == baseline.get("carry_mode") == "automatic":
        return False
    return current != baseline


def _observed(st: "_Pkg") -> dict:
    """BidSheet.ai's choice as this plan leaves it with no choice op: the export's, with
    a carried quote this plan revises referenced through the revising op (the revision
    takes the carry)."""
    snap = _bm_state(st.export)
    sq = snap["selected_quote_id"]
    if sq is not None:
        vq = next((v for v in st.vendors.values() if v.export_id == sq), None)
        if vq is not None:
            snap["selected_quote_id"] = vq.quote_id
    return snap


def choice_text(choice: dict) -> str:
    """A spec choice as the conflict texts show it: its picks, else its `selected`."""
    if choice["picks"]:
        return "picks " + ", ".join(f"{n} {v}" for n, v in choice["picks"].items())
    return choice["selected"]


def bm_side(export_pkg: ExportPackage | None, bm: dict) -> str:
    """BidSheet.ai's choice as the conflict texts show it, with its carry mode."""
    sq = export_pkg.selected_quote if export_pkg else None
    if sq:
        side = sq.get("vendor_name") or f"quote {sq.get('id')}"
    elif bm["carry_mode"] != "pinned":
        side = "no quote"
    elif bm["hand_items"]:
        side = f"hand allocations on items {', '.join(bm['hand_items'])}"
    else:
        side = "self-perform"
    return f"{side} ({bm['carry_mode']})"


def _conflict_text(name: str, choice: dict, export_pkg: ExportPackage | None, bm: dict) -> str:
    return (f"{name}: spec: {choice_text(choice)} · BidSheet.ai: {bm_side(export_pkg, bm)}; "
            "both changed since the last sync; no choice pushed (force spec pushes the spec's)")


def _carry(st: _Pkg, quote_id, pin: bool, note: str, after: Op | None) -> Op:
    after = after or st.ensure
    return st.add("carry", "carry_work_package_quote",
                  {"work_package_id": st.work_package_id(), "quote_id": quote_id, "pin": pin},
                  note=note, after=after.id if after else None)


def _plan_hand(st: _Pkg, entries: list[Entry],
               frame: PackageFrame) -> tuple[list[Op], dict, dict[str, str]] | None:
    """Picks: an allocation per item a vendor carries, every other allocation removed.
    When BidSheet.ai carries a quote, a self-perform pin clears the carry and all its
    allocations first, then every pick is allocated. Returns the ops, the target
    snapshot and item -> vendor of the allocated items; None when refused."""
    want: dict[str, tuple[object, Op | None, str]] = {}
    carried: dict[str, set[str]] = {}
    for n in frame.items:
        src = frame.effective_source(n)
        if src == ARR:
            continue
        if src == CARRY:
            entries.append(Entry("notice", st.name, f"{st.name}: item {n}: CARRY has no BidSheet.ai "
                                                    "form; no allocation"))
            continue
        vq = st.vendors.get(_fold(src))
        if vq is None:
            entries.append(Entry("refused", st.name, f"{st.name}: pick '{src}' for item {n} has no "
                                                     "quote in BidSheet.ai or this push"))
            return None
        if n not in vq.lines:
            entries.append(Entry("refused", st.name, f"{st.name}: {vq.name} has no included line "
                                                     f"for item {n}"))
            return None
        want[n] = (*vq.lines[n], vq.name)
        carried.setdefault(_fold(src), set()).add(n)
    for fold, items in carried.items():
        vq = st.vendors[fold]
        if vq.separate_acceptance_permitted is False and items < set(vq.lines):
            text = f"{st.name}: {vq.name} does not permit separate acceptance"
            entries.append(Entry("refused", st.name,
                                 text + (f": {vq.acceptance_notes}" if vq.acceptance_notes else "")))
            return None
    wanted = {ref for ref, _op, _v in want.values() if not isinstance(ref, dict)}
    kept: set = set()
    ops = []
    carried_now = st.export is not None and st.export.selected_quote is not None
    if carried_now:
        ops.append(_carry(st, 0, True, "clear the carried quote and its allocations "
                                       "(the picks go by hand)", None))
    for a in st.export.allocations if st.export and not carried_now else []:
        lid = a["quote_line_item_id"]
        if lid in wanted and lid not in kept and a.get("allocation_type") == "full" \
                and not a.get("accept_alternate"):
            kept.add(lid)
            continue
        ops.append(st.add("remove_allocation", "remove_subcontractor_allocation",
                          {"allocation_id": a["allocation_id"]},
                          note=f"remove allocation {a['allocation_id']} (quote {a['quote_id']}, "
                               f"line {lid})"))
    for n, (ref, op, vendor) in want.items():
        if not isinstance(ref, dict) and ref in kept:
            continue
        ops.append(st.add("allocate", "allocate_subcontractor",
                          {"quote_line_item_id": ref, "allocation_type": "full"},
                          note=f"item {n}: {vendor} (full allocation)", after=op.id if op else None))
    return (ops, {"carry_mode": "pinned", "selected_quote_id": None, "hand_items": sorted(want)},
            {n: vendor for n, (_ref_, _op, vendor) in want.items()})


@dataclass
class _Choice:
    """What `_plan_choice` decided: the `bm_choice` snapshot pushed (None with no choice
    op), the items a vendor carry covers (item -> vendor), and whether it is a conflict."""
    target: dict | None = None
    carried: dict[str, str] | None = None
    conflict: bool = False


def _plan_choice(st: _Pkg, entries: list[Entry], frame: PackageFrame, spec_pkg: dict,
                 sidecar: Sidecar, force: str | None) -> _Choice:
    """The package's choice ops (spec §1.3), added to `st`. `carried` is set only when
    this plan carries a vendor or BidSheet.ai already carries it as the spec says, and
    holds the items the vendor's current quote includes (as this plan leaves it)."""
    choice = choice_of(spec_pkg)
    frame = replace(frame, selected=_source(choice["selected"]),
                    picks={str(n): _source(v) for n, v in choice["picks"].items()})
    if frame.picks and not choice["pinned"] and all(frame.effective_source(n) == ARR for n in frame.items):
        frame = replace(frame, selected=ARR, picks={})       # all-ARR picks: ARR unpinned (ruling 46)
    current = _bm_state(st.export)
    synced = sidecar.packages.get(st.name)
    if (synced and synced.spec_choice is not None and synced.bm_choice is not None
            and choice != synced.spec_choice and _bm_moved(current, synced.bm_choice) and force != "spec"):
        entries.append(Entry("conflict", st.name, _conflict_text(st.name, choice, st.export, current)))
        return _Choice(conflict=True)
    pinned = current["carry_mode"] == "pinned"
    sq = st.export.selected_quote if st.export else None
    carried = None
    if frame.picks:
        planned = _plan_hand(st, entries, frame)
        if planned is None:
            return _Choice()
        ops, target, carried = planned
        same = not ops and pinned and sq is None
    elif frame.selected == CARRY:
        entries.append(Entry("notice", st.name, f"{st.name}: CARRY has no BidSheet.ai form; "
                                                "the choice is not pushed"))
        return _Choice()
    elif frame.selected == ARR and not choice["pinned"]:
        moved = synced is not None and synced.spec_choice is not None and synced.spec_choice != choice
        if not (pinned and moved):
            return _Choice()
        ops = [_carry(st, 0, False, "return to automatic (BidSheet.ai carries its lowest quote)", None)]
        target, same = {"carry_mode": "automatic", "selected_quote_id": None, "hand_items": []}, False
    elif frame.selected == ARR:
        target = {"carry_mode": "pinned", "selected_quote_id": None, "hand_items": []}
        same = pinned and sq is None and not current["hand_items"]
        ops = [] if same else [_carry(st, 0, True, "self-perform (pinned)", None)]
    else:
        vq = st.vendors.get(_fold(frame.selected))
        if vq is None:
            entries.append(Entry("refused", st.name, f"{st.name}: selected '{frame.selected}' has no "
                                                     "quote in BidSheet.ai or this push"))
            return _Choice()
        target = {"carry_mode": "pinned", "selected_quote_id": vq.quote_id, "hand_items": []}
        same = pinned and sq is not None and vq.export_id is not None and sq.get("id") == vq.export_id
        ops = [] if same else [_carry(st, vq.quote_id, True, f"carry {vq.name} (pinned)", vq.last)]
        carried = {n: vq.name for n in frame.items if n in vq.lines}
    if same and st.export.new_quotes_since_carry:
        ops.append(st.add("acknowledge", "acknowledge_work_package_quotes",
                          {"work_package_id": st.export.work_package_id},
                          note="acknowledge the new quotes: the spec re-affirms the pin"))
    if not ops:
        return _Choice(carried=carried)
    if pinned and not same and target != current:     # a revised quote's $ref is not a move (#427)
        entries.append(Entry("notice", st.name, f"{st.name}: overrides BidSheet.ai's pin on "
                                                f"{bm_side(st.export, current)}"))
    ops[-1].sidecar = {f"packages.{st.name}.bm_choice": "$"}
    ops[-1].note += "; records bm_choice"
    return _Choice(target, carried)


_PREFIX = re.compile(r"^\d{2} ")


def _removed_vendor(synced) -> str:
    """The vendor a package's removed plugs were removed for, from its recorded spec choice."""
    choice = (synced.spec_choice if synced else None) or {}
    selected = _source(choice.get("selected") or ARR)
    if selected not in (ARR, CARRY):
        return selected
    picked = sorted({_source(v) for v in (choice.get("picks") or {}).values()} - {ARR, CARRY})
    return ", ".join(picked) or "a vendor"


def _plug_value(ln) -> str:
    """`qty × price = value`, or the raw qty when it is a formula (nothing is multiplied)."""
    if _is_number(ln.qty) and _is_number(ln.plug_price):
        return f"{ln.qty:g} × {ln.plug_price:,.2f} = {ln.qty * ln.plug_price:,.2f}"
    price = f"{ln.plug_price:,.2f}" if _is_number(ln.plug_price) else str(ln.plug_price)
    return f"{ln.qty} × {price}"


def _plan_plug_removal(st: _Pkg, entries: list[Entry], spec_pkg: dict, frame: PackageFrame,
                       sidecar: Sidecar, carried: dict[str, str] | None) -> dict[str, list[dict]]:
    """The plug-component removal ops offered when a vendor is carried (spec §1.3): for each
    item of `carried` (the vendor carry in effect after this plan, from `_plan_choice`), the
    BidSheet.ai components named like the package's spec lines on that item. The estimator
    confirms each. With no carry nothing is offered; when the spec carries no vendor at all,
    plugs removed earlier are reported.

    Returns the stale `plugs_removed` records per item (#428): when the export names the
    assemblies an item has now, a record whose assembly is not among them was orphaned by a
    push-assemblies re-push. Stale records are not counted as removed, are reported, and
    `--apply` prunes them from `Plan.meta["stale_plugs"]`."""
    synced = sidecar.packages.get(st.name)
    recorded = {n: [plug_entry(e) for e in es]
                for n, es in (synced.plugs_removed if synced else {}).items()}
    current = st.export.assemblies if st.export else {}
    stale = {n: [e for e in es if n in current and e["assembly_id"] not in current[n]]
             for n, es in recorded.items()}
    stale = {n: es for n, es in stale.items() if es}
    live = {n: [e for e in es if e not in stale.get(n, [])] for n, es in recorded.items()}
    live = {n: es for n, es in live.items() if es}
    done = {n: {plug_key(e) for e in es} for n, es in live.items()}
    ops: list[Op] = []
    for item_no in sorted(carried or {}, key=lambda n: (len(n), n)):
        lines = [ln for ln in frame.lines if ln.item_no == item_no]
        for comp in (st.export.components.get(item_no, []) if st.export else []):
            name = _PREFIX.sub("", comp["name"], count=1)
            ln = next((ln for ln in lines if same_name(ln.name, name)), None)
            entry = plug_entry({"assembly_id": comp["assembly_id"], "component_id": comp["component_id"],
                                "name": comp["name"]})
            if ln is None or plug_key(entry) in done.get(item_no, set()):
                continue
            ops.append(st.add(
                "remove_plug", "delete_component", {"component_id": comp["component_id"]},
                note=f"item {item_no} · {comp['name']} · {_plug_value(ln)} · package {st.name}",
                sidecar={f"packages.{st.name}.plugs_removed.{item_no}": entry}))
    choice = choice_of(spec_pkg)
    picks = {str(n): _source(v) for n, v in choice["picks"].items()}
    spec_carries = any(picks.get(n, _source(choice["selected"])) not in (ARR, CARRY) for n in frame.items)
    if not spec_carries and live:
        count = sum(len(es) for es in live.values())
        entries.append(Entry("notice", st.name,
                             f"{st.name}: {count} plug component(s) were removed on item "
                             f"{', '.join(live)} when {_removed_vendor(synced)} was carried; "
                             "push-assemblies restores them"))
    for item_no, es in stale.items():
        entries.append(Entry("notice", st.name,
                             f"{st.name}: {len(es)} stale plug record(s) on item {item_no} "
                             f"({', '.join(plug_text(e) for e in es)}): the assembly was replaced "
                             "by a re-push; --apply prunes them"))
    return stale
    return ops


def plan_push(spec: dict, quotes: list[tuple[str, CanonicalQuote, str]], export: BmExport,
              sidecar: Sidecar, *, spec_name: str, force: str | None = None, now: str) -> Plan:
    """The push plan. `quotes` holds (file name, loaded quote, sha256 of the file's bytes);
    `now` is the timestamp the sidecar will stamp on `--apply`."""
    reset_ids()
    spec_pkgs = spec.get("work_packages") or []
    frames = build_package_frames(_unselected(spec), [], spare_columns=0)
    known = {_fold(p["name"]) for p in spec_pkgs}
    ops: list[Op] = []
    entries: list[Entry] = []
    for file, q, _sha in quotes:
        if _fold(q.work_package_name) not in known:
            entries.append(Entry("refused", q.work_package_name,
                                 f"{file}: package '{q.work_package_name}' is not in the spec's work_packages"))
    vendors: dict = {}
    bm_choice: dict = {}
    adopt: dict = {}
    stale_plugs: dict = {}
    conflicts: set[str] = set()
    for spec_pkg, frame in zip(spec_pkgs, frames):
        name = spec_pkg["name"]
        st = _Pkg(name, export.package(name))
        _plan_package(st, spec_pkg, export.project_id)
        synced = sidecar.packages.get(name)
        for file, q, sha in quotes:
            if _fold(q.work_package_name) == _fold(name):
                sync = synced.quotes.get(file) if synced else None
                _plan_quote_file(st, entries, spec, frame, file, q, sha, sync, export, vendors, force, adopt)
        chosen = _plan_choice(st, entries, frame, spec_pkg, sidecar, force)
        if chosen.conflict:
            conflicts.add(name)
        elif chosen.target is not None:
            bm_choice[name] = chosen.target
        stale = _plan_plug_removal(st, entries, spec_pkg, frame, sidecar, chosen.carried)
        if stale:
            stale_plugs[name] = stale
        if st.ops:
            if not chosen.conflict and name not in bm_choice:
                bm_choice[name] = _observed(st)       # the baseline apply records (ruling 41)
            epid = _ref(st.ensure, "$.estimate_package_id") if st.ensure else st.export.estimate_package_id
            if epid is None:
                entries.append(Entry("notice", name, f"{name}: the export has no estimate package id; "
                                                     "recalculate_estimate_package_totals not planned"))
            else:
                st.add("recalc", "recalculate_estimate_package_totals", {"package_id": epid})
        ops += st.ops
    meta = {"project_id": export.project_id, "estimate_id": export.estimate_id,
            "spec_choice": {p["name"]: choice_of(p) for p in spec_pkgs if p["name"] not in conflicts},
            "file_sha": {file: sha for file, _q, sha in quotes}}
    meta["package_ids"] = {p["name"]: {"work_package_id": ep.work_package_id,
                                       "estimate_package_id": ep.estimate_package_id}
                           for p in spec_pkgs if (ep := export.package(p["name"])) is not None}
    if bm_choice:
        meta["bm_choice"] = bm_choice
    if adopt:
        meta["adopt"] = adopt
    if stale_plugs:
        meta["stale_plugs"] = stale_plugs
    return Plan("push", spec_name, ops, entries, meta=meta)
