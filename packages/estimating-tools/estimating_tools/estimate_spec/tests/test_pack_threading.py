"""scaffold / artifact / summarize read the FormatPack they are given."""
from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
import yaml

from estimating_tools.estimate_spec import artifact, scaffold, summarize
from estimating_tools.estimate_spec import format_pack as fp

ES = Path(fp.__file__).resolve().parent
LEGACY_DIR = ES / "tests" / "fixtures" / "packs" / "legacy_demo"


def _copy_pack(tmp_path: Path, *, trades=None, units=None) -> fp.FormatPack:
    root = tmp_path / "copy"
    shutil.copytree(LEGACY_DIR, root, ignore=shutil.ignore_patterns(
        "*.py", "__pycache__", "tests", "examples", "packs"))
    text = (root / "format.yaml").read_text().replace("name: legacy_demo", "name: copy")
    assert "name: copy" in text            # the copy is its own pack, not the fixture by name
    (root / "format.yaml").write_text(text)
    if trades is not None:
        vocab = yaml.safe_load((root / "vocabulary.yaml").read_text())
        vocab["trades"] = list(trades)
        (root / "vocabulary.yaml").write_text(yaml.safe_dump(vocab, sort_keys=False))
    if units is not None:
        (root / "units.yaml").write_text(yaml.safe_dump(units))
    return fp.load_pack(root)


def _schema_with_trade(extra: str) -> list:
    return list(fp.load_pack(LEGACY_DIR).vocabulary["trades"]) + [extra]


FORMAT_FILES = {"units.yaml", "tokens.yaml", "recipes.yaml", "vocabulary.yaml", "seed.yaml",
                "skeleton.schema.json"}


def test_no_module_reads_a_format_file_behind_the_packs_back():
    """Only format_pack.py may name a format file. An exact-equality check on
    string constants: docstrings and comments that mention a file never match."""
    import ast

    offenders = []
    for py in sorted(ES.glob("*.py")):
        if py.name == "format_pack.py":
            continue
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and node.value in FORMAT_FILES:
                offenders.append(f"{py.name}:{node.lineno}")
    assert offenders == []


def test_artifact_trades_come_from_the_pack(tmp_path):
    pack = _copy_pack(tmp_path, trades=_schema_with_trade("ZZTOP"))
    assert "ZZTOP" in artifact._valid_trades(pack)
    assert "ZZTOP" not in artifact._valid_trades()


def test_artifact_schema_cache_is_per_pack(tmp_path):
    pack = _copy_pack(tmp_path, trades=_schema_with_trade("ZZTOP"))
    a = artifact._item_schema(pack)
    b = artifact._item_schema()
    assert a is not b
    assert artifact._item_schema(pack) is a      # still cached


def test_summarize_defaults_come_from_the_pack(tmp_path, monkeypatch):
    """`_units_default` scans every unit's params for the field name, so any
    unit can carry the override — it need not be a unit the reference pack
    happens to name. The omitted-pack fallback reads `bundled_pack()`,
    proven generically by redirecting it (no test may depend on which pack
    is bundled) rather than asserting today's specific bundled default."""
    units = {"units": copy.deepcopy(fp.load_pack(LEGACY_DIR).units)}
    units["units"]["rates"]["params"]["tax_rate"] = {"type": "number", "default": 0.5}
    pack = _copy_pack(tmp_path, units=units)
    assert summarize._units_default("tax_rate", 0.0, pack) == 0.5

    monkeypatch.setattr(fp, "bundled_pack", lambda: pack)
    assert summarize._units_default("tax_rate", 0.0) == pytest.approx(0.5)


def _spec_with_a_retargeted_crew_row() -> dict:
    """The demo pack's own example, with its first labor crew row retargeted
    to book an unknown trade (ZZTOP), not present in the pack's vocabulary."""
    spec = yaml.safe_load((LEGACY_DIR / "examples" / "demo-pipeline.estimate.yaml")
                          .read_text(encoding="utf-8"))
    for item in spec["items"]:
        for block in item.get("labor") or []:
            if block.get("crew"):
                block["crew"][0]["trade"] = "ZZTOP"
                spec["rate_table"].append({"trade": "ZZTOP", "rate": 1})
                return spec
    raise AssertionError("the demo pack's example carries no labor crew row")


def test_validate_spec_uses_the_pack_schema(tmp_path):
    demo = fp.load_pack(LEGACY_DIR)
    spec = _spec_with_a_retargeted_crew_row()
    with pytest.raises(ValueError, match="schema violation"):
        scaffold.validate_spec(spec, pack=demo)
    scaffold.validate_spec(spec, pack=_copy_pack(tmp_path, trades=_schema_with_trade("ZZTOP")))
