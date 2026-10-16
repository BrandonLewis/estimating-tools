import json

import pytest

from estimating_tools.assemblies.cli import main


def _write_xlsx(path, header, *rows):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    wb.save(path)


def test_cli_writes_canonical_json(tmp_path):
    xlsx = tmp_path / "lib.xlsx"
    _write_xlsx(xlsx, ["assembly", "component_type", "component", "unit_cost"],
                ["CIP wall", "labor", "Form/pour", 65])
    out = tmp_path / "out.json"
    rc = main([str(xlsx), "-o", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["assemblies"][0]["name"] == "CIP wall"
    assert data["assemblies"][0]["components"][0]["component_type"] == "labor"


def test_cli_applies_mapping(tmp_path):
    xlsx = tmp_path / "lib.xlsx"
    _write_xlsx(xlsx, ["Assembly Name", "Crew Type", "Item"],
                ["Striping", "Labor", "Stripe"])
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"assembly": "Assembly Name", "component_type": "Crew Type", "component": "Item"}))
    out = tmp_path / "out.json"
    rc = main([str(xlsx), "--mapping", str(mapping), "-o", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["assemblies"][0]["name"] == "Striping"
    assert data["assemblies"][0]["components"][0]["component_type"] == "labor"


def test_cli_missing_required_field_exits_nonzero(tmp_path, capsys):
    xlsx = tmp_path / "lib.xlsx"
    _write_xlsx(xlsx, ["assembly", "component_type", "name_typo"],
                ["A", "labor", "x"])
    rc = main([str(xlsx)])
    assert rc == 1
    assert "error" in capsys.readouterr().err.lower()
