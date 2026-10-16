"""est-schedule — deterministic schedule analysis surfaces.

  est-schedule costload --schedule sched.json --costs costs.json
      [--task-map m.json] [--name-code-re RE] [--work-hours-per-day 8]
      [--bucket week|month] [--json] [--csv out.csv] [--xlsx out.xlsx]

  est-schedule scope <gc-schedule.{xer,xml,mspdi,gw.json,json}>
      [--resource X | --activity-code Y] [--list-resources | --list-codes]
      [-o out.json] [--xlsx out.xlsx]

stdout is the payload (markdown board by default, or --json; for `scope`
the filtered canonical JSON, or the listing); coverage warnings and status
go to stderr. `costs.json` is
{bid_item_code: {"cost": float, "labor_hours": float|null}} — the skill
assembles it from the BidSheet.ai priced estimate. `scope` filters a GC's
full schedule to a sub-scope (R8): external predecessor ties are preserved
in `external_dependencies` / the External Preds column, never dropped.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path


def _run_costload(args) -> int:
    from estimating_tools.schedule.costload import (
        load_schedule_costs, validate_costs)
    from estimating_tools.schedule.importers import load_schedule
    from bimforge.bim.schedule_model import resolve_bid_item_codes

    try:
        sched = load_schedule(args.schedule)
        task_map = {}
        if args.task_map:
            task_map = json.loads(Path(args.task_map).read_text(encoding="utf-8"))
            if not isinstance(task_map, dict):
                raise ValueError("--task-map must be a JSON object")
        resolve_bid_item_codes(sched, task_map=task_map,
                               name_code_re=args.name_code_re)
        costs = json.loads(Path(args.costs).read_text(encoding="utf-8"))
        validate_costs(costs)
        loaded = load_schedule_costs(sched, costs,
                                     work_hours_per_day=args.work_hours_per_day)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    from estimating_tools.schedule import render
    if args.json:
        print(json.dumps(dataclasses.asdict(loaded), indent=2))
    else:
        print(render.render(loaded, bucket=args.bucket))
    if args.csv:
        Path(args.csv).write_text(render.to_csv(loaded, bucket=args.bucket),
                                  encoding="utf-8")
        print(f"cash-flow CSV written to {args.csv}", file=sys.stderr)
    if args.xlsx:
        try:
            render.to_xlsx(loaded, args.xlsx, bucket=args.bucket)
        except ImportError:
            print("error: --xlsx needs openpyxl "
                  "(pip install openpyxl, or the [plugin-core] extra)",
                  file=sys.stderr)
            return 1
        print(f"cash-flow workbook written to {args.xlsx}", file=sys.stderr)

    _report(loaded)
    return 0


def _report(loaded) -> None:
    if loaded.unloaded_cost:
        total = sum(loaded.unloaded_cost.values())
        print(f"\nReview: unloaded cost — {len(loaded.unloaded_cost)} priced "
              f"item(s) mapped to no task (${total:,.0f} not on the curve):",
              file=sys.stderr)
        for code, amt in sorted(loaded.unloaded_cost.items()):
            print(f"  ! {code}: ${amt:,.0f}", file=sys.stderr)
    if loaded.no_hours_items:
        print(f"\nReview: {len(loaded.no_hours_items)} item(s) priced without a "
              f"labor breakdown — in cash flow, zero workers:", file=sys.stderr)
        for code in loaded.no_hours_items:
            print(f"  ! {code}", file=sys.stderr)
    if loaded.unpriced_tasks:
        print(f"\nReview: {len(loaded.unpriced_tasks)} task(s) whose codes are "
              f"not priced:", file=sys.stderr)
        for tid in loaded.unpriced_tasks:
            print(f"  ! task {tid}", file=sys.stderr)


def _run_scope(args) -> int:
    from estimating_tools.schedule import scope as scope_mod
    from estimating_tools.schedule.importers import load_schedule

    try:
        sched = load_schedule(args.file)
        if args.list_resources or args.list_codes:
            pairs = (scope_mod.list_resources(sched) if args.list_resources
                     else scope_mod.list_activity_codes(sched))
            for name, n in pairs:
                print(f"{name}  ({n} tasks)")
            return 0
        if not args.resource and not args.activity_code:
            args._parser.error(
                "one of --resource/--activity-code is required "
                "(or --list-resources/--list-codes)")
        filtered, report = scope_mod.filter_to_scope(
            sched, resource=args.resource, activity_code=args.activity_code)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    payload = filtered.to_json()
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(f"filtered schedule written to {args.out}", file=sys.stderr)
    else:
        print(payload)
    if args.xlsx:
        try:
            scope_mod.write_task_table(filtered, args.xlsx)
        except ImportError:
            print("error: --xlsx needs openpyxl "
                  "(pip install openpyxl, or the [plugin-core] extra)",
                  file=sys.stderr)
            return 1
        print(f"task table written to {args.xlsx}", file=sys.stderr)

    print(f"scope: {report.resolved} — {report.matched} task(s) matched, "
          f"{report.summaries_kept} summary row(s) kept, "
          f"{report.dropped_tasks} task(s) outside scope dropped",
          file=sys.stderr)
    print(f"predecessors: {report.internal_preds} internal kept, "
          f"{report.external_preds} external moved to external_dependencies",
          file=sys.stderr)
    return 0


def _run_xer(args) -> int:
    from estimating_tools.schedule import xer

    try:
        tables = xer.read_tables(args.xer)
        if not tables.get("TASK"):
            raise ValueError("no TASK table in the XER — not a P6 activity "
                             "export?")
        out = args.out or str(Path(args.xer).with_suffix(".xlsx"))
        if args.profile == "dump":
            xer.write_dump(tables, out, hours_per_day=args.work_hours_per_day,
                           raw=not args.no_raw)
        else:  # bridge
            if not args.config:
                args._parser.error("--config is required for --profile bridge")
            config = json.loads(Path(args.config).read_text(encoding="utf-8"))
            xer.write_bridge(tables, out, config)
    except ImportError:
        print("error: est-schedule xer needs openpyxl "
              "(pip install openpyxl, or the [plugin-core] extra)",
              file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    n_tasks = len(tables.get("TASK", []))
    print(f"wrote {out} ({args.profile} profile, {n_tasks} activities)",
          file=sys.stderr)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="est-schedule", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("costload", help="cost- & resource-load a schedule")
    c.add_argument("--schedule", required=True)
    c.add_argument("--costs", required=True)
    c.add_argument("--task-map", dest="task_map", default=None)
    c.add_argument("--name-code-re", dest="name_code_re", default=None)
    c.add_argument("--work-hours-per-day", dest="work_hours_per_day",
                   type=float, default=8.0)
    c.add_argument("--bucket", choices=("week", "month"), default="month")
    c.add_argument("--json", action="store_true")
    c.add_argument("--csv", default=None)
    c.add_argument("--xlsx", default=None)
    c.set_defaults(func=_run_costload)
    s = sub.add_parser("scope",
                       help="filter a GC's full schedule to a sub-scope")
    s.add_argument("file", help="schedule (.xer/.xml/.mspdi/.gw.json/.json)")
    sel = s.add_mutually_exclusive_group()
    sel.add_argument("--resource", default=None,
                     help="case-insensitive substring of resource name(s)")
    sel.add_argument("--activity-code", dest="activity_code", default=None,
                     help="substring resolving to exactly one activity code")
    s.add_argument("--list-resources", dest="list_resources",
                   action="store_true")
    s.add_argument("--list-codes", dest="list_codes", action="store_true")
    s.add_argument("-o", "--out", dest="out", default=None,
                   help="write filtered canonical JSON here (default stdout)")
    s.add_argument("--xlsx", default=None,
                   help="also write the 9-column Task Table workbook")
    s.set_defaults(func=_run_scope, _parser=s)
    x = sub.add_parser(
        "xer", help="P6 .xer -> Excel (dump | bridge profiles); the "
                    "import-tasks / activity-code filter is `scope`")
    x.add_argument("xer", help="Primavera P6 .xer export")
    x.add_argument("--profile", choices=("dump", "bridge"), default="dump",
                   help="dump = full raw workbook; bridge = formatted "
                        "per-selector deliverable (needs --config)")
    x.add_argument("--out", default=None,
                   help="output .xlsx (default: alongside the .xer)")
    x.add_argument("--config", default=None,
                   help="bridge sheet/selector JSON (required for --profile "
                        "bridge; org data lives here, not in the tool)")
    x.add_argument("--no-raw", dest="no_raw", action="store_true",
                   help="dump: omit the per-table raw sheets")
    x.add_argument("--work-hours-per-day", dest="work_hours_per_day",
                   type=float, default=8.0)
    x.set_defaults(func=_run_xer, _parser=x)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
