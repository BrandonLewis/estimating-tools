"""Tests for the shared XER reader + dump/bridge output profiles (#204)."""
from __future__ import annotations

import pytest

from estimating_tools.schedule import xer

openpyxl = pytest.importorskip("openpyxl")


# ---------------------------------------------------------------------------
# a compact but realistic XER fixture
# ---------------------------------------------------------------------------

def _line(tag, *cells):
    return "\t".join((tag, *cells))


FIXTURE = "\n".join([
    _line("ERMHDR", "20.12", "2026-01-01", "Project", "admin"),
    _line("%T", "PROJECT"),
    _line("%F", "proj_id", "proj_short_name", "plan_start_date"),
    _line("%R", "1", "TESTJOB", "2026-02-01 08:00"),
    _line("%T", "PROJWBS"),
    _line("%F", "wbs_id", "proj_id", "seq_num", "proj_node_flag",
          "wbs_short_name", "wbs_name", "parent_wbs_id"),
    _line("%R", "100", "1", "1", "Y", "ROOT", "Test Job", ""),
    _line("%R", "101", "1", "1", "N", "SUB", "Substructure", "100"),
    _line("%R", "102", "1", "2", "N", "SUP", "Superstructure", "100"),
    _line("%T", "TASK"),
    _line("%F", "task_id", "proj_id", "wbs_id", "task_code", "task_name",
          "task_type", "status_code", "target_drtn_hr_cnt",
          "total_float_hr_cnt", "target_start_date", "target_end_date",
          "early_start_date", "early_end_date", "act_start_date",
          "act_end_date"),
    # a summary (LOE) row + two real tasks across two code prefixes
    _line("%R", "1000", "1", "101", "PPOB.SUM", "Bridge Summary", "TT_WBS",
          "TK_NotStart", "0", "0", "2026-02-01 08:00", "2026-03-01 17:00",
          "", "", "", ""),
    _line("%R", "1001", "1", "101", "PPOB.1000", "Drive piles", "TT_Task",
          "TK_NotStart", "80", "16", "2026-02-01 08:00", "2026-02-11 17:00",
          "2026-02-01 08:00", "2026-02-11 17:00", "", ""),
    _line("%R", "1002", "1", "102", "WHIT.1000", "Erect girders", "TT_Task",
          "TK_NotStart", "40", "8", "2026-02-12 08:00", "2026-02-17 17:00",
          "2026-02-12 08:00", "2026-02-17 17:00", "", ""),
    _line("%T", "TASKPRED"),
    _line("%F", "task_pred_id", "task_id", "pred_task_id", "pred_type",
          "lag_hr_cnt"),
    _line("%R", "5000", "1002", "1001", "PR_FS", "0"),
    "%E",
]) + "\n"


# ---------------------------------------------------------------------------
# reader helpers
# ---------------------------------------------------------------------------

def test_parse_tables_reads_blocks():
    tables = xer.parse_tables(FIXTURE)
    assert set(tables) == {"PROJECT", "PROJWBS", "TASK", "TASKPRED"}
    assert tables["PROJECT"][0]["proj_short_name"] == "TESTJOB"
    assert len(tables["TASK"]) == 3
    assert tables["TASK"][1]["task_code"] == "PPOB.1000"


def test_parse_tables_pads_short_rows_and_truncates_long():
    text = "\n".join([
        _line("%T", "T"),
        _line("%F", "a", "b", "c"),
        _line("%R", "1"),                 # short: b, c missing
        _line("%R", "1", "2", "3", "4"),  # long: extra dropped
    ]) + "\n"
    rows = xer.parse_tables(text)["T"]
    assert rows[0] == {"a": "1", "b": "", "c": ""}
    assert rows[1] == {"a": "1", "b": "2", "c": "3"}


def test_wbs_paths_builds_name_chain():
    tables = xer.parse_tables(FIXTURE)
    paths = xer.wbs_paths(tables)
    assert paths["101"] == "Test Job > Substructure"
    assert paths["102"] == "Test Job > Superstructure"


def test_hours_to_workdays():
    assert xer.hours_to_workdays("80", 8.0) == 10.0
    assert xer.hours_to_workdays("40", 8.0, whole=True) == 5
    assert xer.hours_to_workdays("", 8.0) is None
    assert xer.hours_to_workdays(None, 8.0) is None


def test_xer_date_is_date_only():
    assert xer.xer_date("2026-02-01 08:00") == "2026-02-01"
    assert xer.xer_date("") is None
    assert xer.xer_date(None) is None


# ---------------------------------------------------------------------------
# dump profile
# ---------------------------------------------------------------------------

def test_write_dump_has_core_sheets_and_rows(tmp_path):
    out = tmp_path / "dump.xlsx"
    tables = xer.parse_tables(FIXTURE)
    xer.write_dump(tables, str(out))
    wb = openpyxl.load_workbook(out)
    assert {"Activities", "WBS", "Relationships"} <= set(wb.sheetnames)
    acts = wb["Activities"]
    codes = [r[0] for r in acts.iter_rows(min_row=2, max_col=1, values_only=True)]
    assert "PPOB.1000" in codes and "WHIT.1000" in codes
    # WBS path resolves on the activity row
    hdr = [c.value for c in acts[1]]
    wbs_col = hdr.index("WBS") + 1
    piles = next(r for r in acts.iter_rows(min_row=2, values_only=True)
                 if r[0] == "PPOB.1000")
    assert piles[wbs_col - 1] == "Test Job > Substructure"


def test_write_dump_includes_raw_table_sheets(tmp_path):
    out = tmp_path / "dump.xlsx"
    tables = xer.parse_tables(FIXTURE)
    xer.write_dump(tables, str(out), raw=True)
    wb = openpyxl.load_workbook(out)
    # raw dump of the source table names (sanitized), e.g. PROJECT
    assert any(s.startswith("PROJECT") for s in wb.sheetnames)


def test_write_dump_is_byte_deterministic(tmp_path):
    tables = xer.parse_tables(FIXTURE)
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    xer.write_dump(tables, str(a))
    xer.write_dump(tables, str(b))
    assert a.read_bytes() == b.read_bytes()


# ---------------------------------------------------------------------------
# bridge profile
# ---------------------------------------------------------------------------

BRIDGE_CFG = {
    "title": "Test Job — Baseline V.01",
    "hours_per_day": 8.0,
    "stage_rules": [
        {"contains": "superstructure", "label": "Stage 2 - Superstructure"},
        {"contains": "substructure", "label": "Stage 1 - Substructure"},
    ],
    "sheets": [
        {"title": "OH Bridge", "subtitle": "OH Bridge (PPOB)",
         "code_prefixes": ["PPOB"]},
        {"title": "OC Bridge", "subtitle": "OC Bridge (WHIT)",
         "code_prefixes": ["WHIT"]},
    ],
}


def test_write_bridge_banner_and_selection(tmp_path):
    out = tmp_path / "bridge.xlsx"
    tables = xer.parse_tables(FIXTURE)
    xer.write_bridge(tables, str(out), BRIDGE_CFG)
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["OH Bridge", "OC Bridge"]
    oh = wb["OH Bridge"]
    assert oh["A1"].value == "Test Job — Baseline V.01"
    assert oh["A2"].value == "OH Bridge (PPOB)"
    # header row at row 4; data from row 5
    body_codes = [r[0] for r in oh.iter_rows(min_row=5, max_col=1,
                                             values_only=True) if r[0]]
    assert body_codes == ["PPOB.SUM", "PPOB.1000"]     # .SUM sorts first
    # OC sheet only carries WHIT
    oc = wb["OC Bridge"]
    oc_codes = [r[0] for r in oc.iter_rows(min_row=5, max_col=1,
                                           values_only=True) if r[0]]
    assert oc_codes == ["WHIT.1000"]


def test_write_bridge_stage_label_and_summary_highlight(tmp_path):
    out = tmp_path / "bridge.xlsx"
    tables = xer.parse_tables(FIXTURE)
    xer.write_bridge(tables, str(out), BRIDGE_CFG)
    wb = openpyxl.load_workbook(out)
    oh = wb["OH Bridge"]
    rows = {r[0]: r for r in oh.iter_rows(min_row=5, values_only=True) if r[0]}
    # stage column is C (index 2): the pile task lands under Substructure rule
    assert rows["PPOB.1000"][2] == "Stage 1 - Substructure"
    assert rows["PPOB.SUM"][2] == "Summary"
    # the summary row is yellow-filled + bold
    sum_row = next(cells for cells in oh.iter_rows(min_row=5)
                   if cells[0].value == "PPOB.SUM")
    assert sum_row[0].font.bold is True
    assert sum_row[0].fill.fgColor.rgb.endswith("FFFF00")


def test_write_bridge_code_range_selector(tmp_path):
    text = "\n".join([
        _line("%T", "PROJWBS"),
        _line("%F", "wbs_id", "seq_num", "proj_node_flag", "wbs_name",
              "parent_wbs_id"),
        _line("%R", "1", "1", "N", "Walls", ""),
        _line("%T", "TASK"),
        _line("%F", "task_id", "wbs_id", "task_code", "task_name",
              "task_type", "target_drtn_hr_cnt", "total_float_hr_cnt",
              "target_start_date", "target_end_date"),
        _line("%R", "1", "1", "RW.1060", "Wall footing", "TT_Task", "80",
              "0", "2026-02-01 08:00", "2026-02-11 17:00"),
        _line("%R", "2", "1", "RW.1200", "Wall stem", "TT_Task", "80", "0",
              "2026-02-12 08:00", "2026-02-22 17:00"),
        _line("%R", "3", "1", "RW.2000", "Out of range", "TT_Task", "80", "0",
              "2026-03-01 08:00", "2026-03-11 17:00"),
    ]) + "\n"
    cfg = {"title": "T", "sheets": [
        {"title": "RW", "subtitle": "Retaining wall", "code_prefix": "RW",
         "code_range": [1060, 1210]}]}
    out = tmp_path / "b.xlsx"
    xer.write_bridge(xer.parse_tables(text), str(out), cfg)
    wb = openpyxl.load_workbook(out)
    codes = [r[0] for r in wb["RW"].iter_rows(min_row=5, max_col=1,
                                              values_only=True) if r[0]]
    assert codes == ["RW.1060", "RW.1200"]     # RW.2000 excluded by range


def test_write_bridge_is_byte_deterministic(tmp_path):
    tables = xer.parse_tables(FIXTURE)
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    xer.write_bridge(tables, str(a), BRIDGE_CFG)
    xer.write_bridge(tables, str(b), BRIDGE_CFG)
    assert a.read_bytes() == b.read_bytes()


def test_write_bridge_rejects_bad_config(tmp_path):
    out = tmp_path / "b.xlsx"
    tables = xer.parse_tables(FIXTURE)
    with pytest.raises(ValueError, match="title"):
        xer.write_bridge(tables, str(out), {"sheets": []})
    with pytest.raises(ValueError, match="sheets"):
        xer.write_bridge(tables, str(out), {"title": "x", "sheets": []})
    with pytest.raises(ValueError, match="selector"):
        xer.write_bridge(tables, str(out),
                         {"title": "x", "sheets": [{"title": "s"}]})


def test_write_dump_rejects_nonpositive_hours_per_day(tmp_path):
    tables = xer.parse_tables(FIXTURE)
    with pytest.raises(ValueError, match="hours_per_day"):
        xer.write_dump(tables, str(tmp_path / "d.xlsx"), hours_per_day=0)


def test_write_bridge_rejects_nonpositive_hours_per_day(tmp_path):
    tables = xer.parse_tables(FIXTURE)
    cfg = {**BRIDGE_CFG, "hours_per_day": 0}
    with pytest.raises(ValueError, match="hours_per_day"):
        xer.write_bridge(tables, str(tmp_path / "b.xlsx"), cfg)


def test_write_bridge_rejects_scalar_code_prefixes(tmp_path):
    tables = xer.parse_tables(FIXTURE)
    cfg = {"title": "x", "sheets": [{"title": "s", "code_prefixes": "PPOB"}]}
    with pytest.raises(ValueError, match="code_prefixes must be a list"):
        xer.write_bridge(tables, str(tmp_path / "b.xlsx"), cfg)


def test_write_bridge_rejects_unknown_date_source(tmp_path):
    tables = xer.parse_tables(FIXTURE)
    cfg = {**BRIDGE_CFG, "date_source": "actuals"}   # typo for "actual"
    with pytest.raises(ValueError, match="date_source"):
        xer.write_bridge(tables, str(tmp_path / "b.xlsx"), cfg)


def test_write_bridge_dedups_truncated_sheet_titles(tmp_path):
    tables = xer.parse_tables(FIXTURE)
    long_a = "Overhead Structure Bridge Approach North Leg"
    long_b = "Overhead Structure Bridge Approach South Leg"   # same first 31
    cfg = {"title": "x", "sheets": [
        {"title": long_a, "code_prefixes": ["PPOB"]},
        {"title": long_b, "code_prefixes": ["WHIT"]}]}
    out = tmp_path / "b.xlsx"
    xer.write_bridge(tables, str(out), cfg)
    wb = openpyxl.load_workbook(out)
    assert len(wb.sheetnames) == 2                    # no collision
    assert len(set(wb.sheetnames)) == 2


def test_write_bridge_dates_are_real_excel_dates(tmp_path):
    import datetime
    tables = xer.parse_tables(FIXTURE)
    out = tmp_path / "b.xlsx"
    xer.write_bridge(tables, str(out), BRIDGE_CFG)
    wb = openpyxl.load_workbook(out)
    oh = wb["OH Bridge"]
    piles = next(cells for cells in oh.iter_rows(min_row=5)
                 if cells[0].value == "PPOB.1000")
    # Start (col E) is a real date, not ISO text
    assert isinstance(piles[4].value, (datetime.date, datetime.datetime))


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def test_cli_xer_dump(tmp_path, capsys):
    from estimating_tools.schedule.cli import main
    src = tmp_path / "sched.xer"
    src.write_text(FIXTURE, encoding="cp1252")
    out = tmp_path / "dump.xlsx"
    assert main(["xer", str(src), "--profile", "dump", "--out", str(out)]) == 0
    assert out.exists()
    wb = openpyxl.load_workbook(out)
    assert "Activities" in wb.sheetnames


def test_cli_xer_bridge_needs_config(tmp_path, capsys):
    from estimating_tools.schedule.cli import main
    src = tmp_path / "sched.xer"
    src.write_text(FIXTURE, encoding="cp1252")
    with pytest.raises(SystemExit):
        main(["xer", str(src), "--profile", "bridge",
              "--out", str(tmp_path / "b.xlsx")])


def test_cli_xer_bridge_with_config(tmp_path):
    import json
    from estimating_tools.schedule.cli import main
    src = tmp_path / "sched.xer"
    src.write_text(FIXTURE, encoding="cp1252")
    cfg = tmp_path / "bridge.json"
    cfg.write_text(json.dumps(BRIDGE_CFG), encoding="utf-8")
    out = tmp_path / "bridge.xlsx"
    assert main(["xer", str(src), "--profile", "bridge",
                 "--config", str(cfg), "--out", str(out)]) == 0
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["OH Bridge", "OC Bridge"]


def test_cli_xer_rejects_non_p6(tmp_path, capsys):
    from estimating_tools.schedule.cli import main
    src = tmp_path / "empty.xer"
    src.write_text("ERMHDR\tx\n%E\n", encoding="cp1252")
    assert main(["xer", str(src), "--out", str(tmp_path / "o.xlsx")]) == 1
    assert "no TASK table" in capsys.readouterr().err
