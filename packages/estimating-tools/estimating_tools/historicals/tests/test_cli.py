import json
from pathlib import Path

from estimating_tools.historicals.cli import main

FIX = Path(__file__).parent / "fixtures"


def test_parse_records_suggest_end_to_end(tmp_path, capsys):
    tab_json = tmp_path / "tab.json"
    assert main(["parse", str(FIX / "sr49_tab.csv"), "-o", str(tab_json)]) == 0
    assert "QC" in capsys.readouterr().out
    doc = json.loads(tab_json.read_text(encoding="utf-8"))
    assert doc["agency"] == "caltrans"

    records = tmp_path / "records.jsonl"
    assert main(["records", str(tab_json), "-o", str(records)]) == 0
    lines = [json.loads(l) for l in records.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 4                      # 2 items x 2 bidders
    assert {l["outcome"] for l in lines} == {"awarded", "competitor_bid"}

    assert main(["suggest", "--records", str(records), "--code", "510120",
                 "--qty", "412", "--unit", "CY", "--region", "sierra",
                 "--as-of", "2026-08-05"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["suggested"]["median"] == 1650.0   # awarded outweighs competitor


def test_parse_missing_file_exits_nonzero(tmp_path, capsys):
    assert main(["parse", str(tmp_path / "nope.csv")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""                    # errors go to stderr only
    assert "no such file" in captured.err


def test_records_invalid_tab_json_exits_nonzero(tmp_path, capsys):
    bad = tmp_path / "tab.json"
    bad.write_text("not json", encoding="utf-8")
    assert main(["records", str(bad)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""                    # errors go to stderr only
    assert "invalid tab JSON" in captured.err


def test_suggest_bad_jsonl_line_exits_nonzero(tmp_path, capsys):
    jsonl = tmp_path / "records.jsonl"
    jsonl.write_text('{"outcome": "awarded", "unit_price_bid": 5.0}\n{broken\n',
                     encoding="utf-8")
    assert main(["suggest", "--records", str(jsonl)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""                    # suggest stdout stays pure JSON
    assert "line 2" in captured.err


def test_suggest_bad_as_of_exits_nonzero(tmp_path, capsys):
    jsonl = tmp_path / "records.jsonl"
    jsonl.write_text('{"outcome": "awarded", "unit_price_bid": 5.0, "unit": "CY"}\n',
                     encoding="utf-8")
    assert main(["suggest", "--records", str(jsonl),
                 "--as-of", "2026-13-99"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""                    # errors go to stderr only
    assert "invalid --as-of" in captured.err


CANONICAL = {
    "project": {"name": "sample-bridge", "bid_date": "2026-08-05", "source": "hcss:x.xlsx"},
    "schedules": [{"name": "Base Bid", "items": [
        {"item_number": "4", "description": "Structural Concrete",
         "item_code": "0310.20", "quantity": 412.0, "unit": "CY",
         "unit_price": 1650.0,
         "breakdown": {"labor": 96000.0, "subcontractor": 0.0}},
        {"item_number": "5", "description": "Unpriced", "unit": "LS"},
    ]}],
}


def test_from_estimate_end_to_end(tmp_path, capsys):
    src = tmp_path / "sample-bridge.canonical.json"
    src.write_text(json.dumps(CANONICAL), encoding="utf-8")
    codes = tmp_path / "codes.json"
    codes.write_text(json.dumps({"Base Bid::4": "510120"}), encoding="utf-8")
    out = tmp_path / "est.records.jsonl"
    assert main(["from-estimate", str(src), "--outcome", "estimated",
                 "--agency", "caltrans", "--region", "sierra",
                 "--bidder", "Acme", "--code-map", str(codes),
                 "-o", str(out)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""                    # status goes to stderr
    assert "1 records" in captured.err
    lines = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1                       # unpriced item skipped
    rec = lines[0]
    assert rec["outcome"] == "estimated"
    assert rec["bid_item_code"] == "510120"
    assert rec["unit_cost_estimated"] == 1650.0
    assert rec["breakdown"] == [{"cost_code": "0310.20", "labor": 96000.0,
                                 "sub": 0.0}]
    assert rec["agency"] == "caltrans" and rec["bidder"] == "Acme"


def test_from_estimate_default_output_path(tmp_path, capsys):
    src = tmp_path / "sample-bridge.canonical.json"
    src.write_text(json.dumps(CANONICAL), encoding="utf-8")
    assert main(["from-estimate", str(src)]) == 0
    assert (tmp_path / "sample-bridge.canonical.records.jsonl").exists()
    capsys.readouterr()                          # drain stderr status


def test_from_estimate_missing_file_exits_nonzero(tmp_path, capsys):
    assert main(["from-estimate", str(tmp_path / "nope.json")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""                    # errors go to stderr only
    assert "no such file" in captured.err


def test_from_estimate_invalid_json_exits_nonzero(tmp_path, capsys):
    bad = tmp_path / "bad.canonical.json"
    bad.write_text("not json", encoding="utf-8")
    assert main(["from-estimate", str(bad)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid canonical JSON" in captured.err


def test_from_estimate_missing_code_map_exits_nonzero(tmp_path, capsys):
    src = tmp_path / "sample-bridge.canonical.json"
    src.write_text(json.dumps(CANONICAL), encoding="utf-8")
    assert main(["from-estimate", str(src),
                 "--code-map", str(tmp_path / "nope.json")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no such file" in captured.err


def test_from_estimate_non_object_code_map_exits_nonzero(tmp_path, capsys):
    src = tmp_path / "sample-bridge.canonical.json"
    src.write_text(json.dumps(CANONICAL), encoding="utf-8")
    codes = tmp_path / "codes.json"
    codes.write_text('["510120"]', encoding="utf-8")   # valid JSON, not a dict
    assert main(["from-estimate", str(src), "--code-map", str(codes)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid code map JSON" in captured.err
