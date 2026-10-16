"""costcode-import: parse an org cost-code spreadsheet into the open canonical JSON.

  costcode-import codes.xlsx --system-name "Std Codes 2026" --mapping mapping.json -o out.json

The mapping JSON is {canonical_field: column_header}; omit it for an identity mapping.
--system-name is required (the cost-code system's display name). Output is the open
CanonicalCostCodeSystem JSON you own — no BidSheet.ai involved."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from estimating_tools.costcodes.excel import build_cost_code_system_from_excel


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="costcode-import",
        description="Import an org cost-code spreadsheet into canonical JSON.")
    parser.add_argument("file", help="Path to the cost-code spreadsheet (.xlsx).")
    parser.add_argument("--system-name", required=True,
                        help="Display name for the cost-code system (required).")
    parser.add_argument("--version", default="", help="Optional version string.")
    parser.add_argument("--description", default="", help="Optional description.")
    parser.add_argument("-m", "--mapping",
                        help="JSON file of {canonical_field: column_header} (default: identity).")
    parser.add_argument("--parent-strategy", default="explicit_column",
                        help="Parent-derivation strategy: explicit_column (default), "
                             "segment_truncate, numeric_stub, indentation, flat.")
    parser.add_argument("--composition", default="composed",
                        choices=["composed", "monolithic"],
                        help="Whether full codes compose a bid-item prefix (composed) "
                             "or stand alone (monolithic). Default composed.")
    parser.add_argument("--source-system", default="",
                        help="Classification system name (e.g. MasterFormat) -> IFC identity.")
    parser.add_argument("--edition", default="", help="Classification edition (e.g. 2020).")
    parser.add_argument("-o", "--output", help="Write canonical JSON here (default: stdout).")
    args = parser.parse_args(argv)

    mapping = None
    if args.mapping:
        try:
            with open(args.mapping, encoding="utf-8") as fh:
                mapping = json.loads(fh.read())
        except (OSError, ValueError) as exc:
            print(f"error: could not read mapping {args.mapping}: {exc}", file=sys.stderr)
            return 1

    try:
        system = build_cost_code_system_from_excel(
            args.file, system_name=args.system_name, version=args.version,
            description=args.description, mapping=mapping,
            parent_strategy=args.parent_strategy, composition=args.composition,
            source_system=args.source_system, edition=args.edition)
    except (OSError, ValueError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(asdict(system), indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
