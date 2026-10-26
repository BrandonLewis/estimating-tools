from __future__ import annotations

import json

import pytest

from estimating_tools.heavycivil import build, model, style


def _prop(wb, name):
    return next(p.value for p in wb.custom_doc_props.props if p.name == name)


def test_sheet_order_and_hidden_machinery(book):
    assert book.sheetnames == ["Bid Form", "Recap", "Cost Report", "Crews", "Rates", "Schedule",
                               "Checks", "Flat", "_shares", "_cal", "_wb"]
    for name in ("_shares", "_cal", "_wb"):
        assert book[name].sheet_state == "hidden"
    assert book.active.title == "Bid Form"


def test_stamp(book, doc):
    assert _prop(book, "estimate_format") == "heavycivil 1"
    assert _prop(book, "estimate_id") == str(doc["estimate"]["id"])
    assert _prop(book, "bidsheet_host") == "www.bidsheet.ai"
    assert _prop(book, "exported_at") == "2026-10-20T09:00:00Z"
    assert _prop(book, "style_pack") == "heavycivil 1"
    assert _prop(book, "source_sha") == model.source_sha(doc)


def test_layout_json_cell_and_names(book):
    layout = json.loads(book["_wb"]["A1"].value)
    assert layout["format"] == "heavycivil"
    assert layout["layout_version"] == 2
    assert set(layout["baseline"]) == {"encoding", "chunks", "sha256"}
    for name in ("hc.cost_report", "hc.checks", "hc.layout"):
        assert name in book.defined_names
    assert book.defined_names["hc.layout"].attr_text == "'_wb'!$A$1"
    assert not [n for n in book.defined_names if n.startswith("est.")]


def test_bid_and_schedule_names(book):
    names = {n: book.defined_names[n].attr_text for n in book.defined_names}
    assert names["hc.bid_form"] == "'Bid Form'!$A$12:$T$19"
    assert names["hc.bid_totals"] == "'Bid Form'!$A$22:$I$23"
    assert names["hc.schedule"] == "'Schedule'!$A$4:$K$6"


def test_no_schedule_rows_no_schedule_name(doc):
    for a in doc["activities"]:
        a["start_date"] = a["end_date"] = a["finish_date"] = None
    doc["estimate"]["bid_totals"] = []
    wb = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    assert "hc.schedule" not in wb.defined_names
    # The implicit "Bid Total" row stands in for the missing definitions.
    assert wb.defined_names["hc.bid_totals"].attr_text == "'Bid Form'!$A$22:$I$22"
    assert wb["Bid Form"]["A22"].value == "Bid Total (primary)"
    # It has no amount in the payload to compare against.
    checks = wb["Checks"]
    (status,) = [checks[f"I{n}"].value for n in range(5, checks.max_row + 1)
                 if checks[f"A{n}"].value == "bid total"]
    assert status == "export"


def test_renamed_tab_flows_into_formulas(doc, tmp_path):
    (tmp_path / "sheets.yaml").write_text("sheets:\n  crews:\n    tab: Crew Rates\n")
    wb = build.build(doc, style=style.load_style(tmp_path), exported_at="x", host="h")
    assert "Crew Rates" in wb.sheetnames
    formulas = [c.value for row in wb["Cost Report"].iter_rows() for c in row
                if isinstance(c.value, str) and "Crew Rates" in c.value]
    assert formulas


def test_bad_payload_raises_payload_error(doc):
    del doc["shares"]
    with pytest.raises(model.PayloadError):
        build.build(doc, style=style.load_style(), exported_at="x", host="h")


def test_rates_sheet_honours_freeze_and_print_style(book):
    ws = book["Rates"]
    assert ws.freeze_panes == "A3"
    assert ws.page_setup.orientation == "portrait"
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True
    assert ws.page_setup.fitToWidth == 1
    assert not ws.print_title_rows


def test_large_payload_fits_excels_cell_limit(doc):
    """Excel caps a cell at 32,767 characters; ``_wb!A1`` must not grow with
    the estimate."""
    base = list(doc["resources"])
    next_id = max(r["id"] for r in base) + 1
    for _ in range(200):
        for r in base:
            doc["resources"].append(dict(r, id=next_id))
            next_id += 1
    wb = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    assert len(wb["_wb"]["A1"].value) < 32767
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                assert not (isinstance(c.value, str) and len(c.value) > 32767), c.coordinate


def test_illegal_xml_characters_are_stripped(doc):
    doc["items"][0]["description"] = "Walls\x0b and footings"
    wb = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    values = [c.value for row in wb["Cost Report"].iter_rows() for c in row]
    assert "Walls and footings" in values


def test_failed_save_leaves_the_old_file(doc, tmp_path, monkeypatch):
    dest = tmp_path / "hc.xlsx"
    dest.write_bytes(b"previous")
    wb = build.build(doc, style=style.load_style(), exported_at="x", host="h")

    def boom(path):
        raise OSError("disk full")

    monkeypatch.setattr(build, "normalize_xlsx", boom)
    with pytest.raises(OSError, match="disk full"):
        build.save(wb, dest)
    assert dest.read_bytes() == b"previous"
    assert [p.name for p in tmp_path.iterdir()] == ["hc.xlsx"]


def test_save_replaces_the_destination(doc, tmp_path):
    dest = tmp_path / "hc.xlsx"
    dest.write_bytes(b"previous")
    wb = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    build.save(wb, dest)
    assert dest.read_bytes()[:2] == b"PK"
    assert [p.name for p in tmp_path.iterdir()] == ["hc.xlsx"]


def test_saved_file_has_a_normal_files_mode(doc, tmp_path):
    """mkstemp makes the temp file 0600; the saved book must get the mode a
    normally created file would (0666 less the umask)."""
    import os
    import stat
    wb = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    dest = tmp_path / "hc.xlsx"
    build.save(wb, dest)
    plain = tmp_path / "plain.txt"
    plain.write_bytes(b"x")
    assert stat.S_IMODE(os.stat(dest).st_mode) == stat.S_IMODE(os.stat(plain).st_mode)


def test_checks_factor_and_schedule_rows_have_their_own_formats(book):
    ws = book["Checks"]
    rows = {ws[f"D{n}"].value: n for n in range(5, ws.max_row + 1)
            if ws[f"D{n}"].value in ("factor", "finish")}
    factor, finish = rows["factor"], rows["finish"]
    for col in "EFG":
        assert ws[f"{col}{factor}"].number_format == "0.0000000000", col
    for col in "EF":
        assert ws[f"{col}{finish}"].number_format == "yyyy-mm-dd", col
    assert ws[f"G{finish}"].number_format == "#,##0.00"            # days apart


def test_cost_report_name_reaches_the_activity_row_column(book):
    assert book.defined_names["hc.cost_report"].attr_text == "'Cost Report'!$A$4:$AJ$46"


def test_a_non_json_payload_value_is_refused_before_any_sheet_is_written(doc, monkeypatch):
    from estimating_tools.heavycivil import baseline, build as hc_build
    called = []
    monkeypatch.setattr(hc_build, "write_bid_form", lambda *a, **k: called.append(1))
    with pytest.raises(baseline.BaselineError):
        hc_build.build(dict(doc, unread_field=float("nan")), style=style.load_style(),
                       exported_at="x", host="h")
    assert called == []
