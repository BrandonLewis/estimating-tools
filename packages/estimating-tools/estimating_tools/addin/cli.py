"""est-addin: brand files and XML manifests for the Estimate Navigator Excel add-in."""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import yaml

from estimating_tools.addin import brand as AB
from estimating_tools.addin import manifest as AM


def _profile(path):
    from estimating_tools.profiles.loader import load
    from estimating_tools.profiles.model import Profile
    return load([Path(path)]) if path else Profile(data={})


def cmd_brand(args) -> int:
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            profile = _profile(args.profile)
    except yaml.YAMLError as exc:
        print(f"error: invalid YAML in the profile: {exc}", file=sys.stderr)
        return 1
    for w in caught:
        message = str(w.message)
        if "field 'brand' invalid" in message:
            print(f"error: the profile's brand: section is invalid: {message}", file=sys.stderr)
            return 1
    if args.profile and not profile.section("brand"):
        print("warning: profile has no brand: section; wrote the generic brand", file=sys.stderr)
    brand = AB.brand_from_profile(profile, Path(args.out))
    print("WROTE:", AB.write_brand(brand, Path(args.out)))
    return 0


def cmd_manifest(args) -> int:
    brand = json.loads(Path(args.brand).read_text(encoding="utf-8"))
    text = AM.render_manifest(brand, app_url=args.app_url, version=args.version, slug=args.slug)
    if args.check:
        if not args.output:
            raise AM.ManifestError("--check needs -o/--output")
        current = Path(args.output).read_text(encoding="utf-8") if Path(args.output).exists() else None
        if current != text:
            print(f"drift in: {args.output}", file=sys.stderr)
            return 1
        return 0
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8", newline="\n")
        print("WROTE:", args.output)
    else:
        sys.stdout.write(text)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="est-addin", description="Brand files and manifests for the Estimate Navigator Excel add-in.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brand", help="write brand.json (and copy its assets) from an org profile")
    b.add_argument("--profile", help="org profile directory (default: the generic brand)")
    b.add_argument("-o", "--out", required=True, help="output directory for brand.json and assets/")
    b.set_defaults(func=cmd_brand)
    m = sub.add_parser("manifest", help="write the add-in's XML manifest for one brand")
    m.add_argument("--brand", required=True, help="brand.json")
    m.add_argument("--app-url", required=True,
                   help="https URL of the versioned navigator build folder (the brand folder, "
                        "where brand.json/assets/ and the manifest's URLs live, is two levels above it)")
    m.add_argument("--version", required=True, help="manifest version, four numbers (1.0.0.0)")
    m.add_argument("--slug", help="brand folder name the pane loads brand.json from (omit for generic)")
    m.add_argument("-o", "--output", help="output file (default: stdout)")
    m.add_argument("--check", action="store_true", help="exit 1 if --output differs from what would be written")
    m.set_defaults(func=cmd_manifest)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (AB.BrandError, AM.ManifestError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
