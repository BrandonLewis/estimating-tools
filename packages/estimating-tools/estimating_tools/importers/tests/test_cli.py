import json
import openpyxl

from estimating_tools.importers.cli import main


def _hcss_workbook(path):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Bid Item", "Description", "Quantity", "Unit", "Unit Price", "Cost Code"])
    ws.append(["1", "Mobilization", 1, "LS", 50000, "070-010"])
    wb.save(path)


def test_cli_writes_valid_canonical_json(tmp_path, capsys):
    src = tmp_path / "export.xlsx"; _hcss_workbook(src)
    out = tmp_path / "out.json"
    rc = main([str(src), "-o", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["project"]["source"] == "HCSS HeavyBid"
    assert data["schedules"][0]["items"][0]["item_code"] == "070-010"
    # validates against the schema (no raise)
    from estimating_tools.importers.validate import validate_canonical
    validate_canonical(data)


def test_cli_unrecognized_file_errors(tmp_path, capsys):
    bad = tmp_path / "x.xlsx"
    wb = openpyxl.Workbook(); wb.active.append(["foo"]); wb.save(bad)
    rc = main([str(bad)])
    assert rc != 0
