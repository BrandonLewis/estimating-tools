import json

import pytest

from estimating_tools.rates.cli import main


def _write_xlsx(path, header, *rows):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    wb.save(path)


def test_cli_writes_canonical_json(tmp_path):
    xlsx = tmp_path / "rates.xlsx"
    _write_xlsx(xlsx, ["rate_type", "name", "rate", "unit"],
                ["material", "Rebar #4", 0.85, "LF"],
                ["labor", "CARP", 45, ""])
    out = tmp_path / "out.json"
    rc = main([str(xlsx), "-o", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["material_costs"][0]["material_name"] == "Rebar #4"
    assert data["labor_rates"][0]["classification"] == "CARP"


def test_cli_applies_mapping(tmp_path):
    xlsx = tmp_path / "rates.xlsx"
    _write_xlsx(xlsx, ["Type", "Classification", "Base $/hr"],
                ["Labor", "OPER", 52.5])
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"rate_type": "Type", "name": "Classification", "rate": "Base $/hr"}))
    out = tmp_path / "out.json"
    rc = main([str(xlsx), "--mapping", str(mapping), "-o", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["labor_rates"][0]["classification"] == "OPER"


def test_cli_non_numeric_rate_exits_nonzero(tmp_path, capsys):
    xlsx = tmp_path / "rates.xlsx"
    _write_xlsx(xlsx, ["rate_type", "name", "rate"], ["labor", "CARP", "N/A"])
    rc = main([str(xlsx)])
    assert rc == 1
    assert "error" in capsys.readouterr().err.lower()
