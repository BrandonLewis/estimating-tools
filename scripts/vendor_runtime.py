#!/usr/bin/env python3
"""Vendor scripts/plugin_runtime.py into each plugin's scripts/, or --check it.

WHY A COPY AND NOT AN IMPORT. Each plugin is distributed as its own subtree:
the marketplace installs `plugins/estimating-core/` alone, at
`~/.claude/plugins/cache/estimating-platform/estimating-core/<version>/`. A
plugin therefore cannot reference a sibling's files, and cannot reference the
repo root's `scripts/` either -- neither exists on an installed machine. The
module has to physically sit beside the `ensure_tools.py` that imports it.

So the repo root's copy is the source of truth and the per-plugin copies are
generated, guarded the same way the bundled wheels and the OpenWorker skill port
are: CI runs `--check`, which fails the build when a copy is stale.

Examples:
    python scripts/vendor_runtime.py            # regenerate the copies
    python scripts/vendor_runtime.py --check    # CI drift gate, writes nothing
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "scripts" / "plugin_runtime.py"

#: Both plugins own a SessionStart hook and bundle wheels. (The calc-lighting,
#: calc-thermal and calc-ies calculators, which had neither, were retired 2026-10.)
PLUGINS = ("calc-bim", "estimating-core")


def targets() -> list:
    return [REPO_ROOT / "plugins" / p / "scripts" / "plugin_runtime.py"
            for p in PLUGINS]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the vendored copies match the source; write nothing")
    args = ap.parse_args(argv)

    want = SOURCE.read_bytes()
    stale = []
    for dest in targets():
        rel = dest.relative_to(REPO_ROOT)
        if args.check:
            if not dest.is_file() or dest.read_bytes() != want:
                stale.append(str(rel))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE, dest)
        print(f"vendored {rel}")

    if args.check:
        if stale:
            print("DRIFT: vendored plugin_runtime.py is stale in: "
                  + ", ".join(stale), file=sys.stderr)
            print("Run: python scripts/vendor_runtime.py", file=sys.stderr)
            return 1
        print(f"{len(PLUGINS)} vendored plugin_runtime.py copies are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
