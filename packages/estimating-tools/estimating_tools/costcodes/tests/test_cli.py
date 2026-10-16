import json

import pytest

from estimating_tools.costcodes.cli import main


def _write_xlsx(path, header, *rows):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    wb.save(path)


def test_cli_writes_canonical_json(tmp_path):
    xlsx = tmp_path / "codes.xlsx"
    _write_xlsx(xlsx, ["code", "description", "cost_type", "parent_code"],
                ["02", "Bridge", "L", ""],
                ["02-110", "Form Footings", "L", "02"])
    out = tmp_path / "out.json"
    rc = main([str(xlsx), "--system-name", "Std 2026", "-o", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["name"] == "Std 2026"
    assert [c["code"] for c in data["cost_types"]] == ["L"]
    codes = [a["code"] for a in data["activity_codes"]]
    assert codes.index("02") < codes.index("02-110")


def test_cli_applies_mapping(tmp_path):
    xlsx = tmp_path / "codes.xlsx"
    _write_xlsx(xlsx, ["Code", "Type"], ["01-100", "L"])
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"code": "Code", "cost_type": "Type"}))
    out = tmp_path / "out.json"
    rc = main([str(xlsx), "--system-name", "S", "--mapping", str(mapping), "-o", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["activity_codes"][0]["code"] == "01-100"


def test_cli_missing_system_name_exits_nonzero(tmp_path, capsys):
    xlsx = tmp_path / "codes.xlsx"
    _write_xlsx(xlsx, ["code"], ["A"])
    # argparse enforces the required --system-name: SystemExit(2)
    with pytest.raises(SystemExit):
        main([str(xlsx)])


def test_cli_tree_error_exits_nonzero(tmp_path, capsys):
    xlsx = tmp_path / "codes.xlsx"
    _write_xlsx(xlsx, ["code", "parent_code"], ["02-110", "99"])
    rc = main([str(xlsx), "--system-name", "S"])
    assert rc == 1
    assert "error" in capsys.readouterr().err.lower()


def test_cli_passes_strategy_and_composition(tmp_path):
    xlsx = tmp_path / "codes.xlsx"
    _write_xlsx(xlsx, ["code"], ["03"], ["03 30 00"])
    out = tmp_path / "out.json"
    rc = main([
        str(xlsx), "--system-name", "MF",
        "--parent-strategy", "segment_truncate",
        "--composition", "monolithic",
        "--source-system", "MasterFormat", "--edition", "2020",
        "-o", str(out),
    ])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["composition"] == "monolithic"
    assert data["source_system"] == "MasterFormat"
    assert data["edition"] == "2020"
    by = {a["code"]: a for a in data["activity_codes"]}
    assert by["03 30 00"]["parent_code"] == "03"
