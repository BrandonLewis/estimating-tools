"""asm-load: parse an estimate-bound assembly spreadsheet (or JSON rows) into the
open CanonicalAssemblyLoad JSON (issue #201).

  asm-load load.xlsx --mapping mapping.json -o load.canonical.json
  asm-load rows.json  -o load.canonical.json

Rows bind assemblies to an estimate item via an ``estimate_item_id`` column
(+ optional ``bid_item_code``); ``production_rate`` / ``production_unit`` /
``labor_cost_basis`` carry the roll-up contract. A ``.xlsx`` file reads the first
worksheet; a ``.json`` file is a list of the same row dicts. The mapping JSON is
{canonical_field: column_header}; omit it for an identity mapping (columns named
after the canonical fields). Output is the open CanonicalAssemblyLoad you own —
no BidSheet.ai involved; ``plan_assembly_load`` enforces the contract at push time.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from estimating_tools.assemblies.excel import build_assembly_load, read_assembly_rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="asm-load",
        description="Import an estimate-bound assembly spreadsheet/JSON into "
                    "canonical assembly-load JSON (issue #201).")
    parser.add_argument("file", help="Path to the assembly rows (.xlsx or .json).")
    parser.add_argument("-m", "--mapping",
                        help="JSON file of {canonical_field: column_header} (default: identity).")
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
        if str(args.file).lower().endswith(".json"):
            with open(args.file, encoding="utf-8") as fh:
                rows = json.loads(fh.read())
            if not isinstance(rows, list):
                raise ValueError(
                    "JSON input must be a list of row objects (the same row shape "
                    "as the .xlsx path); got a "
                    f"{type(rows).__name__}"
                )
            load = build_assembly_load(rows, mapping)
        else:
            load = build_assembly_load(read_assembly_rows(args.file), mapping)
    except (OSError, ValueError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(asdict(load), indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
