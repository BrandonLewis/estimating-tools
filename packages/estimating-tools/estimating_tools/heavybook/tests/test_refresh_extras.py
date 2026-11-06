"""HeavyBook's own part of a new baseline (``heavybook.refresh.extras``): the
Checks sheet's BidSheet.ai figures and export line after a refresh or a
patch (#426), the cost-share guard, and the spec's Patch fixture on a real
HeavyBook book."""
from __future__ import annotations

import zipfile
from decimal import Decimal

from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment

from estimating_tools.exchange import model, writer
from estimating_tools.exchange.types import ApplyResult
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook import style
from estimating_tools.heavybook.columns import CK, CR
from estimating_tools.heavybook.sheets import checks
from estimating_tools.heavybook.tests import _readback as H

CHECKS = "Checks"


def _check_row(ws, kind, desc, measure):
    for r in range(1, ws.max_row + 1):
        if (ws[f"{CK.KIND}{r}"].value, ws[f"{CK.DESC}{r}"].value,
                ws[f"{CK.MEASURE}{r}"].value) == (kind, desc, measure):
            return r
    raise LookupError((kind, desc, measure))


def test_figures_are_what_the_build_writes():
    wb = model.parse(H.fixture_doc())
    figs = checks.figures(wb, style.load_style())
    excavate = next(v for (k, _c, d, m), v in figs.items()
                    if (k, d, m) == ("activity", "Excavate", "cost"))
    assert excavate == wb.activity(1).cost


def test_a_refresh_brings_the_checks_figures_and_export_line_up_to_date(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    fresh = H.fixture_doc()
    act = next(a for a in fresh["activities"] if a["id"] == 1)
    act["cost"] = "11111.00"
    res = next(r for r in fresh["resources"] if r["id"] == 1)
    res.update({"quantity": "32.000", "v": "1" * 16})
    report = hb_pack.pack().refresh(path, fresh)
    assert report.clean
    ws = H.open_book(path)[CHECKS]
    assert ws[f"{CK.BIDSHEET}{_check_row(ws, 'activity', 'Excavate', 'cost')}"].value == 11111
    assert "2026-10-20T09:00:00Z" not in ws["A2"].value
    assert ws["A2"].value.startswith("Exported from www.bidsheet.ai -- estimate")


def test_a_change_in_the_cost_shares_needs_a_rebuild(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    before = path.read_bytes()
    fresh = H.fixture_doc()
    fresh["shares"][0]["fraction"] = "0.5"
    report = hb_pack.pack().refresh(path, fresh)
    assert any("_shares" in s for s in report.structural)
    assert path.read_bytes() == before


def test_a_patch_updates_the_export_line_too(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    row = H.cr_row(ws, "RESOURCE", 3)
    ws[f"{CR.QTY}{row}"] = 9
    H.save_book(wb, path)
    p = hb_pack.pack()
    read = p.read(path)
    fresh = H.fixture_doc()
    next(r for r in fresh["resources"] if r["id"] == 3).update(quantity="9.000",
                                                                v="f" * 16)
    report = p.patch(path, read.change_set, ApplyResult.from_plan(
        {"created": {}, "deleted": [], "totals": {}}, dry_run=False), fresh)
    assert report.baseline_replaced
    assert "2026-10-20T09:00:00Z" not in H.open_book(path)[CHECKS]["A2"].value


X14 = (b'<extLst><ext uri="{CCE6A557-97BC-4b89-ADB6-D9C93CAAB3DF}" '
       b'xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main">'
       b'<x14:dataValidations count="1" '
       b'xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main">'
       b'<x14:dataValidation type="list" allowBlank="1">'
       b'<x14:formula1><xm:f>Rates!$B$3:$B$3</xm:f></x14:formula1>'
       b'<xm:sqref>AK5:AK40</xm:sqref></x14:dataValidation></x14:dataValidations>'
       b'</ext></extLst>')


def _decorated_book(tmp_path):
    """The spec's Patch fixture on HeavyBook: an extra sheet with a chart, a
    note in a spare column, a custom number format, a data-validation
    extension -- and an edit (resource 3 pasted into activity 1) to apply."""
    path = H.build_book(H.fixture_doc(), tmp_path / "deco.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    H.insert_copies(ws, H.cr_row(ws, "RESOURCE", 3), H.cr_row(ws, "RESOURCE", 3),
                    H.block_end(ws, 1))
    ws["AL30"].comment = Comment("estimator: ask the sub about this", "est")
    ws["AL31"] = 0.25
    ws["AL31"].number_format = '0.00" ea"'
    notes = wb.create_sheet("Estimator notes")
    notes["A1"] = "kept as typed"
    chart = BarChart()
    chart.add_data(Reference(ws, min_col=18, min_row=5, max_row=20))
    notes.add_chart(chart, "B3")
    H.save_book(wb, path)
    parts = _parts(path)
    sheet = _sheet_part(path, H.CR_TAB)
    parts[sheet] = parts[sheet].replace(b"</worksheet>", X14 + b"</worksheet>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in parts.items():
            z.writestr(n, data)
    return path


def _parts(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def _sheet_part(path, title):
    with zipfile.ZipFile(path) as z:
        return writer._sheet_parts(z)[title]


def test_the_spec_patch_fixture_changes_only_the_written_cells_and_the_stamp(tmp_path):
    path = _decorated_book(tmp_path)
    p = hb_pack.pack()
    result = p.read(path)
    (where,) = result.change_set.rows
    fresh = H.fixture_doc()
    copy = dict(next(r for r in fresh["resources"] if r["id"] == 3))
    copy.update({"id": 41, "activity_id": 1, "v": "deadbeefdeadbeef"})
    fresh["resources"].append(copy)
    before = _parts(path)
    report = p.patch(path, result.change_set, ApplyResult.from_plan(
        {"created": {result.change_set.ops[0]["ref"]: "resource:41"}, "deleted": [],
         "totals": {}}, dry_run=False), fresh)
    assert report.baseline_replaced
    after = _parts(path)
    written = {_sheet_part(path, t) for t in (H.CR_TAB, CHECKS, "_wb")} | {"docProps/custom.xml"}
    # Cached formula values may change on any sheet (#370); nothing else may.
    assert H.changed_beyond_cached_values(before, after) <= written
    assert b"<xm:sqref>AK5:AK40</xm:sqref>" in after[_sheet_part(path, H.CR_TAB)]
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.ID}{where['row']}"].value == 41
    assert ws[f"{CR.V}{where['row']}"].value == "deadbeefdeadbeef"
    assert ws["AL30"].comment.text == "estimator: ask the sub about this"
    assert ws["AL31"].number_format == '0.00" ea"'
    assert Decimal(str(ws["AL31"].value)) == Decimal("0.25")
