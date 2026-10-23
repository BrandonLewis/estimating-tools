"""est-quotes — quote documents saved to a folder in, vendor quote files out.

Subcommands (each takes the estimate spec first):
  scan     record the inbox's new documents in the inventory
  text     recover the text of each new document, or route it to vision
  batch    write the work file the extraction agent reads
  import   apply the agent's results file: quote files and inventory records
           (a dry run without --write)
  report   the inventory as a table (or --json)
  requeue  reopen documents so the next batch offers them again
  run      scan, text and batch in one go: the bid-day loop's tick

Exit codes: 0 ok; 1 a refused results file; 2 the spec cannot be read, is not
a mapping, has no work_packages or work packages that do not build, the inbox
does not exist (scan, run), or a quote file on disk is malformed.
Deterministic file operations only; the skill (intake-quotes) drives the
agent between `batch` and `import`."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

from estimating_tools.estimate_spec.cli import _emit
from estimating_tools.estimate_spec.package_frames import PackageError
from estimating_tools.quotes.intake.inventory import (
    Inventory, inbox_dir_for, quotes_dir_for, state_dir_for)


def _load_spec(path: str):
    """The spec, its state dir and its quotes dir; None (after the message)
    when the spec cannot be used."""
    spec_path = Path(path).resolve()
    try:
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _emit(f"no such file: {spec_path}", file=sys.stderr)
        return None
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        _emit(f"invalid YAML in {spec_path}: {exc}", file=sys.stderr)
        return None
    if not isinstance(spec, dict):
        _emit(f"the spec is not a mapping: {spec_path}", file=sys.stderr)
        return None
    if not spec.get("work_packages"):
        _emit("the spec has no work_packages", file=sys.stderr)
        return None
    return spec, state_dir_for(spec_path, spec), quotes_dir_for(spec_path, spec)


def _save(inv: Inventory) -> None:
    if inv.dirty:
        inv.save()


def _bad_packages(exc: Exception) -> int:
    _emit(f"the spec's work packages: {exc}", file=sys.stderr)
    return 2


def _missing_inbox(report) -> bool:
    if report.missing_inbox:
        for line in report.lines:
            _emit(line, file=sys.stderr)
    return report.missing_inbox


def _print_unsupported(report) -> None:
    if report.unsupported:
        listed = ", ".join(f"{suffix} ×{n}" for suffix, n in report.unsupported.items())
        _emit(f"unsupported: {listed}", file=sys.stderr)


def _print_not_rendered(n: int) -> None:
    if n:
        _emit(f"{n} vision document(s) not rendered", file=sys.stderr)


def cmd_scan(args) -> int:
    from estimating_tools.quotes.intake.scan import scan_inbox
    loaded = _load_spec(args.spec)
    if loaded is None:
        return 2
    spec, state_dir, _ = loaded
    inv = Inventory.load(state_dir)
    report = scan_inbox(inv, inbox_dir_for(Path(args.spec), spec, args.inbox), state_dir)
    if _missing_inbox(report):
        return 2
    _save(inv)
    _emit(report.summary())
    for line in report.lines:
        _emit(line)
    _print_unsupported(report)
    return 0


def cmd_text(args) -> int:
    from estimating_tools.quotes.intake.text import recover_text
    loaded = _load_spec(args.spec)
    if loaded is None:
        return 2
    _, state_dir, _ = loaded
    inv = Inventory.load(state_dir)
    report = recover_text(inv, state_dir)
    _save(inv)
    _emit(report.summary())
    for line in report.lines:
        _emit(line)
    return 0


def cmd_batch(args) -> int:
    from estimating_tools.quotes.intake.batch import write_batch
    loaded = _load_spec(args.spec)
    if loaded is None:
        return 2
    spec, state_dir, _ = loaded
    inv = Inventory.load(state_dir)
    try:
        path, not_rendered = write_batch(inv, spec, state_dir, limit=args.limit,
                                         include_held=args.include_held,
                                         out=Path(args.output) if args.output else None)
    except PackageError as exc:
        return _bad_packages(exc)
    _save(inv)
    _emit(str(path) if path is not None else "nothing to extract")
    _print_not_rendered(not_rendered)
    return 0


def cmd_import(args) -> int:
    from estimating_tools.quotes.files import QuoteFileError
    from estimating_tools.quotes.intake.batch import ResultsError, read_results
    from estimating_tools.quotes.intake.importer import import_results
    loaded = _load_spec(args.spec)
    if loaded is None:
        return 2
    spec, state_dir, quotes_dir = loaded
    results = Path(args.results)
    try:
        payload = read_results(results)
    except ResultsError as exc:
        for error in exc.errors:
            _emit(error, file=sys.stderr)
        return 1
    if args.write:
        kept = state_dir / "results" / results.name
        if not (kept.exists() and kept.resolve() == results.resolve()):
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(results, kept)
    inv = Inventory.load(state_dir)
    try:
        report = import_results(inv, spec, quotes_dir, payload, write=args.write,
                                batch_name=results.name)
    except QuoteFileError as exc:
        _emit(f"quote file problem: {exc}", file=sys.stderr)
        return 2
    except PackageError as exc:
        return _bad_packages(exc)
    for line in report.lines():
        _emit(line)
    _emit(report.summary())
    if not args.write:
        _emit("dry run: run again with --write to apply")
    return 0


_COLUMNS = ("sha", "file", "route", "status", "vendor", "package", "quote file", "flags")


def _ordered(inv: Inventory) -> list:
    """Live records as the inventory iterates them, then the superseded ones."""
    live = list(inv)
    return live + [d for d in inv.all() if d.superseded_by is not None]


def _rows(doc) -> list[tuple[str, ...]]:
    """One row per result entry (a document on two packages is two rows)."""
    base = (doc.short, doc.file_name, doc.route or "", doc.status)
    flags = [doc.reason] if doc.reason else []
    if doc.superseded_by:
        flags.append(f"superseded by {doc.superseded_by[:8]}")
    if not doc.results:
        return [base + ("", "", "", "; ".join(flags))]
    return [base + (entry.get("vendor_name") or "", entry.get("work_package_name") or "",
                    entry.get("quote_file") or "",
                    "; ".join(flags + list(entry.get("needs_review") or [])))
            for entry in doc.results]


def cmd_report(args) -> int:
    loaded = _load_spec(args.spec)
    if loaded is None:
        return 2
    _, state_dir, _ = loaded
    docs = _ordered(Inventory.load(state_dir))
    if args.json:
        _emit(json.dumps({"documents": [asdict(d) for d in docs]}, indent=2))
        return 0
    rows = [_COLUMNS] + [row for doc in docs for row in _rows(doc)]
    widths = [max(len(row[i]) for row in rows) for i in range(len(_COLUMNS))]
    for row in rows:
        _emit("  ".join(value.ljust(w) for value, w in zip(row, widths)).rstrip())
    return 0


def cmd_requeue(args) -> int:
    loaded = _load_spec(args.spec)
    if loaded is None:
        return 2
    _, state_dir, _ = loaded
    if bool(args.sha) == bool(args.held):
        _emit("requeue takes SHA... or --held", file=sys.stderr)
        return 2
    inv = Inventory.load(state_dir)
    if args.held:
        docs = [d for d in inv if d.status == "held"]
    else:
        try:
            docs = [inv.find(prefix) for prefix in args.sha]
        except ValueError as exc:
            _emit(str(exc), file=sys.stderr)
            return 2
    for doc in docs:
        inv.requeue(doc)
        _emit(f"requeued {doc.short} {doc.file_name}")
    _save(inv)
    return 0


def cmd_run(args) -> int:
    from estimating_tools.quotes.intake.batch import write_batch
    from estimating_tools.quotes.intake.scan import scan_inbox
    from estimating_tools.quotes.intake.text import recover_text
    loaded = _load_spec(args.spec)
    if loaded is None:
        return 2
    spec, state_dir, _ = loaded
    inv = Inventory.load(state_dir)
    before = {d.sha256: d.status for d in inv.all()}
    scanned = scan_inbox(inv, inbox_dir_for(Path(args.spec), spec, args.inbox), state_dir)
    if _missing_inbox(scanned):
        return 2
    _save(inv)
    _print_unsupported(scanned)
    for line in scanned.lines:
        _emit(line, file=sys.stderr)
    recover_text(inv, state_dir)
    _save(inv)
    # A record this tick could not take (an .msg, an .xls, a bad scan) is named once.
    for doc in inv:
        if doc.status in ("held", "error") and before.get(doc.sha256) != doc.status:
            _emit(f"{doc.status} {doc.short} {doc.file_name}: {doc.reason}", file=sys.stderr)
    offered_before = {d.sha256 for d in inv.all() if d.offered_in}
    try:
        path, not_rendered = write_batch(inv, spec, state_dir, limit=args.limit)
    except PackageError as exc:
        return _bad_packages(exc)
    _save(inv)
    # stdout is the one line the loop reads; the rest goes to stderr.
    if path is not None:
        _emit(str(path))
    elif scanned.new == 0:
        _emit("nothing new")
    else:
        _emit("nothing to extract")
    _print_not_rendered(not_rendered)
    if path is not None:
        offered = [d for d in inv.all() if d.offered_in and d.offered_in[-1] == path.name]
        if offered and all(d.sha256 in offered_before for d in offered):
            _emit(f"{len(offered)} document(s) offered before and still open", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="est-quotes", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="record the inbox's new documents")
    p.add_argument("spec")
    p.add_argument("--inbox", default=None,
                   help="inbox folder (default: the spec's work_packages_inbox_dir)")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("text", help="recover text, or route a document to vision")
    p.add_argument("spec")
    p.set_defaults(func=cmd_text)

    p = sub.add_parser("batch", help="write the extraction work file")
    p.add_argument("spec")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("-o", "--output", default=None, help="work file path")
    p.add_argument("--include-held", dest="include_held", action="store_true")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("import", help="apply a results file (dry run without --write)")
    p.add_argument("spec")
    p.add_argument("results")
    p.add_argument("--write", action="store_true")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("report", help="the inventory as a table")
    p.add_argument("spec")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("requeue", help="reopen documents for the next batch")
    p.add_argument("spec")
    p.add_argument("sha", nargs="*", help="sha256 prefixes (8+ characters)")
    p.add_argument("--held", action="store_true", help="every held document")
    p.set_defaults(func=cmd_requeue)

    p = sub.add_parser("run", help="scan, text and batch in one go")
    p.add_argument("spec")
    p.add_argument("--inbox", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
