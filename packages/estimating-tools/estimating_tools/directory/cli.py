"""dir-import: parse an org directory spreadsheet into the open canonical JSON.

  dir-import directory.xlsx --mapping mapping.json -o directory.canonical.json

The mapping JSON is {canonical_field: column_header}; omit it for an identity mapping.
Output is the open CanonicalDirectory JSON you own — no BidSheet.ai involved."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from estimating_tools.directory.excel import build_directory_from_excel


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="dir-import",
        description="Import an org vendor/sub directory spreadsheet into canonical JSON.")
    parser.add_argument("file", help="Path to the directory spreadsheet (.xlsx).")
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
        directory = build_directory_from_excel(args.file, mapping)
    except (OSError, ValueError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(asdict(directory), indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
