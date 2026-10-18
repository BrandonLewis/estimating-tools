"""The layout loop is driven by recipes.yaml and names no unit."""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest
import yaml

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import format_pack as fp

ES = Path(fp.__file__).resolve().parent
LEGACY_DIR = ES / "tests" / "fixtures" / "packs" / "legacy_demo"
SAMPLE = LEGACY_DIR / "examples" / "demo-pipeline.estimate.yaml"


def _config():
    return yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))


def test_build_py_names_no_unit_and_no_format_literal():
    """No unit name of any pack -- the bundled one, the legacy_demo fixture,
    the alt fixture -- appears as a literal in build.py."""
    units = set()
    for pack in (fp.bundled_pack(), fp.load_pack(LEGACY_DIR),
                 fp.load_pack(ES / "tests" / "fixtures" / "packs" / "alt")):
        units |= set(pack.units)
    banned = units | {"Summary", "LUMBER", "HARDWARE", "$G$2", "$H$2",
                      "takeoff_variants", "item_header", "rate_table"}
    tree = ast.parse((ES / "build.py").read_text(encoding="utf-8"))
    found = sorted({n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and n.value in banned})
    assert found == []


def _copy_pack(tmp_path: Path, mutate) -> fp.FormatPack:
    root = tmp_path / "copy"
    shutil.copytree(LEGACY_DIR, root, ignore=shutil.ignore_patterns(
        "*.py", "__pycache__", "tests", "examples", "packs"))
    doc = yaml.safe_load((root / "recipes.yaml").read_text())
    mutate(doc)
    (root / "recipes.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    return fp.load_pack(root)


def test_a_rate_table_can_live_on_its_own_sheet(tmp_path):
    def mutate(doc):
        for entry in doc["recipes"]["setup"]["units"]:
            if entry["unit"] == "rates":
                entry["sheet"] = "Rates"
    config = _config()
    wb = B.generate(config, _copy_pack(tmp_path, mutate))
    assert "Rates" in wb.sheetnames
    # last populated rate-table row, derived from the config's own rate_table
    # length rather than a hardcoded coordinate.
    last_row = 1 + len(config["rate_table"])
    assert wb["Rates"][f"B{last_row}"].value is not None
    formulas = [c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row
                if isinstance(c.value, str) and "VLOOKUP" in c.value]
    assert formulas and all("'Rates'!" in f for f in formulas)


def test_the_cover_comes_from_the_recipe(tmp_path):
    default_cover = fp.load_pack(LEGACY_DIR).recipes["recipes"]["cover"]["sheet_name"]

    def mutate(doc):
        doc["recipes"]["cover"]["sheet_name"] = "Bid"
    wb = B.generate(_config(), _copy_pack(tmp_path, mutate))
    assert "Bid" in wb.sheetnames and default_cover not in wb.sheetnames


def test_a_bad_recipe_is_refused_before_rendering(tmp_path):
    def mutate(doc):
        doc["recipes"]["setup"]["units"].append({"unit": "no_such_unit"})
    # Refused when the pack loads (B1), before any render can start.
    with pytest.raises(fp.FormatPackError, match="no_such_unit"):
        _copy_pack(tmp_path, mutate)
