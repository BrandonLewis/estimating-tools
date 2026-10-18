"""Repo-level guards for excel-addin/: committed generated files match their generators."""
from __future__ import annotations

import json
from pathlib import Path

from estimating_tools.addin import brand as AB
from estimating_tools.profiles.model import Profile

ROOT = Path(__file__).resolve().parents[1]
ADDIN = ROOT / "excel-addin"


def test_the_committed_generic_brand_is_what_the_generator_writes(tmp_path):
    committed = json.loads((ADDIN / "brand" / "brand.json").read_text(encoding="utf-8"))
    assert committed == AB.brand_from_profile(Profile(data={}), tmp_path)


def test_the_generic_brand_satisfies_its_schema():
    import jsonschema
    schema = json.loads((ADDIN / "brand" / "brand.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(json.loads((ADDIN / "brand" / "brand.json").read_text(encoding="utf-8")), schema)


def test_the_generic_icons_exist():
    for n in (*AB.ICON_SIZES, 300):
        assert (ADDIN / "brand" / "assets" / f"icon-{n}.png").stat().st_size > 0


GENERIC_APP_URL = "https://anvilrockroad.com/excel/addons/navigator/1.0.0/"
GENERIC_VERSION = "1.0.0.0"


def test_the_committed_generic_manifest_is_what_the_generator_writes():
    from estimating_tools.addin import manifest as AM
    committed = (ADDIN / "manifests" / "estimate-navigator.xml").read_text(encoding="utf-8")
    assert committed == AM.render_manifest(AB.GENERIC, app_url=GENERIC_APP_URL, version=GENERIC_VERSION)


def test_package_builds_a_deployable_tree(tmp_path):
    import re
    import subprocess
    import sys
    from urllib.parse import urljoin

    from openpyxl import load_workbook
    out = tmp_path / "addons"
    r = subprocess.run([sys.executable, str(ADDIN / "scripts" / "package.py"), "--version", "1.2.3", "--out", str(out)],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    build = out / "navigator" / "1.2.3"
    assert (build / "panes" / "taskpane.html").exists() and (build / "core" / "stamp.js").exists()
    for part in ("panes", "core"):
        assert _files(build / part) == _files(ADDIN / part), part
    assert (out / "brand.json").exists() and (out / "assets" / "icon-80.png").exists()
    manifest = (out / "manifest.xml").read_text(encoding="utf-8")
    assert "navigator/1.2.3/panes/taskpane.html" in manifest and "<Version>1.2.3.0</Version>" in manifest
    for page in ("privacy", "support", "terms"):
        assert (out / f"{page}.html").exists()
    wb = load_workbook(out / "navigator" / "sample.xlsx")
    assert "estimate_layout" in {p.name for p in wb.custom_doc_props.props}
    assert "est.layout" in wb.defined_names
    # The pane fetches these relative to its own URL; each must land on a packaged file.
    base = "https://h/excel/addons/"
    pane = base + "navigator/1.2.3/panes/taskpane.html"
    sample = re.search(r'const SAMPLE_URL = "([^"]+)"', (ADDIN / "panes" / "main.js").read_text(encoding="utf-8"))
    generic = re.search(r':\s*"([^"]*brand\.json)"', (ADDIN / "core" / "brand.js").read_text(encoding="utf-8"))
    assert sample and generic, "the pane's sample or generic brand path moved"
    for rel in (sample.group(1), generic.group(1)):
        url = urljoin(pane, rel)
        assert url.startswith(base), url
        assert (out / url[len(base):]).is_file(), url


def _files(folder):
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


def _package(version, out):
    import subprocess
    import sys
    return subprocess.run([sys.executable, str(ADDIN / "scripts" / "package.py"), "--version", version, "--out", str(out)],
                          cwd=ROOT, capture_output=True, text=True)


def test_package_refuses_a_bad_version(tmp_path):
    # "1.0.0\n" slips past re.match with $; "١" (Arabic-Indic one) slips past \d.
    for bad in ("1.2", "1.0.0\n", "1.0.0.0", "1.١.0"):
        r = _package(bad, tmp_path / "out")
        assert r.returncode != 0 and "three numbers" in r.stderr, repr(bad)
        assert not (tmp_path / "out").exists(), repr(bad)


def test_package_rerun_drops_stale_assets(tmp_path):
    out = tmp_path / "addons"
    (out / "assets").mkdir(parents=True)
    (out / "assets" / "stale.png").write_bytes(b"old")
    r = _package("1.2.3", out)
    assert r.returncode == 0, r.stderr
    assert _files(out / "assets") == _files(ADDIN / "brand" / "assets")
