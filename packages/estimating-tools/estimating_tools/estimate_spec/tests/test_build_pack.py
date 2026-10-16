"""build.py renders from a FormatPack."""
from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
import yaml

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import format_pack as fp
from estimating_tools.estimate_spec.cli import main

ES = Path(fp.__file__).resolve().parent
DEMO_DIR = ES / "packs" / "demo"
SAMPLE = DEMO_DIR / "examples" / "demo-pipeline.estimate.yaml"


def _config():
    return yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))


def _cells(wb):
    return {(ws.title, c.coordinate): (c.value, c.fill.fgColor.rgb)
            for ws in wb.worksheets for row in ws.iter_rows() for c in row
            if c.value is not None}


def _demo_pack() -> fp.FormatPack:
    return fp.load_pack(DEMO_DIR)


def _copy_pack(tmp_path: Path) -> Path:
    root = tmp_path / "copy"
    shutil.copytree(DEMO_DIR, root, ignore=shutil.ignore_patterns(
        "*.py", "__pycache__", "tests", "examples", "packs"))
    text = (root / "format.yaml").read_text().replace("name: demo", "name: copy")
    (root / "format.yaml").write_text(text)
    return root


def test_omitting_pack_uses_the_bundled_pack(monkeypatch):
    """`generate(config)` with no `pack` falls back to `bundled_pack()` —
    proven generically by redirecting the bundled pack to the demo pack
    rather than depending on whichever pack format_pack.py bundles today."""
    demo = _demo_pack()
    monkeypatch.setattr(fp, "bundled_pack", lambda: demo)
    assert _cells(B.generate(_config())) == _cells(B.generate(_config(), demo))


def test_the_pack_actually_drives_the_render(tmp_path):
    # item_identity (the item_header row-2 strip) is unconditional, so it
    # actually exercises "the pack drives the render" regardless of which
    # optional sections the sample spec happens to use.
    root = _copy_pack(tmp_path)
    tokens = yaml.safe_load((root / "tokens.yaml").read_text())
    tokens["fills"]["item_identity"] = "123456"
    (root / "tokens.yaml").write_text(yaml.safe_dump(tokens))
    fills = {v[1] for v in _cells(B.generate(_config(), fp.load_pack(root))).values()}
    assert "FF123456" in fills


def test_rendering_does_not_mutate_the_cached_pack():
    pack = _demo_pack()
    before = copy.deepcopy((pack.units, pack.tokens, pack.recipes, pack.schema))
    B.generate(_config(), pack)
    B.generate(_config(), pack)
    assert (pack.units, pack.tokens, pack.recipes, pack.schema) == before


def test_the_workbook_names_its_format():
    wb = B.generate(_config(), _demo_pack())
    props = {p.name: p.value for p in wb.custom_doc_props.props}
    assert props["estimate_format"] == "demo 1"


def test_the_stamp_is_suppressible():
    wb = B.generate(_config(), _demo_pack(), stamp=False)
    assert "estimate_format" not in {p.name for p in wb.custom_doc_props.props}


def test_cli_build_accepts_a_format(tmp_path):
    out = tmp_path / "out.xlsx"
    rc = main(["build", str(SAMPLE), "-o", str(out), "--format", str(_copy_pack(tmp_path))])
    assert rc == 0 and out.is_file()


def test_cli_build_refuses_a_bad_format(tmp_path, capsys):
    rc = main(["build", str(SAMPLE), "-o", str(tmp_path / "o.xlsx"),
               "--format", str(tmp_path / "nope")])
    assert rc == 2
    assert "format pack error" in capsys.readouterr().err
    assert not (tmp_path / "o.xlsx").exists()


# ---- cmd_build's error surface ----------------------------------------------
# cmd_build had none: every one of these came out as a traceback, while
# cmd_cip and cmd_summarize next to it reported and exited.

def test_cli_build_reports_a_missing_config(tmp_path, capsys):
    rc = main(["build", str(tmp_path / "nope.estimate.yaml"),
               "-o", str(tmp_path / "o.xlsx")])
    assert rc == 1
    assert "no such file" in capsys.readouterr().err


def test_cli_build_reports_unparseable_yaml(tmp_path, capsys):
    bad = tmp_path / "bad.estimate.yaml"
    bad.write_text("items: [\n  - unterminated\n", encoding="utf-8")
    rc = main(["build", str(bad), "-o", str(tmp_path / "o.xlsx")])
    assert rc == 1
    assert "invalid YAML" in capsys.readouterr().err


def test_cli_build_reports_a_spec_the_pack_refuses(tmp_path, capsys):
    bad = tmp_path / "bad.estimate.yaml"
    bad.write_text("items:\n  - recipe: no_such_recipe\n    sheet: S\n",
                   encoding="utf-8")
    rc = main(["build", str(bad), "-o", str(tmp_path / "o.xlsx")])
    assert rc == 1
    assert "invalid spec" in capsys.readouterr().err
    assert not (tmp_path / "o.xlsx").exists()
