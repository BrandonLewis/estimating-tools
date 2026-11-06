"""Apply the skill's MCP results to the sidecar (the only step that writes its contents).

`apply_results(plan, results, sidecar, now=...)` walks the plan's ops in order. An op with no
result is skipped; a result carrying "error" is an error and writes nothing; an op whose
`after` chain reaches a failed op is skipped. For every other op each `Op.sidecar` entry
(dotted sidecar path -> result path) is written.

Sidecar path grammar (names may contain spaces and dots, so paths are parsed by shape, not
split on dots)::

    packages.<pkg>.work_package_id | estimate_package_id | bm_choice | spec_choice (pull only)
    packages.<pkg>.plugs_removed.<item>                 (value: the entry dict
                      {"assembly_id", "component_id", "name"}, appended as recorded; a
                      legacy "+<assembly_id>:<component_id>" string appends a nameless entry)
    packages.<pkg>.quotes.<file>.quote_id | revision | vendor_id | file_sha
    packages.<pkg>.quotes.<file>.lines.<item>

`<pkg>` runs to the first following `.quotes`, `.bm_choice`, `.spec_choice`, `.plugs_removed`,
`.work_package_id`, `.estimate_package_id` or `.synced_at`; `<file>` ends in `.json`.

Result paths: `$` (whole result), `$.a.b`, `$.a[0].b`, `$.a[?key=='v'].b` (the element of `a`
whose `key` equals 'v'). `bm_choice` is recorded from `plan.meta["bm_choice"][pkg]` (its
`selected_quote_id` may be a `$ref` placeholder, resolved from that op's result), falling back
to the op's whole result. When an op revises a quote, that quote's `lines` are rebuilt from
this plan's results alone.

A package with applied ops, or one the sidecar already records, whose `work_package_id` /
`estimate_package_id` is still None after the ops (it already existed, so the plan had no
ensure op) gets them from `plan.meta["package_ids"][pkg]`, the export's ids (#421).
A package with applied ops whose plan has no op recording `bm_choice` gets
`plan.meta["bm_choice"][pkg]` (BidSheet.ai's observed choice) as its baseline (ruling 41).
`plan.meta["adopt"][pkg][file]` (`{"quote_id", "revision", "vendor_id", "lines"}`) is
written as that file's `QuoteSync`, with `file_sha` from `meta["file_sha"]`, on every
apply, even when no op applied (ruling 44); an entry the sidecar already has is kept.
`plan.meta["stale_plugs"][pkg][item]` lists `plugs_removed` entries whose assembly a
push-assemblies re-push replaced (#428): apply drops them from the sidecar on every apply
and names each in `pruned`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from estimating_tools.estimate_spec.bm_sync.ops import Op, Plan
from estimating_tools.estimate_spec.bm_sync.sidecar import (
    QuoteSync, Sidecar, plug_entry, plug_key, plug_text)

_PKG = re.compile(r"^packages\.(?P<pkg>.+?)\.(?P<key>quotes|bm_choice|spec_choice|plugs_removed|work_package_id"
                  r"|estimate_package_id|synced_at)(?:\.(?P<rest>.*))?$", re.S)
_QUOTE = re.compile(r"^(?P<file>.+?\.json)\.(?P<field>quote_id|revision|vendor_id|file_sha|lines\.(?P<item>.+))$", re.S)
_TOKEN = re.compile(r"\.(\w+)|\[(\d+)\]|\[\?(\w+)=='([^']*)'\]")


@dataclass
class SidecarPath:
    """A parsed sidecar path: `file`/`field`/`item` are set for a `quotes` path."""
    pkg: str
    key: str
    rest: str | None
    file: str | None = None
    field: str | None = None
    item: str | None = None


def parse_sidecar_path(path: str) -> SidecarPath | None:
    """`path` parsed by the grammar above; None when it does not fit (a `quotes` path
    without a recognised file field is None too)."""
    m = _PKG.match(path)
    if not m:
        return None
    sp = SidecarPath(m["pkg"], m["key"], m["rest"])
    if sp.key == "quotes":
        qm = _QUOTE.match(sp.rest or "")
        if not qm:
            return None
        sp.file, sp.field, sp.item = qm["file"], qm["field"], qm["item"]
    return sp


@dataclass
class ApplyReport:
    applied: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)     # stale plugs_removed entries dropped (#428)


def resolve_path(result, path: str):
    """The value at `path` in `result`; KeyError when it is not there."""
    if not path.startswith("$"):
        raise KeyError(path)
    cur, pos = result, 1
    while pos < len(path):
        m = _TOKEN.match(path, pos)
        if not m:
            raise KeyError(path)
        name, idx, fkey, fval = m.groups()
        try:
            if name is not None:
                cur = cur[name]
            elif idx is not None:
                cur = cur[int(idx)]
            else:
                cur = next(e for e in cur if isinstance(e, dict) and str(e.get(fkey)) == fval)
        except (KeyError, IndexError, TypeError, StopIteration):
            raise KeyError(path) from None
        pos = m.end()
    return cur


def _resolve_arg(value, results: dict, failed: dict):
    """A `$ref` placeholder resolved from its op's result; the value itself otherwise.
    Raises KeyError when the referenced op has no usable result."""
    if isinstance(value, dict) and "$ref" in value:
        ref = value["$ref"]
        if ref in failed or not isinstance(results.get(ref), dict) or "error" in results[ref]:
            raise KeyError(ref)
        return resolve_path(results[ref], value.get("path", "$"))
    return value


@dataclass
class _QuotePending:
    fields: dict = field(default_factory=dict)
    lines: dict = field(default_factory=dict)
    reset: bool = False
    touched: bool = False


def apply_results(plan: Plan, results: dict, sidecar: Sidecar, *, now: str) -> ApplyReport:
    res = results.get("results", {})
    meta = plan.meta
    report = ApplyReport()
    failed: dict[str, tuple[str, str]] = {}   # op id -> (root op id, "failed" | "has no result")
    after_of = {op.id: op.after for op in plan.ops}
    touched_pkgs: set[str] = set()
    quotes: dict[tuple[str, str], _QuotePending] = {}

    sidecar.project_id = meta.get("project_id", sidecar.project_id)
    sidecar.estimate_id = meta.get("estimate_id", sidecar.estimate_id)

    for op in plan.ops:
        dep, a = None, op.after
        while a is not None and dep is None:
            dep = a if a in failed else None
            a = after_of.get(a)
        if dep is not None:
            failed[op.id] = failed[dep]
            root, why = failed[dep]
            report.skipped.append((op.id, f"depends on {root} which {why}"))
            continue
        result = res.get(op.id)
        if result is None:
            failed[op.id] = (op.id, "has no result")
            report.skipped.append((op.id, "no result"))
            continue
        if isinstance(result, dict):
            ws = result.get("carry_warnings") or []
            ws = [ws] if isinstance(ws, str) else list(ws)
            if result.get("carry_warning"):
                ws.insert(0, result["carry_warning"])
            report.warnings += [f"{op.id} {op.kind} {op.package}: {w}" for w in ws]
            if "error" in result:
                failed[op.id] = (op.id, "failed")
                report.errors.append((op.id, str(result["error"])))
                continue
        n_err = len(report.errors)
        _write_op(op, result, sidecar, plan, res, failed, quotes, report)
        if len(report.errors) == n_err:
            report.applied.append(op.id)
            touched_pkgs.add(op.package)

    for (pkg, file), q in quotes.items():
        if not q.touched:
            continue
        cur = sidecar.package(pkg).quotes.get(file)
        merged = {"quote_id": cur.quote_id if cur else None, "revision": cur.revision if cur else None,
                  "vendor_id": cur.vendor_id if cur else None, "file_sha": cur.file_sha if cur else "",
                  **q.fields}
        if merged["quote_id"] is None:
            continue
        lines = {} if q.reset or cur is None else dict(cur.lines)
        lines.update(q.lines)
        sidecar.package(pkg).quotes[file] = QuoteSync(
            merged["quote_id"], merged["revision"], merged["vendor_id"], merged["file_sha"], lines)

    choice_pkgs = {sp.pkg for op in plan.ops for path in op.sidecar
                   if (sp := parse_sidecar_path(path)) is not None and sp.key == "bm_choice"}
    for pkg in touched_pkgs:
        ps = sidecar.package(pkg)
        ps.synced_at = now
        if pkg in meta.get("spec_choice", {}):
            ps.spec_choice = meta["spec_choice"][pkg]
        snap = (meta.get("bm_choice") or {}).get(pkg)
        if pkg not in choice_pkgs and snap is not None:
            snap = _snapshot(snap, pkg, "baseline", "bm_choice", res, failed, report)
            if snap is not None:
                ps.bm_choice = snap

    for pkg in touched_pkgs | set(sidecar.packages):   # ids only; baselines stay above (#421)
        ps = sidecar.package(pkg)
        ids = (meta.get("package_ids") or {}).get(pkg) or {}
        for key in ("work_package_id", "estimate_package_id"):
            if getattr(ps, key) is None and ids.get(key) is not None:
                setattr(ps, key, ids[key])

    for pkg, items in (meta.get("stale_plugs") or {}).items():    # #428
        ps = sidecar.package(pkg)
        for item_no, stale in items.items():
            keys = {plug_key(plug_entry(e)) for e in stale}
            kept = []
            for e in ps.plugs_removed.get(item_no) or []:
                if plug_key(e) in keys:
                    report.pruned.append(f"{pkg} item {item_no}: {plug_text(e)}")
                else:
                    kept.append(e)
            if kept:
                ps.plugs_removed[item_no] = kept
            else:
                ps.plugs_removed.pop(item_no, None)

    for pkg, files in (meta.get("adopt") or {}).items():
        for file, a in files.items():
            ps = sidecar.package(pkg)
            if file not in ps.quotes:
                ps.quotes[file] = QuoteSync(a["quote_id"], a["revision"], a.get("vendor_id"),
                                            meta.get("file_sha", {}).get(file, ""),
                                            {str(n): lid for n, lid in (a.get("lines") or {}).items()})
    return report


def _snapshot(snap: dict, pkg: str, op_id: str, kind: str, res: dict, failed: dict,
              report: ApplyReport) -> dict | None:
    """A `bm_choice` snapshot with its `selected_quote_id` reference resolved; None (and a
    skip or error in the report) when the referenced op has no usable result."""
    snap = dict(snap)
    ref = snap.get("selected_quote_id")
    try:
        snap["selected_quote_id"] = _resolve_arg(ref, res, failed)
    except KeyError:
        if ref["$ref"] in failed:
            report.skipped.append((op_id, f"bm_choice for {pkg} depends on "
                                          f"{ref['$ref']} which {failed[ref['$ref']][1]}"))
        else:
            report.errors.append((op_id, f"{op_id} {kind} {pkg}: result has no "
                                         f"{ref.get('path', '$')} (from {ref['$ref']})"))
        return None
    return snap


def _write_op(op: Op, result, sidecar: Sidecar, plan: Plan, res: dict, failed: dict,
              quotes: dict, report: ApplyReport) -> None:
    meta = plan.meta
    if op.kind == "create_revision":
        for path in op.sidecar:
            sp = parse_sidecar_path(path)
            if sp and sp.file:
                quotes.setdefault((sp.pkg, sp.file), _QuotePending()).reset = True
    for path, rpath in op.sidecar.items():
        sp = parse_sidecar_path(path)
        if not sp:
            report.warnings.append(f"{op.id}: unrecognised sidecar path {path}")
            continue
        pkg, key, rest = sp.pkg, sp.key, sp.rest
        ps = sidecar.package(pkg)
        try:
            if key == "bm_choice":
                snap = (meta.get("bm_choice") or {}).get(pkg)
                if snap is None:
                    report.errors.append((op.id, f"bm_choice for {pkg}: plan carries no snapshot"))
                    continue
                snap = _snapshot(snap, pkg, op.id, op.kind, res, failed, report)
                if snap is not None:
                    ps.bm_choice = snap
            elif key == "quotes":
                q = quotes.setdefault((pkg, sp.file), _QuotePending())
                q.touched = True
                q.fields["file_sha"] = meta.get("file_sha", {}).get(sp.file, "")
                if sp.item is not None:
                    q.lines[sp.item] = resolve_path(result, rpath)
                else:
                    q.fields[sp.field] = resolve_path(result, rpath)
                if op.kind == "create_quote" and "vendor_id" not in q.fields:
                    q.fields["vendor_id"] = _vendor_id(op, result, res, failed)
            elif key == "plugs_removed":
                if isinstance(rpath, dict):
                    entry = plug_entry(rpath)
                elif rpath.startswith("+"):
                    entry = plug_entry(rpath[1:])
                else:
                    entry = plug_entry(resolve_path(result, rpath))
                ps.plugs_removed.setdefault(rest, []).append(entry)
            else:   # work_package_id, estimate_package_id, synced_at
                setattr(ps, key, resolve_path(result, rpath))
        except KeyError:
            report.errors.append((op.id, f"{op.id} {op.kind} {op.package}: result has no {rpath}"))


def _vendor_id(op: Op, result, res: dict, failed: dict):
    if isinstance(result, dict) and result.get("vendor_id") is not None:
        return result["vendor_id"]
    try:
        return _resolve_arg(op.args.get("vendor_id"), res, failed)
    except KeyError:
        return None

