"""Release version-consistency gate.

Reads the pushed tag from $GITHUB_REF_NAME (e.g. "v0.1.1"), strips a leading "v",
and asserts every committed version string equals it: packages/estimating-tools/
pyproject.toml and each plugins/*/.claude-plugin/plugin.json. bimforge is released
from BrandonLewis/BIMForge on its own line and is not checked here.
Exits 0 on a full
match (prints "version consistency OK: all == <ver>"); else exits 1 and lists every
mismatched file. The committed versions are authoritative — the tag is a pointer.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    tag = os.environ.get("GITHUB_REF_NAME", "")
    if not tag:
        print("GITHUB_REF_NAME is not set (expected the pushed tag, e.g. v0.1.1)", file=sys.stderr)
        return 2
    want = tag[1:] if tag.startswith("v") else tag

    errs = []
    for rel in ("packages/estimating-tools/pyproject.toml",):
        pp = (ROOT / rel).read_text()
        m = re.search(r'^version\s*=\s*"([^"]+)"', pp, re.M)
        if m is None:
            errs.append(f'{rel}: no `version = "..."` line found')
        elif m.group(1) != want:
            errs.append(f"{rel}: {m.group(1)!r} != {want!r}")

    for f in sorted(glob.glob(str(ROOT / "plugins/*/.claude-plugin/plugin.json"))):
        rel = Path(f).relative_to(ROOT)
        try:
            v = json.loads(Path(f).read_text()).get("version")
        except (json.JSONDecodeError, OSError) as e:
            errs.append(f"{rel}: could not parse ({e})")
            continue
        if v != want:
            errs.append(f"{rel}: {v!r} != {want!r}")

    if errs:
        print("VERSION MISMATCH (tag vs committed):")
        for e in errs:
            print(" -", e)
        return 1
    print(f"version consistency OK: all == {want}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
