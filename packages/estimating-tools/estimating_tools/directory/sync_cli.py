"""dir-sync — diff a local canonical directory against a BM export.

  plan  local.json remote.json -> sync-plan markdown on stdout (--json for
        the raw plan). Both files are CanonicalDirectory-shaped:
        {"organizations": [{..., "contacts": [...]}]}.

Deterministic; MCP traffic (the export, the apply) stays at the
sync-directory skill layer."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load(path: str):
    p = Path(path)
    if not p.is_file():
        print(f"no such file: {p}", file=sys.stderr)
        return None
    from estimating_tools.directory.model import CanonicalDirectory
    try:
        return CanonicalDirectory.from_dict(
            json.loads(p.read_text(encoding="utf-8")))
    except (ValueError, TypeError) as exc:
        print(f"invalid directory JSON in {p}: {exc}", file=sys.stderr)
        return None


def cmd_plan(args) -> int:
    from estimating_tools.directory.diff import build_sync_plan, render_sync_plan
    local = _load(args.local)
    if local is None:
        return 1
    remote = _load(args.remote)
    if remote is None:
        return 1
    plan = build_sync_plan(local, remote)
    print(json.dumps(plan, indent=2) if args.json else render_sync_plan(plan))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="dir-sync", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", help="local + remote JSON -> sync plan")
    p.add_argument("local")
    p.add_argument("remote")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
