"""CLI for takeoff helpers: `est-takeoff convert 9 SF SY`,
`est-takeoff plan takeoff.json [--target estimate-structures|bid-item-quantities]
[--structure-id S1] [--existing existing.json]`, and
`est-takeoff audit --takeoff takeoff.json [--ifc model.ifc] [--no-mesh]
[--bm bm.json] [--tol-pct 1.0] [--geom-tol-pct 0.5] [--strict]
[--out audit.xlsx]` — a three-way quantity reconciliation (takeoff vs IFC
Qtos vs a BM estimate snapshot), plus a measured-geometry mesh leg whenever
an IFC is given, to an audit.xlsx workbook.

The default plan target is estimate-structures (takeoff quantities live on the
estimate layer); bid-item-quantities is legacy and forbidden on live bids
(BM #984)."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from estimating_tools.takeoff import core
from estimating_tools.takeoff.model import CanonicalTakeoff
from estimating_tools.takeoff.push import plan_takeoff_push


def _run_plan(args) -> int:
    try:
        with open(args.file, encoding="utf-8") as fh:
            takeoff = CanonicalTakeoff.from_json(fh.read())
        existing = None
        if args.existing:
            with open(args.existing, encoding="utf-8") as fh:
                existing = json.loads(fh.read())
            if not (isinstance(existing, list) and all(isinstance(e, dict) for e in existing)):
                raise ValueError("--existing must be a JSON list of objects")
        plan = plan_takeoff_push(takeoff, existing, target=args.target,
                                 structure_id=args.structure_id)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(asdict(plan), indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


def _run_audit(args) -> int:
    from datetime import datetime

    from estimating_tools.takeoff.audit import build_audit, load_bm_snapshot
    from estimating_tools.takeoff.audit_xlsx import write_audit_xlsx
    try:
        from pathlib import Path
        takeoff = CanonicalTakeoff.from_json(
            Path(args.takeoff).read_text(encoding="utf-8"))
        ifc = None
        if args.ifc:
            # lazy: convert/plan must keep working without ifcopenshell
            import ifcopenshell

            from bimforge.bim.ifc_takeoff import ifc_leg
            try:
                ifc = ifc_leg(args.ifc)
            except ifcopenshell.Error as exc:
                raise ValueError(f"unreadable IFC {args.ifc}: {exc}") from exc
        mesh = None
        if ifc is not None and not args.no_mesh:
            from bimforge.bim.ifc_mesh import mesh_leg
            try:
                mesh = mesh_leg(args.ifc)
            except ifcopenshell.Error as exc:
                raise ValueError(
                    f"unreadable IFC {args.ifc}: {exc}") from exc
        bm = None
        if args.bm:
            bm = load_bm_snapshot(
                json.loads(Path(args.bm).read_text(encoding="utf-8")))
        try:
            from importlib.metadata import version
            tool = version("estimating_tools")
        except Exception:
            tool = "?"
        report = build_audit(
            takeoff, ifc=ifc, bm=bm, mesh=mesh, tol_pct=args.tol_pct,
            geom_tol_pct=args.geom_tol_pct,
            provenance={"takeoff": args.takeoff, "ifc": args.ifc,
                        "bm": args.bm,
                        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "tool": tool})
        out = args.out or str(Path(args.takeoff).with_suffix("")) + ".audit.xlsx"
        write_audit_xlsx(report, out)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError,
            ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    legs = ", ".join(k.upper() for k, v in sorted(report.legs.items()) if v)
    print(f"{out}: {len(report.items)} item(s), {len(report.elements)} "
          f"element(s), {len(report.exceptions)} exception(s) — legs: "
          f"{legs or 'takeoff only'}")
    if report.legs.get("mesh"):
        mc = report.provenance.get("mesh_counts", {})
        gv = sum(1 for i in report.items if i.geom_status == "GEOM VARIANCE")
        print(f"  mesh leg: {mc.get('meshed', 0)} meshed, "
              f"{mc.get('qto_only', 0)} qto-only, "
              f"{mc.get('unclassified', 0)} unclassified — "
              f"{gv} item(s) at GEOM VARIANCE "
              f"(tol ±{report.provenance.get('geom_tol_pct')}%)")
    for f in report.exceptions:
        print(f"  ! [{f.kind}] {f.item_key or '(file)'}: {f.detail}",
              file=sys.stderr)
    if args.strict and report.exceptions:
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="est-takeoff")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("convert")
    c.add_argument("quantity", type=float)
    c.add_argument("from_unit")
    c.add_argument("to_unit")
    c.add_argument("--material", default="general")

    p = sub.add_parser("plan")
    p.add_argument("file", help="CanonicalTakeoff JSON file")
    p.add_argument("--target", choices=["estimate-structures", "bid-item-quantities"],
                   default="estimate-structures",
                   help="estimate-structures (default) plans structure sections on the "
                        "estimate; bid-item-quantities is LEGACY — it writes the official "
                        "agency schedule quantity and is forbidden on live bids (BM #984)")
    p.add_argument("--structure-id",
                   help="BidSheet.ai structure id for --target estimate-structures "
                        "(default: the takeoff's project_ref)")
    p.add_argument("--existing", help="JSON list of existing bid items "
                                      "[{item_number, schedule, cost_code?, project_bid_item_id}] "
                                      "(bid-item-quantities target only)")
    p.add_argument("-o", "--output", help="Write plan JSON here (default: stdout)")

    a = sub.add_parser("audit", help="Quantity audit: takeoff vs IFC Qtos "
                                     "vs BM estimate snapshot, with a "
                                     "measured-geometry mesh leg -> "
                                     "audit.xlsx")
    a.add_argument("--takeoff", required=True, help="CanonicalTakeoff JSON")
    a.add_argument("--ifc", help="IFC to re-read Qto quantities from "
                                 "(omit: no IFC leg)")
    a.add_argument("--bm", help="BM estimate snapshot JSON fetched by the "
                                "audit-quantities skill (omit: no BM leg)")
    a.add_argument("--out", help="output .xlsx "
                                 "(default: <takeoff stem>.audit.xlsx)")
    a.add_argument("--tol-pct", type=float, default=1.0,
                   help="variance tolerance in percent (default 1.0)")
    a.add_argument("--strict", action="store_true",
                   help="exit nonzero when any Exceptions rows exist "
                        "(pre-push gate)")
    a.add_argument("--no-mesh", action="store_true",
                   help="skip the measured-geometry (mesh) leg that "
                        "otherwise runs whenever --ifc is given")
    a.add_argument("--geom-tol-pct", type=float, default=0.5,
                   help="mesh vs authored-volume tolerance in percent "
                        "(default 0.5)")

    args = parser.parse_args(argv)
    if args.cmd == "convert":
        print(json.dumps(
            core.convert_units(args.quantity, args.from_unit, args.to_unit, args.material),
            indent=2))
        return 0
    if args.cmd == "plan":
        return _run_plan(args)
    if args.cmd == "audit":
        return _run_audit(args)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
