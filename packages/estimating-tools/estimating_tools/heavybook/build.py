"""Build a HeavyBook workbook from a get_estimate_workbook payload.

``build(doc, style=..., exported_at=..., host=...)`` returns an openpyxl
Workbook; ``save(wb, path)`` writes it byte-deterministically (the same
payload and stamp always give the same bytes). Nothing here talks to
BidSheet.ai: the skill fetches the payload over MCP and hands the JSON in.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.packaging.custom import StringProperty
from openpyxl.workbook.defined_name import DefinedName

from estimating_tools.estimate_spec.build import sheet_qualified
from estimating_tools.exchange import baseline
from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange import model
from estimating_tools.heavybook import FORMAT_NAME, FORMAT_VERSION, layout
from estimating_tools.heavybook.columns import BF
from estimating_tools.heavybook.sheets.bid_form import write_bid_form
from estimating_tools.heavybook.sheets.checks import write_checks
from estimating_tools.heavybook.sheets.common import last_column_letter, set_value
from estimating_tools.heavybook.sheets.cost_report import write_cost_report
from estimating_tools.heavybook.sheets.crews import write_crews
from estimating_tools.heavybook.sheets.flat import write_flat
from estimating_tools.heavybook.sheets.rates import write_rates
from estimating_tools.heavybook.sheets.recap import write_recap
from estimating_tools.heavybook.sheets.schedule import CAL_SHEET, write_calendar, write_schedule
from estimating_tools.heavybook.sheets.shares import SHEET as SHARES_SHEET
from estimating_tools.heavybook.sheets.shares import write_shares
from estimating_tools.heavybook.sheets.templates import SHEET as TEMPLATES_SHEET
from estimating_tools.heavybook.sheets.templates import write_templates
from estimating_tools.xlcalc import cache_or_warn
from estimating_tools.xlsx_determinism import BUILD_STAMP, normalize_xlsx

WB_SHEET = "_wb"


def build(doc, *, style, exported_at, host) -> Workbook:
    data = model.parse(doc)
    # The payload as built (``merge_pages``' output when paged -- plain
    # ``json.loads`` data, no Decimal), for read-back. Encoded first: a value
    # JSON cannot carry (NaN in a field the model never reads) is refused
    # before any sheet is written.
    chunks, meta = baseline.encode(doc)
    plan = layout.plan(data, style)
    checks_stamp = {"exported_at": exported_at, "host": host}

    book = Workbook()
    bid_ws = book.active
    bid_ws.title = plan.tabs["bid_form"]
    recap_ws = book.create_sheet(plan.tabs["recap"])
    cost_ws = book.create_sheet(plan.tabs["cost_report"])
    crews_ws = book.create_sheet(plan.tabs["crews"])
    rates_ws = book.create_sheet(plan.tabs["rates"])
    schedule_ws = book.create_sheet(plan.tabs["schedule"])
    checks_ws = book.create_sheet(plan.tabs["checks"])
    flat_ws = book.create_sheet(plan.tabs["flat"])
    shares_ws = book.create_sheet(SHARES_SHEET)
    cal_ws = book.create_sheet(CAL_SHEET)
    wb_ws = book.create_sheet(WB_SHEET)
    tpl_ws = book.create_sheet(TEMPLATES_SHEET)

    write_bid_form(bid_ws, plan, data, style)
    write_recap(recap_ws, plan, data, style)
    write_cost_report(cost_ws, plan, data, style)
    write_crews(crews_ws, plan, data, style)
    write_rates(rates_ws, plan, data, style)
    write_schedule(schedule_ws, plan, data, style)
    checks = write_checks(checks_ws, plan, data, style, checks_stamp)
    write_flat(flat_ws, plan, data, style)
    write_shares(shares_ws, plan, data)
    write_calendar(cal_ws, plan)
    templates = write_templates(tpl_ws, plan, style)
    book.active = 0

    wb_ws.sheet_state = "hidden"
    stamp_text = exchange_stamp.dumps(layout.stamp_doc(
        plan, data, style, meta, host=host, exported_at=exported_at, payload=doc))
    if len(stamp_text) > exchange_stamp.CELL_LIMIT:
        # openpyxl would write a truncated cell and the book would be refused
        # on read; ``stamp.make`` has already dropped a page's item ids.
        raise baseline.BaselineError(
            f"the book's stamp is {len(stamp_text)} characters; Excel holds "
            f"{exchange_stamp.CELL_LIMIT} per cell -- build fewer items per page or a "
            "smaller style")
    wb_ws["A1"] = stamp_text
    for n, chunk in enumerate(chunks, start=1):
        # Pinned to text: a last chunk of base64 padding ("==") would
        # otherwise be stored as a formula.
        set_value(wb_ws[f"B{n}"], chunk)

    names = {
        "hc.cost_report": (plan.tabs["cost_report"],
                           (f"$A${layout.HEADER_ROW}:${last_column_letter('cost_report')}"
                            f"${max(plan.cost_report_last_row, layout.HEADER_ROW)}")),
        "hc.checks": (plan.tabs["checks"],
                      f"$A${layout.HEADER_ROW}:$I${max(checks['last'], layout.HEADER_ROW)}"),
        "hc.layout": (WB_SHEET, "$A$1"),
        exchange_stamp.NAME: (WB_SHEET, "$A$1"),
        "hc.bid_form": (plan.tabs["bid_form"],
                        f"$A${BF.HEADER_ROW}:${last_column_letter('bid_form')}"
                        f"${plan.bid_items_span[1]}"),
    }
    if plan.bid_total_rows:      # always, the implicit total included
        names["hc.bid_totals"] = (plan.tabs["bid_form"],
                                  f"$A${plan.bid_total_rows[0].row}:${BF.TOTAL}"
                                  f"${plan.bid_total_rows[-1].row}")
    if plan.schedule_rows:
        names["hc.schedule"] = (plan.tabs["schedule"],
                                f"$A${layout.HEADER_ROW}:${last_column_letter('schedule')}"
                                f"${max(plan.schedule_rows.values())}")
    for key, (first, last) in templates.items():
        names[layout.TEMPLATE_NAMES[key]] = (TEMPLATES_SHEET, f"${first}:${last}")
    for name, (sheet, ref) in sorted(names.items()):
        book.defined_names[name] = DefinedName(name, attr_text=sheet_qualified(sheet, ref))

    props = {"estimate_format": f"{FORMAT_NAME} {FORMAT_VERSION}",
             "estimate_id": str(data.estimate.id), "bidsheet_host": host,
             "exported_at": exported_at, "style_pack": f"{style.name} {style.version}",
             "source_sha": data.source_sha}
    for name, value in props.items():
        book.custom_doc_props.append(StringProperty(name=name, value=value))
    book.properties.created = BUILD_STAMP
    book.properties.modified = BUILD_STAMP
    return book


def _match_new_file_mode(tmp):
    """``mkstemp`` creates the temp file 0600; give it the mode a normally
    created file gets (0666 less the umask). The umask can only be read by
    setting it, so it is set and restored at once. On Windows chmod only
    toggles read-only, which this leaves off."""
    old = os.umask(0)
    os.umask(old)
    os.chmod(tmp, 0o666 & ~old)


def save(book, path) -> None:
    """Write atomically: a temp file beside ``path`` is saved, normalized and
    given its formulas' cached values (#370), then moved over it. On any
    failure the temp file is removed and an existing ``path`` is left as it
    was; a failure to cache values only warns."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".xlsx.tmp", dir=path.parent)
    os.close(fd)
    try:
        book.save(tmp)
        normalize_xlsx(tmp)
        cache_or_warn(tmp, label=path.name)
        _match_new_file_mode(tmp)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass
        raise
