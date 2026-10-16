"""Materialize a project folder tree from a profile's folder_conventions.

Minimal by design: create a folder tree from the resolved org profile. Not a
project-lifecycle CLI.
"""
from __future__ import annotations

import argparse
import re
from importlib import resources
from pathlib import Path

import yaml

from estimating_tools.docgen.yaml_tree import build_tree, build_tree_from_spec
from estimating_tools.profiles.loader import load
from estimating_tools.profiles.model import Profile


def materialize_tree(profile: Profile, base: Path, ctx: dict | None = None) -> bool:
    """Build the profile's folder tree under `base`. Returns False (no-op) when
    the profile has no folder_conventions.tree."""
    tree_ref = profile.section("folder_conventions").get("tree")
    if not tree_ref:
        return False
    yaml_text = Path(tree_ref).read_text()
    # Support both raw-list YAML (legacy) and folders:-keyed YAML.
    parsed = yaml.safe_load(yaml_text)
    if not parsed:
        return True  # empty tree file — nothing to create
    if isinstance(parsed, list):
        build_tree_from_spec(Path(base), parsed, ctx or {})
    elif isinstance(parsed, dict):
        build_tree(Path(base), yaml_text, ctx or {})
    else:
        raise ValueError(
            f"folder_conventions tree must be a YAML list or mapping, got {type(parsed).__name__}"
        )
    return True


def materialize_layout(base: Path, layout: str, ctx: dict | None = None) -> None:
    """Build a packaged canonical layout (trees/<layout>-layout.yaml) under base."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", layout):
        raise ValueError(f"unknown layout {layout!r}")
    ref = resources.files("estimating_tools.profiles") / "trees" / f"{layout}-layout.yaml"
    try:
        yaml_text = ref.read_text()
    except FileNotFoundError:
        raise ValueError(f"unknown layout {layout!r}") from None
    build_tree(Path(base), yaml_text, ctx or {})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="est-scaffold",
                                     description="Create a project folder tree from the active profile.")
    parser.add_argument("name", help="Project name (becomes the project directory).")
    parser.add_argument("--parent", default=".", help="Parent directory (default: cwd).")
    parser.add_argument("--layout", default=None,
                        help="Use a packaged canonical layout (e.g. 'work-project') instead of the profile tree.")
    args = parser.parse_args(argv)

    base = Path(args.parent) / args.name
    base.mkdir(parents=True, exist_ok=True)
    if args.layout:
        try:
            materialize_layout(base, args.layout, {"name": args.name})
        except ValueError as exc:
            print(exc)
            return 1
        print(f"scaffolded {base} with the '{args.layout}' canonical layout")
        return 0
    built = materialize_tree(load(), base, {"name": args.name})
    if built:
        print(f"scaffolded {base} from the active profile")
    else:
        print(f"created {base} (no folder_conventions in the active profile)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
