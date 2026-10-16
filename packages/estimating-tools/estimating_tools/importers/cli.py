"""est-import: parse a legacy estimate export into canonical JSON."""
from __future__ import annotations

import argparse
import sys

import jsonschema

from estimating_tools.importers import registry
from estimating_tools.importers.hcss import HcssHeavyBidImporter
from estimating_tools.importers.validate import validate_canonical


def _register_builtins() -> None:
    if not any(getattr(i, "name", None) == "hcss-heavybid" for i in registry.importers()):
        registry.register(HcssHeavyBidImporter())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="est-import",
                                     description="Parse a legacy estimate export into canonical JSON.")
    parser.add_argument("file", help="Path to the export to import (e.g. an HCSS HeavyBid .xlsx).")
    parser.add_argument("-o", "--output", help="Write canonical JSON here (default: stdout).")
    args = parser.parse_args(argv)

    _register_builtins()
    try:
        est = registry.import_file(args.file)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    data = est.to_dict()
    try:
        validate_canonical(data)
    except jsonschema.ValidationError as exc:
        print(f"error: invalid canonical output: {exc}", file=sys.stderr)
        return 1
    text = est.to_json()
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        n_items = sum(len(s["items"]) for s in data["schedules"])
        print(f"wrote {args.output}: {len(data['schedules'])} schedule(s), {n_items} item(s)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
