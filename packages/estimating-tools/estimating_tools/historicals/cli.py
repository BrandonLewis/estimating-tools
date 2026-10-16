"""est-hist — parse bid tabs, emit historical-record payloads, suggest prices.

Subcommands:
  parse    bid tab (csv/xlsx/pdf) -> CanonicalBidTab JSON + QC summary
  records  CanonicalBidTab JSON -> record-payload JSONL (the interchange
           format for bulk_create_historical_records)
  from-estimate  CanonicalEstimate JSON -> own estimated/bid record JSONL
  suggest  record JSONL (e.g. a list_historical_records dump) + target ->
           suggestion JSON on stdout

Deterministic file operations only; MCP traffic stays at the skill layer
(import-historicals / price-estimate)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


def cmd_parse(args) -> int:
    from estimating_tools.historicals.tabs import cross_check, load
    try:
        tab = load(args.tab)
    except FileNotFoundError:
        print(f"no such file: {args.tab}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"cannot parse: {exc}", file=sys.stderr)
        return 1
    flags = cross_check(tab)
    out = Path(args.output or (Path(args.tab).with_suffix(".tab.json")))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(tab.to_json(), encoding="utf-8")
    print("WROTE:", out)
    print(f"QC: {len(tab.items)} items, {len(tab.bidders)} bidders, "
          f"{len(tab.warnings)} parse warnings, {len(flags)} total-check flags")
    for w in tab.warnings + flags:
        print("  !", w)
    return 0


def cmd_records(args) -> int:
    from estimating_tools.historicals.model import CanonicalBidTab
    try:
        tab = CanonicalBidTab.from_json(
            Path(args.tab_json).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"no such file: {args.tab_json}", file=sys.stderr)
        return 1
    except (ValueError, TypeError) as exc:
        print(f"invalid tab JSON: {exc}", file=sys.stderr)
        return 1
    records = tab.to_records()
    out = Path(args.output or Path(args.tab_json).with_suffix(".records.jsonl"))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec.to_payload()) + "\n")
    # Confirmation goes to stderr, not stdout: `suggest` is the one
    # subcommand whose stdout is a machine-parseable payload meant to be
    # piped/parsed on its own, so upstream commands in a chain keep their
    # status noise off of it.
    print("WROTE:", out, f"({len(records)} records)", file=sys.stderr)
    return 0


def cmd_from_estimate(args) -> int:
    from estimating_tools.historicals.estimates import estimate_to_records
    from estimating_tools.importers.model import CanonicalEstimate
    try:
        est = CanonicalEstimate.from_json(
            Path(args.canonical).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"no such file: {args.canonical}", file=sys.stderr)
        return 1
    except (ValueError, TypeError, KeyError) as exc:
        print(f"invalid canonical JSON: {exc}", file=sys.stderr)
        return 1
    code_map = {}
    if args.code_map:
        try:
            code_map = json.loads(Path(args.code_map).read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"no such file: {args.code_map}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"invalid code map JSON: {exc}", file=sys.stderr)
            return 1
        if not isinstance(code_map, dict):
            print(f"invalid code map JSON: expected an object, "
                  f"got {type(code_map).__name__}", file=sys.stderr)
            return 1
    records = estimate_to_records(
        est, outcome=args.outcome, agency=args.agency, region=args.region,
        bidder=args.bidder, project_ref=args.project_ref, code_map=code_map)
    out = Path(args.output or Path(args.canonical).with_suffix(".records.jsonl"))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec.to_payload()) + "\n")
    print("WROTE:", out, f"({len(records)} records)", file=sys.stderr)
    return 0


def cmd_suggest(args) -> int:
    # All status/error messages go to stderr: suggest's stdout is a pure,
    # machine-parseable JSON payload (see module docstring).
    from estimating_tools.historicals.suggest import suggest
    try:
        lines = Path(args.records).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        print(f"no such file: {args.records}", file=sys.stderr)
        return 1
    records = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"invalid JSON on line {n} of {args.records}: {exc}",
                  file=sys.stderr)
            return 1
    if args.code:
        records = [r for r in records if r.get("bid_item_code") == args.code]
    as_of = None
    if args.as_of:
        try:
            as_of = date.fromisoformat(args.as_of)
        except ValueError:
            print(f"invalid --as-of (expected YYYY-MM-DD): {args.as_of}",
                  file=sys.stderr)
            return 1
    result = suggest(
        records, quantity=args.qty, unit=args.unit, region=args.region,
        as_of=as_of, escalation_rate=args.escalation)
    print(json.dumps(result, indent=2))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="est-hist", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="bid tab file -> CanonicalBidTab JSON")
    p.add_argument("tab")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser("records", help="tab JSON -> record-payload JSONL")
    p.add_argument("tab_json")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_records)

    p = sub.add_parser("from-estimate",
                       help="CanonicalEstimate JSON -> own-record JSONL")
    p.add_argument("canonical")
    p.add_argument("--outcome", choices=("estimated", "bid"),
                   default="estimated")
    p.add_argument("--agency", default="", help="lowercase agency slug")
    p.add_argument("--region", default="")
    p.add_argument("--bidder", default="", help="our org name on the record")
    p.add_argument("--project-ref", dest="project_ref", default="",
                   help="override; defaults to the canonical project name")
    p.add_argument("--code-map", dest="code_map", default="",
                   help='JSON {"<schedule>::<item#>" | "<item#>": bid_item_code}')
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_from_estimate)

    p = sub.add_parser("suggest", help="record JSONL + target -> suggestion JSON")
    p.add_argument("--records", required=True)
    p.add_argument("--code", default="", help="filter to one bid_item_code")
    p.add_argument("--qty", type=float, default=None)
    p.add_argument("--unit", default="")
    p.add_argument("--region", default="")
    p.add_argument("--as-of", dest="as_of", default="")
    p.add_argument("--escalation", type=float, default=0.0,
                   help="flat annual rate, e.g. 0.03 (default off)")
    p.set_defaults(func=cmd_suggest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
