"""Build the deployable /excel/addons/ tree for Estimate Navigator.

    python excel-addin/scripts/package.py --version 1.0.0 --out dist/excel-addons

Lays out:
  OUT/navigator/<version>/{panes,core}/   the versioned static build
  OUT/navigator/sample.xlsx               a fieldbook workbook built from the pack's example
  OUT/brand.json, OUT/assets/             the generic brand
  OUT/manifest.xml                        the generic manifest for this version
  OUT/{privacy,support,terms}.html        the store pages
The pane fetches ../../sample.xlsx and ../../../brand.json relative to
navigator/<version>/panes/taskpane.html, which is why those two sit where they do.
Upload OUT's contents to https://anvilrockroad.com/excel/addons/, keeping older
navigator/<version>/ folders. Client folders (OUT/<slug>/) are made with est-addin
and live only in the site deployment.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ADDIN = Path(__file__).resolve().parents[1]
REPO = ADDIN.parent
BASE = "https://anvilrockroad.com/excel/addons/"
PAGES = ("privacy", "support", "terms")
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")  # fullmatch: no trailing newline, ASCII digits only

# Use this checkout's packages, not whatever estimating_tools is installed.
for _pkg in ("estimating-tools", "bimforge"):
    sys.path.insert(0, str(REPO / "packages" / _pkg))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", required=True, help="three numbers, e.g. 1.0.0")
    ap.add_argument("--out", required=True, help="output folder, mirroring /excel/addons/")
    args = ap.parse_args(argv)
    if not _VERSION.fullmatch(args.version):
        print("error: --version must be three numbers, e.g. 1.0.0", file=sys.stderr)
        return 1

    from estimating_tools.addin import manifest as AM
    from estimating_tools.estimate_spec import build as B
    from estimating_tools.estimate_spec.format_pack import BUNDLED

    out = Path(args.out)
    build = out / "navigator" / args.version
    if build.exists():
        shutil.rmtree(build)
    for part in ("panes", "core"):
        shutil.copytree(ADDIN / part, build / part)
    shutil.copy(ADDIN / "brand" / "brand.json", out / "brand.json")
    if (out / "assets").exists():
        shutil.rmtree(out / "assets")  # a re-run must not keep assets the brand has dropped
    shutil.copytree(ADDIN / "brand" / "assets", out / "assets")
    for page in PAGES:
        shutil.copy(ADDIN / "site" / f"{page}.html", out / f"{page}.html")
    brand = json.loads((ADDIN / "brand" / "brand.json").read_text(encoding="utf-8"))
    (out / "manifest.xml").write_text(
        AM.render_manifest(brand, app_url=f"{BASE}navigator/{args.version}/", version=f"{args.version}.0"),
        encoding="utf-8", newline="\n")
    # Built directly, not through the CLI, so it carries no profile brand.
    example = BUNDLED / "examples" / "demo-pipeline.estimate.yaml"
    B.build(str(example), str(out / "navigator" / "sample.xlsx"))
    print("WROTE:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
