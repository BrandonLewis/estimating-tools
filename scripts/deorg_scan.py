"""Provenance scan — CI gate (`.github/workflows/ci.yml`).

Refuses to let three things into the tree, in text files and inside the
bundled wheels alike:

* an employer bid number (`B2217`, `b2235-2026-09-16`): fixtures cite public
  sources or derive their quantities in-repo, never a real pursuit;
* a developer-machine path (`/home/<user>/`, `/Users/`, `C:/Users`);
* a credential-shaped string (private-key headers, JWTs, bearer / API tokens).

Project-specific tokens (organisation, site and people names) are supplied by
the maintainer through the ``DEORG_EXTRA_PATTERNS`` environment variable — a
``|``-joined, case-insensitive regex, held as a repository secret so the list
never lands in the tree. Without it the three classes above still run.

    python scripts/deorg_scan.py          # exit 1 on any hit
"""
from __future__ import annotations

import csv
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve().relative_to(ROOT).as_posix()


def _word(token: str) -> str:
    # boundaries that treat `_` and `-` as separators (unlike \b)
    return rf"(?<![a-z0-9]){token}(?![a-z0-9])"


BIDS = _word(r"b2[0-9]{3}")
PATHS = r"/home/[a-z][a-z0-9_-]*/|/Users/|c:/users"
# The JWT prefix is case-sensitive on purpose: base64 hashes contain "eYJ"
# often enough that a case-insensitive match false-positives on every RECORD.
SECRETS = (
    r"BEGIN [A-Z ]*PRIVATE KEY|(?-i:eyJ[A-Za-z0-9_-]{10,})|"
    r"Bearer [A-Za-z0-9._-]{20,}|ApiKey [A-Za-z0-9._-]{16,}"
)


def pattern() -> re.Pattern[str]:
    parts = [BIDS, PATHS, SECRETS]
    extra = os.environ.get("DEORG_EXTRA_PATTERNS", "").strip()
    if extra:
        parts.append(extra)
    return re.compile("|".join(parts), re.I)


def tracked_files() -> list[Path]:
    try:
        # tracked AND untracked-but-not-ignored: a fresh export into an empty
        # clone has nothing staged yet, and the gate must still see it
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others",
                              "--exclude-standard"], cwd=ROOT, check=True,
                             capture_output=True).stdout
        names = [n for n in out.decode("utf-8").split("\0") if n]
    except (OSError, subprocess.CalledProcessError):
        names = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                 if p.is_file() and ".git" not in p.parts]
    return [ROOT / n for n in names if n != SELF]


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data


def scan_text(data: bytes, location: str, rx: re.Pattern[str]) -> list[str]:
    hits = []
    for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        if rx.search(line):
            hits.append(f"{location}:{n}: {line.strip()[:160]}")
    return hits


def _record_paths(data: bytes) -> bytes:
    """A wheel ``RECORD`` reduced to its path column.

    The sha256 column is machine-generated base64 that randomly spells short
    tokens, so scanning whole lines false-positives on files that never
    mention anything. Only the path, where a leaked absolute path or a
    revealingly named file would show, is scanned. A line the CSV reader
    cannot split is kept whole, so over-trimming never hides a real leak.
    """
    out = []
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            row = next(csv.reader([line]))
        except (csv.Error, StopIteration):
            row = [line]
        out.append(row[0] if len(row) >= 3 else line)
    return "\n".join(out).encode("utf-8")


def scan(files: list[Path], rx: re.Pattern[str]) -> list[str]:
    hits = []
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        if f.suffix == ".whl":
            # a wheel is a zip: scan its text members, the code customers install
            with zipfile.ZipFile(f) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    data = zf.read(info)
                    if _is_binary(data):
                        continue
                    if info.filename.endswith(".dist-info/RECORD"):
                        data = _record_paths(data)
                    hits += scan_text(data, f"{rel}!{info.filename}", rx)
            continue
        data = f.read_bytes()
        if _is_binary(data):
            continue
        hits += scan_text(data, rel, rx)
    return hits


def main() -> int:
    hits = scan(tracked_files(), pattern())
    if hits:
        print(">>> provenance scan found forbidden content:")
        for h in hits:
            print("  ", h)
        return 1
    extra = "with" if os.environ.get("DEORG_EXTRA_PATTERNS") else "without"
    print(f"provenance scan clean ({extra} DEORG_EXTRA_PATTERNS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
