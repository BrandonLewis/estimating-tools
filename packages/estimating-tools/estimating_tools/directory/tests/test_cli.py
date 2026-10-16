import json

import pytest

from estimating_tools.directory.cli import main


def _write_xlsx(path, header, *rows):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    wb.save(path)


def test_cli_writes_canonical_json(tmp_path):
    xlsx = tmp_path / "dir.xlsx"
    _write_xlsx(xlsx, ["organization", "is_dbe", "contact_email", "role"],
                ["Acme Paving", "yes", "jane@acme.com", "estimator"])
    out = tmp_path / "out.json"
    rc = main([str(xlsx), "-o", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    o = data["organizations"][0]
    assert o["name"] == "Acme Paving" and o["is_dbe"] is True
    assert o["contacts"][0]["email"] == "jane@acme.com" and o["contacts"][0]["role"] == "estimator"


def test_cli_applies_mapping(tmp_path):
    xlsx = tmp_path / "dir.xlsx"
    _write_xlsx(xlsx, ["Company", "Email"], ["Acme", "j@acme.com"])
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"organization": "Company", "contact_email": "Email"}))
    out = tmp_path / "out.json"
    rc = main([str(xlsx), "--mapping", str(mapping), "-o", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["organizations"][0]["name"] == "Acme"


def test_cli_missing_required_field_exits_nonzero(tmp_path, capsys):
    xlsx = tmp_path / "dir.xlsx"
    _write_xlsx(xlsx, ["org_typo", "contact_email"], ["A", "a@x.com"])
    rc = main([str(xlsx)])
    assert rc == 1
    assert "error" in capsys.readouterr().err.lower()
