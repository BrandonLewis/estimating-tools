"""est-quotespace — solicitation journal, ITB docs, coverage board.

Subcommands:
  solicit   append one validated SolicitationRecord to the journal
  itb       package JSON + vendors JSON -> one ITB markdown per vendor
  coverage  journal + BM JSONL/JSON exports -> coverage board (added in a
            later task; stdout is the payload, status goes to stderr)
  condition append one validated QuoteConditionRecord to the
            quote-conditions journal
  sync      journal vs a BM list_solicitations export -> emit the delta
            (records newer/absent in BM) as JSON on stdout for the skill to
            push with record_solicitation

Deterministic file operations only; MCP traffic stays at the skill layer
(solicit-quotes / quote-coverage)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_json(path: str, what: str):
    p = Path(path)
    if not p.is_file():
        print(f"no such file: {p}", file=sys.stderr)
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"invalid {what} JSON in {p}: {exc}", file=sys.stderr)
        return None


def _read_text(path: str):
    p = Path(path)
    if not p.is_file():
        print(f"no such file: {p}", file=sys.stderr)
        return None
    return p.read_text(encoding="utf-8")


def cmd_solicit(args) -> int:
    from estimating_tools.quotespace.model import SolicitationRecord, append_records
    items = []
    if args.items:
        try:
            items = json.loads(args.items)
        except ValueError as exc:
            print(f"invalid --items JSON: {exc}", file=sys.stderr)
            return 1
    try:
        rec = SolicitationRecord(
            work_package={"name": args.package,
                          "bm_work_package_id": args.bm_package_id},
            vendor={"org_name": args.vendor, "bm_vendor_id": args.bm_vendor_id},
            contacts=args.contact,
            items=items, sent_at=args.sent_at, channel=args.channel,
            status=args.status, notes=args.notes)
    except ValueError as exc:
        print(f"invalid record: {exc}", file=sys.stderr)
        return 1
    out = append_records(args.journal, [rec])
    print(f"WROTE: {out} ({rec.record_id})", file=sys.stderr)
    return 0


def cmd_itb(args) -> int:
    from estimating_tools.quotespace.itb import render_itb, vendor_slug
    package = _load_json(args.package_json, "package")
    if package is None:
        return 1
    vendors = _load_json(args.vendors_json, "vendors")
    if vendors is None:
        return 1
    scope = ""
    if args.scope:
        scope = _read_text(args.scope)
        if scope is None:
            return 1
    letterhead = ""
    if args.letterhead:
        letterhead = _read_text(args.letterhead)
        if letterhead is None:
            return 1
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    used: dict[str, int] = {}
    for vendor in vendors:
        md = render_itb(
            project_name=package.get("project_name", ""),
            package_name=package.get("name", ""),
            vendor_name=vendor.get("org_name", ""),
            contacts=vendor.get("contacts", []),
            items=package.get("items", []),
            scope=scope, letterhead=letterhead,
            respond_by=args.respond_by, notes=args.notes)
        slug = vendor_slug(vendor.get("org_name", "vendor"))
        n = used[slug] = used.get(slug, 0) + 1
        path = out_dir / (f"{slug}.md" if n == 1 else f"{slug}-{n}.md")
        path.write_text(md, encoding="utf-8")
        print(f"WROTE: {path}", file=sys.stderr)
    return 0


def cmd_coverage(args) -> int:
    # stdout is the payload (markdown or JSON); status stays on stderr.
    from estimating_tools.quotespace.coverage import build_coverage, render_coverage_md
    from estimating_tools.quotespace.model import read_journal
    try:
        records = read_journal(args.journal)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    packages = _load_json(args.packages, "packages")
    if packages is None:
        return 1
    quotes = []
    allocations = []
    if args.quotes:
        quotes = _load_json(args.quotes, "quotes")
        if quotes is None:
            return 1
    if args.allocations:
        allocations = _load_json(args.allocations, "allocations")
        if allocations is None:
            return 1
    leveled = [s for s in (args.leveled or "").split(",") if s.strip()]
    cov = build_coverage(records, packages, quotes=quotes,
                         allocations=allocations, leveled=leveled)
    if args.json:
        print(json.dumps(cov, indent=2))
    else:
        print(render_coverage_md(cov))
    return 0


def cmd_condition(args) -> int:
    from estimating_tools.quotespace.conditions import QuoteConditionRecord
    from estimating_tools.quotespace.model import append_records
    tags = []
    for raw in args.tag:
        try:
            tags.append(json.loads(raw))
        except ValueError as exc:
            print(f"invalid --tag JSON: {exc}", file=sys.stderr)
            return 1
    flag = {"yes": True, "no": False, "unknown": None}[args.separate_acceptance]
    try:
        rec = QuoteConditionRecord(
            work_package={"name": args.package,
                          "bm_work_package_id": args.bm_package_id},
            vendor={"org_name": args.vendor, "bm_vendor_id": args.bm_vendor_id},
            separate_acceptance_permitted=flag,
            acceptance_notes=args.acceptance_notes,
            scope_tags=tags, notes=args.notes)
    except ValueError as exc:
        print(f"invalid record: {exc}", file=sys.stderr)
        return 1
    out = append_records(args.journal, [rec])
    print(f"WROTE: {out} ({rec.record_id})", file=sys.stderr)
    return 0


def cmd_sync(args) -> int:
    from estimating_tools.quotespace.model import (
        SolicitationRecord, current_records, read_journal)
    try:
        local = current_records(read_journal(args.journal))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    bm_raw = _load_json(args.bm_solicitations, "bm-solicitations")
    if bm_raw is None:
        return 1
    if not isinstance(bm_raw, list):
        print("bm-solicitations must be a JSON list of rows", file=sys.stderr)
        return 1
    # BM current state keyed the same way, via the adapter (rows carry the
    # skill-resolved work_package_name / vendor_org_name). A non-object row
    # (TypeError), a missing name field (KeyError), or an out-of-vocab
    # status/channel (ValueError from the record's validation) is a malformed
    # dump — report it and stop, don't traceback.
    bm = {}
    try:
        for row in bm_raw:
            if not isinstance(row, dict):
                raise TypeError("each row must be a JSON object")
            rec = SolicitationRecord.from_bm(
                row, work_package_name=row["work_package_name"],
                vendor_org_name=row["vendor_org_name"])
            bm[rec.key()] = rec
    except (KeyError, ValueError, TypeError) as exc:
        print(f"invalid bm-solicitations row: {exc}", file=sys.stderr)
        return 1

    delta = [rec.to_payload() for key, rec in local.items()
             if key not in bm
             or rec.content_signature() != bm[key].content_signature()]
    print(json.dumps(delta, indent=2))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="est-quotespace", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("solicit", help="append a solicitation record")
    p.add_argument("--journal", required=True)
    p.add_argument("--package", required=True)
    p.add_argument("--bm-package-id", dest="bm_package_id", type=int, default=None)
    p.add_argument("--vendor", required=True)
    p.add_argument("--bm-vendor-id", dest="bm_vendor_id", type=int, default=None)
    p.add_argument("--contact", action="append", default=[])
    p.add_argument("--items", default="",
                   help='JSON list of {"schedule", "item_number"}')
    p.add_argument("--status", choices=("planned", "sent", "declined"),
                   default="planned")
    p.add_argument("--sent-at", dest="sent_at", default="")
    p.add_argument("--channel", choices=("email", "phone", "portal", "other"),
                   default="email")
    p.add_argument("--notes", default="")
    p.set_defaults(func=cmd_solicit)

    p = sub.add_parser("itb", help="package + vendors JSON -> ITB markdown per vendor")
    p.add_argument("--package-json", dest="package_json", required=True)
    p.add_argument("--vendors-json", dest="vendors_json", required=True)
    p.add_argument("--scope", default="", help="scope text file (briefing excerpt)")
    p.add_argument("--letterhead", default="", help="org profile letterhead.md")
    p.add_argument("--respond-by", dest="respond_by", default="")
    p.add_argument("--notes", default="")
    p.add_argument("-o", "--output", required=True, help="output directory")
    p.set_defaults(func=cmd_itb)

    p = sub.add_parser("coverage", help="journal + BM exports -> coverage board")
    p.add_argument("--journal", required=True)
    p.add_argument("--packages", required=True,
                   help='JSON [{"name","strategy","items":[...]}]')
    p.add_argument("--quotes", default="",
                   help='JSON [{"vendor_name","work_package_name"} or '
                        '{"vendor_name","schedule","item_number"}]')
    p.add_argument("--allocations", default="",
                   help='JSON [{"vendor_name","schedule","item_number"}]')
    p.add_argument("--leveled", default="",
                   help="comma-separated package names with a current spread")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_coverage)

    p = sub.add_parser("condition", help="append a quote-condition record")
    p.add_argument("--journal", required=True)
    p.add_argument("--package", required=True)
    p.add_argument("--bm-package-id", dest="bm_package_id", type=int, default=None)
    p.add_argument("--vendor", required=True)
    p.add_argument("--bm-vendor-id", dest="bm_vendor_id", type=int, default=None)
    p.add_argument("--separate-acceptance", dest="separate_acceptance",
                   choices=("yes", "no", "unknown"), default="unknown")
    p.add_argument("--acceptance-notes", dest="acceptance_notes", default="")
    p.add_argument("--tag", action="append", default=[],
                   help='scope-tag JSON, repeatable: {"group", "items", '
                        '"treatment": "separate"|"folded", "folded_into"}')
    p.add_argument("--notes", default="")
    p.set_defaults(func=cmd_condition)

    p = sub.add_parser("sync", help="journal vs BM solicitations -> push delta")
    p.add_argument("--journal", required=True)
    p.add_argument("--bm-solicitations", dest="bm_solicitations", required=True,
                   help="JSON list of list_solicitations rows enriched with "
                        "work_package_name + vendor_org_name")
    p.set_defaults(func=cmd_sync)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
