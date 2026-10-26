"""`est-estimate heavycivil read` (spec §4 CLI)."""
from __future__ import annotations

import json

from estimating_tools.estimate_spec import cli
from estimating_tools.heavycivil.columns import CR
from estimating_tools.heavycivil.tests import _readback as H


def _book(tmp_path):
    return H.build_book(H.fixture_doc(), tmp_path / "e1.workbook.xlsx")


def test_read_writes_the_change_set(tmp_path, capsys):
    path = _book(tmp_path)
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    row = H.cr_row(ws, "RESOURCE", 1)
    ws[f"{CR.QTY}{row}"] = 31
    H.save_book(wb, path)
    out = tmp_path / "changes.json"
    assert cli.main(["heavycivil", "read", str(path), "-o", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["estimate_id"] == 1 and doc["estimate_v"] == "ac6cc8eec0e04323"
    assert [op["op"] for op in doc["ops"]] == ["resource.update"]
    assert doc["rows"] == [{"op_index": 0, "sheet": H.CR_TAB, "row": row}]
    assert doc["summary"] == [f"{H.CR_TAB} row {row}: 'CAT 336' quantity 30 → 31"]
    printed = capsys.readouterr().out
    assert "WROTE:" in printed and "1 op(s) for estimate 1" in printed


def test_an_unedited_book_reads_no_changes(tmp_path, capsys):
    path = _book(tmp_path)
    assert cli.main(["heavycivil", "read", str(path)]) == 0
    out = tmp_path / "e1.workbook.changes.json"
    assert json.loads(out.read_text(encoding="utf-8"))["ops"] == []
    assert "no changes" in capsys.readouterr().out


def test_no_changes_still_prints_the_notes(tmp_path, capsys):
    path = _book(tmp_path)
    wb = H.open_book(path)
    ws = wb[H.BF_TAB]
    H.type_row(ws, H.find_row(ws, "ITEM_BID", 3, kind_col="J", id_col="K"),
               {"A": "Z9", "B": "New item", "D": 3})
    H.save_book(wb, path)
    assert cli.main(["heavycivil", "read", str(path)]) == 0
    printed = capsys.readouterr().out
    assert "no changes" in printed and "Notes:" in printed
    assert "ignored" in printed and "add bid items in BidSheet.ai" in printed


def test_a_refused_read_exits_2_and_writes_nothing(tmp_path, capsys):
    path = _book(tmp_path)
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"] = "lots"
    ws[f"{CR.TYPE}{H.cr_row(ws, 'RESOURCE', 2)}"] = "labour"
    H.save_book(wb, path)
    out = tmp_path / "changes.json"
    assert cli.main(["heavycivil", "read", str(path), "-o", str(out)]) == 2
    assert not out.exists()
    err = capsys.readouterr().err
    assert "2 problem(s)" in err and "'lots' is not a number" in err and "'labour'" in err


def test_a_refused_read_leaves_an_earlier_change_set_alone(tmp_path, capsys):
    path = _book(tmp_path)
    out = tmp_path / "changes.json"
    out.write_text("earlier", encoding="utf-8")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"] = "lots"
    H.save_book(wb, path)
    assert cli.main(["heavycivil", "read", str(path), "-o", str(out)]) == 2
    assert out.read_text(encoding="utf-8") == "earlier"
    assert "nothing written" in capsys.readouterr().err


def test_a_tampered_baseline_exits_2(tmp_path, capsys):
    path = _book(tmp_path)
    wb = H.open_book(path)
    chunk = wb["_wb"]["B1"].value
    wb["_wb"]["B1"] = ("A" if chunk[10] != "A" else "B").join((chunk[:10], chunk[11:]))
    H.save_book(wb, path)
    out = tmp_path / "changes.json"
    assert cli.main(["heavycivil", "read", str(path), "-o", str(out)]) == 2
    assert not out.exists()
    err = capsys.readouterr().err
    assert "1 problem(s)" in err and "baseline" in err and "rebuild the book" in err


def test_not_an_xlsx_exits_2(tmp_path, capsys):
    path = tmp_path / "notes.xlsx"
    path.write_text("not a workbook", encoding="utf-8")
    assert cli.main(["heavycivil", "read", str(path)]) == 2
    assert not (tmp_path / "notes.changes.json").exists()
    assert "cannot read" in capsys.readouterr().err


def test_the_output_may_not_be_the_book(tmp_path, capsys):
    path = _book(tmp_path)
    assert cli.main(["heavycivil", "read", str(path), "-o", str(path)]) == 2
    assert "is the workbook itself" in capsys.readouterr().err


def test_a_missing_book_exits_2(tmp_path, capsys):
    assert cli.main(["heavycivil", "read", str(tmp_path / "nope.xlsx")]) == 2
    assert "no such file" in capsys.readouterr().err
    assert not (tmp_path / "nope.changes.json").exists()
