"""profile-init: scaffold a new org profile directory.

  profile-init <target-dir> --name "Acme Builders" --fields fields.json

--name is required; --fields is an optional JSON file with the rest of the inputs
(company_name, address, logo, tree, letterhead, compliance_label, spec_note, naming).
Writes profile.yaml + tree.yaml + letterhead.md into <target-dir>. Local files only."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from estimating_tools.profiles.build import ProfileInputs, build_profile_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="profile-init", description="Scaffold a new org profile directory.")
    parser.add_argument("directory", help="Target directory to create the profile in.")
    parser.add_argument("--name", required=True, help="Profile / organization name.")
    parser.add_argument("--fields",
                        help="JSON file with the rest of the inputs (company_name, address, "
                             "logo, tree, letterhead, compliance_label, spec_note, naming, "
                             "estimating_format).")
    args = parser.parse_args(argv)

    data: dict = {}
    if args.fields:
        try:
            with open(args.fields, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        except (OSError, ValueError) as exc:
            print(f"error: could not read fields {args.fields}: {exc}", file=sys.stderr)
            return 1
        if not isinstance(data, dict):
            print(f"error: --fields {args.fields} must be a JSON object", file=sys.stderr)
            return 1

    inputs = ProfileInputs(
        name=args.name,
        company_name=data.get("company_name", ""),
        address=data.get("address", ""),
        logo=data.get("logo"),
        tree=data.get("tree", ""),
        letterhead=data.get("letterhead", ""),
        compliance_label=data.get("compliance_label", ""),
        spec_note=data.get("spec_note", ""),
        naming=data.get("naming"),
        estimating_format=data.get("estimating_format", ""),
    )
    try:
        files = build_profile_dir(inputs)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    target = Path(args.directory)
    try:
        target.mkdir(parents=True, exist_ok=True)
        for fname, content in files.items():
            (target / fname).write_text(content, encoding="utf-8")
    except OSError as exc:
        print(f"error: could not write profile to {target}: {exc}", file=sys.stderr)
        return 1

    print(f"wrote profile to {target} — add it to ESTIMATING_PROFILES to activate")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
