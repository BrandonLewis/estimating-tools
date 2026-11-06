"""The pull planner: BidSheet.ai's current quotes as quote files (spec §1.4).

`plan_pull` is pure: per spec package (``work_packages`` order) it matches each current
BidSheet.ai quote to a quote file -- by the sidecar's quote id, else by vendor name or
file name -- and plans a new file, a rewrite of the file (BidSheet.ai moved past the
synced revision), a conflict (the file moved too; ``force="bm"`` rewrites it) or
nothing. A synced quote BidSheet.ai no longer has is a notice; the file stays.

BidSheet.ai prices an item as one line. A file line is written per spec package line
of the item: the first carries the price, the others are `folded_into` it, and the
quote's notes ask for a review when the item has several package lines. A new file
takes BidSheet.ai's notes; a rewrite keeps the file's notes, conditions, quote_ref,
quote_date, surcharge, is_dbe and contact_info (the export carries none of them).
An amount the push derived (BidSheet.ai's notes carry `DERIVED_AMOUNT_NOTE`) is never
written into a file: its `amount` is None, and a new file's notes drop that line (ruling 42).

The choice: an automatic carry is a notice only (the workbook keeps its own choice). A
pinned carry -- a quote, self-perform or hand allocations -- becomes the package's
`selected`/`pinned`/`picks` unless the spec already gives every item the same source;
a `write_spec` op records it and the sidecar's `spec_choice`/`bm_choice` are set so the
next push sees no movement. When both sides moved since the last sync it is a conflict
(``force="bm"`` writes BidSheet.ai's); when BidSheet.ai did not move nothing is pulled.

`write_pull` writes what the plan holds: a `.bak-<YYYYMMDD-HHMMSS>` copy of each file it
rewrites, the files, the spec (round trip, only when `spec_changes` is set) and the
sidecar (`sidecar_updates`, in the sidecar path grammar of `apply.py`). A new file's
`file_sha` is planned as None and filled with the sha of the bytes written.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from estimating_tools.estimate_spec.bm_sync.apply import parse_sidecar_path
from estimating_tools.estimate_spec.bm_sync.export import BmExport, ExportPackage, ExportQuote
from estimating_tools.estimate_spec.bm_sync.ops import Entry, Op, Plan, next_id, reset_ids
from estimating_tools.estimate_spec.bm_sync.plan_push import (DERIVED_AMOUNT_NOTE, _bm_state, _source,
                                                              _unselected, bm_side, choice_text)
from estimating_tools.estimate_spec.bm_sync.sidecar import QuoteSync, Sidecar, choice_of, file_sha
from estimating_tools.estimate_spec.package_frames import ARR, PackageFrame, build_package_frames
from estimating_tools.estimate_spec.readback.spec_io import SpecYaml
from estimating_tools.quotes.files import quote_file_slug, write_quote_file
from estimating_tools.quotes.model import CanonicalQuote, QuoteLine

_PRICE_KEYS = ("unit_price", "quantity", "amount", "exclusion_notes")


def _fold(name) -> str:
    return str(name or "").strip().casefold()


@dataclass
class PullPlan(Plan):
    files: dict[str, CanonicalQuote] = field(default_factory=dict)   # file name -> content
    backups: list[str] = field(default_factory=list)                  # files rewritten
    spec_changes: dict[str, dict] = field(default_factory=dict)       # package -> selected/pinned/picks
    sidecar_updates: list[tuple[str, object]] = field(default_factory=list)   # (sidecar path, value)
    now: str = ""


def _review_note(item_no: str) -> str:
    return f"review: BidSheet.ai prices item {item_no} as one line; split by hand if the vendor's document does"


def _file_quote(eq: ExportQuote, pkg_name: str, frame: PackageFrame, export_pkg: ExportPackage,
                existing: CanonicalQuote | None = None) -> tuple[CanonicalQuote | None, list[str]]:
    """The quote file for `eq`, or None and why it cannot be written; and notices.
    A rewrite of `existing` keeps its notes, conditions, quote_ref, quote_date,
    surcharge, is_dbe and contact_info; vendor, header amount and lines come from
    BidSheet.ai."""
    lines, reviews, notices = [], [], []
    by_item: dict[str, list] = {}
    for ln in frame.lines:
        by_item.setdefault(ln.item_no, []).append(ln)
    for item_no, line in eq.lines.items():
        if item_no not in by_item:
            notices.append(f"item {item_no} is not in the spec package; left out")
            continue
        item = export_pkg.items.get(item_no)
        schedule = item.schedule_name if item else None
        if not schedule:
            return None, [f"item {item_no} has no schedule name in the export"]
        price = {k: line.get(k) for k in _PRICE_KEYS}
        included = line.get("is_included") is not False
        if price["unit_price"] is None and price["amount"] is None and included:
            return None, [f"item {item_no} has no price"]
        first, *rest = by_item[item_no]
        lines.append(QuoteLine(schedule_name=schedule, item_number=item_no, line_name=first.name,
                               is_included=included, is_alternate=bool(line.get("is_alternate")),
                               **price))
        lines += [QuoteLine(schedule_name=schedule, item_number=item_no, line_name=ln.name,
                            folded_into=first.name) for ln in rest]
        if rest:
            reviews.append(_review_note(item_no))
    order = {ln.item_no: i for i, ln in reversed(list(enumerate(frame.lines)))}
    lines.sort(key=lambda ql: order[ql.item_number])     # spec order (stable within an item)
    derived = DERIVED_AMOUNT_NOTE in (eq.notes or "")
    if existing is not None:
        base = existing.notes
    else:
        base = "\n".join(ln for ln in (eq.notes or "").splitlines() if ln.strip() != DERIVED_AMOUNT_NOTE) or None
    notes = "\n".join(([base] if base else []) + [r for r in reviews if r not in (base or "")]) or None
    kept = {} if existing is None else {
        "conditions": dict(existing.conditions), "quote_ref": existing.quote_ref,
        "quote_date": existing.quote_date, "surcharge": existing.surcharge,
        "is_dbe": existing.is_dbe, "contact_info": existing.contact_info}
    return CanonicalQuote(vendor_name=eq.vendor_name, work_package_name=pkg_name,
                          amount=None if derived else eq.amount,
                          vendor_id=eq.vendor_id, notes=notes, lines=lines, **kept), notices


def _hand_choice(plan: PullPlan, name: str, items: list[str], export_pkg: ExportPackage) -> dict:
    """A pinned package's hand allocations as a spec choice: one vendor taking every item
    its current quote includes is `selected`; anything else is ARR with `picks`."""
    line_of = {ln.get("line_id"): (eq, n) for eq in export_pkg.quotes for n, ln in eq.lines.items()}
    picks: dict[str, str] = {}
    quote_of: dict[str, ExportQuote] = {}
    for a in export_pkg.allocations:
        hit = line_of.get(a["quote_line_item_id"])
        if hit is None:
            plan.entries.append(Entry("notice", name, f"{name}: allocation {a['allocation_id']} points at a "
                                                      "superseded quote line; nothing written for it"))
            continue
        eq, n = hit
        if a.get("accept_alternate"):
            plan.entries.append(Entry("notice", name, f"{name}: an alternate allocation on item {n} has no "
                                                      "spec form; nothing written"))
            continue
        if n not in items:
            plan.entries.append(Entry("notice", name, f"{name}: allocation {a['allocation_id']} is on item "
                                                      f"{n}, not in the spec package; nothing written for it"))
            continue
        picks[n] = eq.vendor_name
        quote_of[eq.vendor_name] = eq
    if len(quote_of) == 1 and set(picks) == set(items):
        (vendor, eq), = quote_of.items()
        if set(items) == {n for n, ln in eq.lines.items() if ln.get("is_included") is not False}:
            return {"selected": vendor, "pinned": True, "picks": {}}
    return {"selected": ARR, "pinned": True, "picks": {n: picks[n] for n in items if n in picks}}


def _sources(choice: dict, items: list[str]) -> dict[str, str]:
    """Each item's effective source under a spec choice, as the frames read it."""
    return {n: _source(choice["picks"].get(n, choice["selected"])) for n in items}


def _pull_choice(plan: PullPlan, spec_pkg: dict, export_pkg: ExportPackage, sidecar: Sidecar,
                 force: str | None) -> None:
    """BidSheet.ai's choice into `plan.spec_changes` (spec §1.4). An automatic carry is
    reported, never written; a pinned one becomes the spec's choice unless the spec
    already yields the same source per item. When both sides moved since the last
    sync it is a conflict (``force="bm"`` writes BidSheet.ai's); when BidSheet.ai did
    not move, nothing is pulled."""
    name = spec_pkg["name"]
    sq = export_pkg.selected_quote
    spec_choice = choice_of(spec_pkg)
    if export_pkg.carry_mode != "pinned":
        if sq:
            value = sq.get("value")
            lowest = "lowest" if value is None else f"lowest, ${float(value):,.2f}"
            plan.entries.append(Entry("notice", name, f"{name}: BidSheet.ai carries {sq.get('vendor_name')} "
                                                      f"automatically ({lowest}); the workbook carries "
                                                      f"{spec_choice['selected']}"))
        return
    items = [str(n) for n in spec_pkg.get("items") or []]
    bm = _bm_state(export_pkg)
    synced = sidecar.packages.get(name)
    if synced is not None and synced.bm_choice is not None and bm == synced.bm_choice:
        return
    if sq:
        vendor = sq.get("vendor_name") or next(
            (eq.vendor_name for eq in export_pkg.quotes if eq.quote_id == sq.get("id")), None)
        if not vendor:
            plan.entries.append(Entry("notice", name, f"{name}: carried quote {sq.get('id')} has no vendor "
                                                      "name; nothing written"))
            return
        target = {"selected": vendor, "pinned": True, "picks": {}}
    elif export_pkg.allocations:
        target = _hand_choice(plan, name, items, export_pkg)
    else:
        target = {"selected": ARR, "pinned": True, "picks": {}}
    if spec_choice["pinned"] and _sources(spec_choice, items) == _sources(target, items):
        # the spec already says it: only a stale baseline is refreshed, so a push sees no movement
        if synced is None or synced.spec_choice != spec_choice:
            plan.sidecar_updates.append((f"packages.{name}.spec_choice", spec_choice))
        if synced is None or synced.bm_choice != bm:
            plan.sidecar_updates.append((f"packages.{name}.bm_choice", bm))
        return
    if (synced is not None and synced.spec_choice is not None and synced.bm_choice is not None
            and spec_choice != synced.spec_choice and force != "bm"):
        plan.entries.append(Entry("conflict", name, f"{name}: spec: {choice_text(spec_choice)} · BidSheet.ai: "
                                                    f"{bm_side(export_pkg, bm)}; both changed since the last "
                                                    "sync; no choice pulled (force bm pulls BidSheet.ai's)"))
        return
    plan.spec_changes[name] = target
    plan.ops.append(Op(next_id("u"), "write_spec", "", {"package": name, **target}, name,
                       note=f"spec: {name} carries {choice_text(target)} (pinned), from BidSheet.ai"))
    plan.sidecar_updates += [(f"packages.{name}.spec_choice", target), (f"packages.{name}.bm_choice", bm)]


def plan_pull(spec: dict, quotes: list[tuple[str, CanonicalQuote, str]], export: BmExport,
              sidecar: Sidecar, *, spec_name: str, force: str | None = None, now: str) -> PullPlan:
    """The pull plan. `quotes` holds (file name, loaded quote, sha256 of the file's bytes)."""
    reset_ids()
    spec_pkgs = spec.get("work_packages") or []
    frames = build_package_frames(_unselected(spec), [], spare_columns=0)
    plan = PullPlan("pull", spec_name, [], [], meta={"project_id": export.project_id,
                                                     "estimate_id": export.estimate_id}, now=now)
    for spec_pkg, frame in zip(spec_pkgs, frames):
        name = spec_pkg["name"]
        export_pkg = export.package(name)
        if export_pkg is None:
            continue
        synced = sidecar.packages.get(name)
        synced_quotes = synced.quotes if synced else {}
        local = {f: (q, sha) for f, q, sha in quotes if _fold(q.work_package_name) == _fold(name)}
        current_ids = {eq.quote_id for eq in export_pkg.quotes}
        for file, sync in synced_quotes.items():
            if sync.quote_id not in current_ids:
                plan.entries.append(Entry("notice", name, f"{file}: BidSheet.ai quote {sync.quote_id} "
                                                          "no longer exists; the file stays"))
        n_ops = len(plan.ops)
        for eq in export_pkg.quotes:
            _plan_quote(plan, name, frame, export_pkg, eq, synced_quotes, local, force)
        _pull_choice(plan, spec_pkg, export_pkg, sidecar, force)
        if len(plan.ops) > n_ops:
            plan.sidecar_updates.append((f"packages.{name}.synced_at", now))
    return plan


def _plan_quote(plan: PullPlan, name: str, frame: PackageFrame, export_pkg: ExportPackage,
                eq: ExportQuote, synced_quotes: dict[str, QuoteSync], local: dict, force: str | None) -> None:
    """A new file, a rewrite, a conflict or nothing for one BidSheet.ai quote."""
    file = next((f for f, s in synced_quotes.items() if s.quote_id == eq.quote_id), None)
    sync = synced_quotes.get(file) if file else None
    if file is None:
        slug = quote_file_slug(eq.vendor_name, name)
        file = next((f for f, (q, _sha) in local.items()
                     if f == slug or _fold(q.vendor_name) == _fold(eq.vendor_name)), slug)
    on_disk = file in local
    if sync is not None:
        if (eq.quote_id, eq.revision) == (sync.quote_id, sync.revision):
            return
        if on_disk and local[file][1] != sync.file_sha and force != "bm":
            plan.entries.append(Entry("conflict", name, f"{file}: the file changed since the last sync and "
                                                        f"BidSheet.ai moved from revision {sync.revision} to "
                                                        f"revision {eq.revision}; not pulled (force bm pulls it)"))
            return
        note = (f"rewrite quote file {file} (BidSheet.ai quote {eq.quote_id} rev {sync.revision} "
                f"-> rev {eq.revision})")
    elif on_disk:
        if force != "bm":
            plan.entries.append(Entry("notice", name, f"{file}: no sidecar record; matches BidSheet.ai quote "
                                                      f"{eq.quote_id} (revision {eq.revision}) by vendor name; "
                                                      "not pulled (force bm pulls it)"))
            return
        note = f"rewrite quote file {file} (BidSheet.ai quote {eq.quote_id} rev {eq.revision})"
    else:
        note = f"new quote file {file} (BidSheet.ai quote {eq.quote_id} rev {eq.revision})"
    content, notices = _file_quote(eq, name, frame, export_pkg, local[file][0] if on_disk else None)
    if content is None:
        plan.entries.append(Entry("refused", name, f"{file}: {notices[0]}; not pulled"))
        return
    plan.entries += [Entry("notice", name, f"{file}: {n}") for n in notices]
    plan.ops.append(Op(next_id("u"), "write_file", "", {"file": file, "quote_id": eq.quote_id,
                                                       "revision": eq.revision}, name, note=note))
    plan.files[file] = content
    if on_disk:
        plan.backups.append(file)
    base = f"packages.{name}.quotes.{file}"
    plan.sidecar_updates += [(f"{base}.quote_id", eq.quote_id), (f"{base}.revision", eq.revision),
                             (f"{base}.vendor_id", eq.vendor_id), (f"{base}.file_sha", None)]
    plan.sidecar_updates += [(f"{base}.lines.{item_no}", line.get("line_id"))
                             for item_no, line in eq.lines.items()
                             if any(ql.item_number == item_no for ql in content.lines)]


# ---------- writing ----------

def _apply_updates(sidecar: Sidecar, updates: list[tuple[str, object]], shas: dict[str, str]) -> None:
    """Each (path, value) onto the sidecar; a quote touched here is rebuilt from its
    updates alone (a rewritten file's old line ids go)."""
    rebuilt: dict[tuple[str, str], dict] = {}
    for path, value in updates:
        sp = parse_sidecar_path(path)
        if sp is None:
            raise ValueError(f"unrecognised sidecar path {path}")
        if sp.file is not None:
            q = rebuilt.setdefault((sp.pkg, sp.file), {"lines": {}})
            if sp.item is not None:
                q["lines"][sp.item] = value
            else:
                q[sp.field] = shas.get(sp.file, value) if sp.field == "file_sha" else value
        elif sp.key in ("work_package_id", "estimate_package_id", "synced_at", "bm_choice", "spec_choice"):
            setattr(sidecar.package(sp.pkg), sp.key, value)
        else:
            raise ValueError(f"sidecar path {path} is not written by a pull")
    for (pkg, file), q in rebuilt.items():
        sidecar.package(pkg).quotes[file] = QuoteSync(q["quote_id"], q["revision"], q.get("vendor_id"),
                                                      q.get("file_sha") or "", q["lines"])


def _apply_spec_changes(spec: dict, changes: dict[str, dict]) -> None:
    """Each package's changes onto its `work_packages[]` entry; a None or empty value
    drops the key."""
    by_name = {_fold(n): c for n, c in changes.items()}
    for pkg in spec.get("work_packages") or []:
        for key, value in by_name.get(_fold(pkg.get("name")), {}).items():
            if value is None or value == {}:
                pkg.pop(key, None)
            else:
                pkg[key] = value


def write_pull(plan: PullPlan, spec_path: Path, qdir: Path, sidecar_path: Path) -> list[str]:
    """Write the plan's backups, files, spec and sidecar; the paths written, in that order."""
    spec_path, qdir, sidecar_path = Path(spec_path), Path(qdir), Path(sidecar_path)
    stamp = datetime.fromisoformat(plan.now).strftime("%Y%m%d-%H%M%S")
    wrote: list[str] = []
    for file in plan.backups:
        src = qdir / file
        if src.exists():
            bak = qdir / f"{file}.bak-{stamp}"
            shutil.copy2(src, bak)
            wrote.append(str(bak))
    shas = {}
    if plan.files:
        qdir.mkdir(parents=True, exist_ok=True)
    for file, quote in plan.files.items():
        write_quote_file(qdir / file, quote)
        shas[file] = file_sha(qdir / file)
        wrote.append(str(qdir / file))
    if plan.spec_changes:
        doc = SpecYaml(spec_path.read_text(encoding="utf-8"))
        _apply_spec_changes(doc.spec, plan.spec_changes)
        spec_path.write_text(doc.dumps(), encoding="utf-8")
        wrote.append(str(spec_path))
    if plan.sidecar_updates:
        sidecar = Sidecar.load(sidecar_path)
        _apply_updates(sidecar, plan.sidecar_updates, shas)
        if sidecar.project_id is None:
            sidecar.project_id = plan.meta.get("project_id")
        if sidecar.estimate_id is None:
            sidecar.estimate_id = plan.meta.get("estimate_id")
        sidecar.save(sidecar_path)
        wrote.append(str(sidecar_path))
    return wrote
