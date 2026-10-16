"""Build a package's wheel into a plugin's dist/, or --check it for drift.

The marketplace copies only the plugin subtree, so every wheel a plugin needs
must be committed inside the plugin. Wheels track main: any PR changing a
source package must regenerate its bundled copies (CI runs --check per
(plugin, package) pair). A dist/ may hold wheels from several packages; the
check only compares wheels whose name prefix matches the built package.

Usage:
  python scripts/build_plugin_wheel.py plugins/estimating-core                                # estimating_tools wheel
  python scripts/build_plugin_wheel.py plugins/estimating-core --package packages/bimforge      # bimforge wheel
  python scripts/build_plugin_wheel.py plugins/calc-bim --package packages/bimforge --check     # CI drift gate
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# dist-info members that vary between builds without a semantic change.
_VOLATILE_DIST_INFO = {"RECORD", "WHEEL"}
_METADATA_KEEP = ("Name:", "Version:", "Requires-Python:", "Requires-Dist:", "Provides-Extra:")


def build_wheel(outdir: Path, package_dir: Path) -> Path:
    # A stale build/ is a packaging input: setuptools' build_py reuses
    # build/lib, so a module deleted from the source tree kept shipping in the
    # wheel as long as its copy sat there (the removed calculators did, for a
    # release). Build from a clean directory every time.
    shutil.rmtree(package_dir / "build", ignore_errors=True)
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir), str(package_dir)],
        check=True,
    )
    wheels = sorted(outdir.glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected exactly one built wheel in {outdir}, found {len(wheels)}")
    return wheels[0]


def wheel_contents(path: Path) -> dict[str, bytes]:
    """Semantic contents: package files LF-normalized + normalized dist-info."""
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as zf:

        def read(name: str) -> bytes:
            # line endings vary by build platform (git autocrlf); compare LF-normalized
            return zf.read(name).replace(b"\r\n", b"\n")

        for name in zf.namelist():
            if name.endswith("/"):
                # zip directory entries are empty placeholders; whether they
                # appear at all varies by build toolchain
                continue
            top, _, rest = name.partition("/")
            if rest and top.endswith(".dist-info"):
                base = rest.split("/")[-1]
                if base in _VOLATILE_DIST_INFO:
                    continue
                if base == "METADATA":
                    keep = sorted(
                        line
                        for line in read(name).decode("utf-8").splitlines()
                        if line.startswith(_METADATA_KEEP)
                    )
                    out["dist-info/METADATA"] = "\n".join(keep).encode("utf-8")
                else:
                    out[f"dist-info/{base}"] = read(name)
            else:
                out[name] = read(name)
    return out


def diff_wheels(a: Path, b: Path) -> list[str]:
    ca, cb = wheel_contents(a), wheel_contents(b)
    diffs = []
    for name in sorted(set(ca) | set(cb)):
        if name not in ca:
            diffs.append(f"only in {b.name}: {name}")
        elif name not in cb:
            diffs.append(f"only in {a.name}: {name}")
        elif ca[name] != cb[name]:
            diffs.append(f"differs: {name}")
    return diffs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plugin", help="plugin directory to receive the wheel, e.g. plugins/estimating-core")
    ap.add_argument("--package", default="packages/estimating-tools",
                    help="package directory to build (default: packages/estimating-tools)")
    ap.add_argument("--check", action="store_true", help="verify the committed wheel matches a fresh build")
    args = ap.parse_args(argv)

    dist = ROOT / args.plugin / "dist"
    with tempfile.TemporaryDirectory() as td:
        fresh = build_wheel(Path(td), ROOT / args.package)
        prefix = fresh.name.split("-")[0]
        committed = sorted(dist.glob(f"{prefix}-*.whl"))
        if args.check:
            if len(committed) != 1:
                print(f"DRIFT: expected exactly one committed {prefix}-*.whl in {dist}, found {len(committed)}")
                return 1
            diffs = diff_wheels(committed[0], fresh)
            if committed[0].name != fresh.name:
                diffs.insert(0, f"filename: committed {committed[0].name} != fresh {fresh.name}")
            if diffs:
                print(f"DRIFT: committed wheel is stale ({len(diffs)} differences):")
                for d in diffs:
                    print(f"  {d}")
                print(f"fix: python scripts/build_plugin_wheel.py {args.plugin} --package {args.package}")
                return 1
            print(f"wheel up to date: {committed[0].name}")
            return 0
        dist.mkdir(parents=True, exist_ok=True)
        for old in committed:
            old.unlink()
        target = dist / fresh.name
        target.write_bytes(fresh.read_bytes())
        print(f"wrote {target.relative_to(ROOT)}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
