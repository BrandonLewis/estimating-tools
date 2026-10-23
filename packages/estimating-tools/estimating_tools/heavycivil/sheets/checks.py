"""Checks: Excel against BidSheet.ai, row by row, plus BidSheet.ai's own
warnings and the export stamp. Freshly built, every row reads OK; after an
estimator's edits, the DIFF rows are what those edits moved."""
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal

from openpyxl.formatting.rule import CellIsRule, FormulaRule

from estimating_tools.heavycivil import formulas as F
from estimating_tools.heavycivil.columns import BF, CK, CR, CW, SC
from estimating_tools.heavycivil.layout import FIRST_ROW
from estimating_tools.heavycivil.sheets.common import factory, put, setup_sheet
from estimating_tools.heavycivil.sheets.cost_report import in_bid_fraction

CENT = Decimal("0.005")
#: ``live_bid_factor`` is stored to 10 places.
FACTOR_TOL = Decimal("0.0000000005")
#: Excel's day zero: a date cell compares as its serial from here.
EXCEL_EPOCH = date(1899, 12, 30)
CHANGED = "CHANGED -- re-export to reweight"
#: Cell styles (Excel, BidSheet.ai, difference, tolerance) by measure; any
#: other measure is money.
_FORMATS = {"factor": ("calc_factor_fine", "export_factor_fine", "calc_factor_fine",
                       "calc_factor_fine"),
            "finish": ("calc_date", "export_date", "calc_qty", "calc_qty")}
_MONEY = ("calc_money", "export_money", "calc_money", "calc_money")


def _ref(ref):
    return f'IF({ref}="",0,{ref})'


def _rows(plan, wb):
    """(kind, code, description, measure, excel_formula, bidsheet_value, tolerance) per check.

    An activity's payload ``cost`` is the in-bid part of its own cost (the
    shares to excluded items are dropped), so Excel's total is scaled by the
    in-bid fraction (``AF``) before comparing. With no in-bid share there is
    nothing to compare the cost to (status "export"). Man-hours are never
    reduced, so they always compare whole.

    A stepped activity also checks its live Shifts (J, summed from its step
    rows) against the stored ``duration_shifts``. BidSheet.ai does not
    always restamp that figure (bulk-created steps, an ``hours_per_shift``
    edit), so a stale stamp reads DIFF on a fresh book -- a true signal."""
    cost_tab, crews_tab = plan.tabs["cost_report"], plan.tabs["crews"]
    out = []
    for a in wb.activities:
        r = plan.activity_rows[a.id].row
        f = in_bid_fraction(wb, a)
        if f == 0:
            out.append(("activity", a.code, a.name, "cost", None, a.cost, None))
        else:
            # A split share is rounded to the cent by largest remainder, so
            # the shares left can sit a cent each from R x f.
            n = len(wb.shares_of_activity(a.id))
            tol = CENT if f == 1 else CENT + Decimal("0.01") * n
            excel = _ref(F.qualified(cost_tab, CR.TOTAL, r))
            if f != 1:
                excel += f"*{F.qualified(cost_tab, CR.H1, r)}"
            out.append(("activity", a.code, a.name, "cost", excel, a.cost, tol))
        out.append(("activity", a.code, a.name, "man-hours", _ref(F.qualified(cost_tab, CR.MH, r)),
                    a.manhours, CENT))
        if a.steps:
            out.append(("activity", a.code, a.name, "shifts",
                        _ref(F.qualified(cost_tab, CR.SHIFTS, r)), a.duration_shifts, CENT))
    for res in wb.resources:
        r = plan.resource_rows[res.id].row
        out.append(("resource", "", res.name, "cost", _ref(F.qualified(cost_tab, CR.H2, r)),
                    res.cost, CENT))
    split = Counter(s.activity_id for s in wb.shares)
    for item in wb.items:
        r = plan.item_rows[item.id].row
        if item.scope == "excluded":
            out.append(("item", item.item_number, item.description, "cost", None, item.total, None))
            continue
        n_split = sum(1 for s in wb.shares if s.item_id == item.id and split[s.activity_id] > 1)
        out.append(("item", item.item_number, item.description, "unit price",
                    _ref(F.qualified(cost_tab, CR.H4, r)), item.calculated_unit_price,
                    CENT + Decimal("0.01") * n_split))
        # BidSheet.ai's ``calculate_total``: quantity x (manual price, else the
        # calculated unit price) -- not the stored ``total``, which rounds the
        # unrounded breakdown and can sit cents away (fixture item 12:
        # 14657.38 stored vs 10 x 1465.74 = 14657.40).
        qty = item.quantity or Decimal(0)
        price = (item.estimated_unit_price if item.estimated_unit_price is not None
                 else (item.calculated_unit_price or Decimal(0)))
        out.append(("item", item.item_number, item.description, "cost",
                    _ref(F.qualified(cost_tab, CR.TOTAL, r)), price * qty,
                    CENT + (Decimal("0.01") * abs(qty) if n_split else Decimal(0))))
    for crew in wb.crews:
        r = plan.crew_rows[crew.id].row
        out.append(("crew", crew.code, crew.name, "$/hr",
                    _ref(F.qualified(crews_tab, CW.RATE, r)),
                    crew.hourly_rate, CENT))
    return out


def _bid_rows(plan, wb):
    """The Bid Form against BidSheet.ai: the estimate figures, each item's
    bid unit price and total, and each bid total definition. TEC, markup and
    the excluded cost compare to the stored totals; the factor to
    ``live_bid_factor`` (what ``bid_totals`` used). The item bid prices use
    the stored ``bid_factor``: equal unless the stored totals are stale,
    which then reads DIFF."""
    bid_tab, e = plan.tabs["bid_form"], wb.estimate
    rows = plan.bid_inputs

    def cell(col, r):
        return _ref(F.qualified(bid_tab, col, r))

    out = [
        ("estimate", "", "Direct cost (primary bid)", "cost",
         cell(BF.VALUE, rows["direct_cost"]), e.total_estimated_cost, CENT),
        ("estimate", "", "Markup", "cost", cell(BF.VALUE, rows["markup_total"]),
         e.markup_total, CENT),
        ("estimate", "", "Bid factor", "factor", cell(BF.VALUE, rows["bid_factor"]),
         e.live_bid_factor, FACTOR_TOL),
        ("estimate", "", "Excluded cost", "cost", cell(BF.VALUE, rows["excluded_cost"]),
         e.excluded_cost, CENT),
    ]
    for item in wb.items:
        r = plan.bid_rows[item.id].row
        out.append(("bid item", item.item_number, item.description, "bid unit price",
                    cell(BF.PRICE, r), item.bid_unit_price, CENT))
        out.append(("bid item", item.item_number, item.description, "bid total",
                    cell(BF.TOTAL, r), item.bid_total, CENT))
    for row in plan.bid_total_rows:
        t = row.obj
        # The implicit total (no definitions in the payload) has no amount.
        ref = None if t.amount is None else cell(BF.TOTAL, row.row)
        out.append(("bid total", "", t.name, "bid total", ref, t.amount, CENT))
    return out


def _schedule_rows(plan, wb):
    """Each dated activity's live finish against the export's, as Excel
    serials (a date cell compares as its serial)."""
    sched_tab = plan.tabs["schedule"]
    out = []
    for activity_id, r in plan.schedule_rows.items():
        a = wb.activity(activity_id)
        serial = Decimal((date.fromisoformat(a.finish_date) - EXCEL_EPOCH).days)
        out.append(("schedule", a.code, a.name, "finish",
                    _ref(F.qualified(sched_tab, SC.FINISH, r)), serial, Decimal("0.5")))
    return out


def _element_rows(plan, wb):
    """(code, description, excel_ref, exported override) per element quantity.

    An override edit is read back, but Excel cannot re-weight the share
    fractions it drives, so it is flagged rather than priced."""
    cost_tab = plan.tabs["cost_report"]
    out = []
    for e in sorted(wb.elements, key=lambda e: (e.display_order, e.id)):
        for q in sorted(e.quantities, key=lambda q: q.key):
            r = plan.quantity_rows[(e.id, q.key)].row
            out.append((q.key, f"{e.name} -- {q.label}", F.qualified(cost_tab, CR.QTY, r),
                        q.override))
    return out


def write_checks(ws, plan, wb, style, stamp):
    sf = factory(style)
    setup_sheet(ws, sf, style, "checks", title="Checks",
                subtitle=(f"Exported from {stamp['host']} -- estimate {wb.estimate.name} "
                          f"(#{wb.estimate.id}) at {stamp['exported_at']}"))
    rows = _rows(plan, wb) + _bid_rows(plan, wb) + _schedule_rows(plan, wb)
    elements = _element_rows(plan, wb)
    last = FIRST_ROW + len(rows) + len(elements) - 1
    status_range = f"{CK.STATUS}{FIRST_ROW}:{CK.STATUS}{max(last, FIRST_ROW)}"
    put(ws, sf, "D3", "Rows differing:", "label_bold")
    put(ws, sf, "E3", F.Formula(f'=COUNTIF({status_range},"DIFF")'), "status")
    put(ws, sf, "F3", "Edits needing re-export:", "label_bold")
    put(ws, sf, "G3", F.Formula(f'=COUNTIF({status_range},"CHANGED*")'), "status")
    for offset, (kind, code, desc, measure, ref, value, tol) in enumerate(rows):
        r = FIRST_ROW + offset
        put(ws, sf, f"{CK.KIND}{r}", kind, "label")
        put(ws, sf, f"{CK.CODE}{r}", code, "label")
        put(ws, sf, f"{CK.DESC}{r}", desc, "label")
        put(ws, sf, f"{CK.MEASURE}{r}", measure, "calc_text")
        s_excel, s_export, s_diff, s_tol = _FORMATS.get(measure, _MONEY)
        put(ws, sf, f"{CK.BIDSHEET}{r}", value if value is not None else Decimal(0), s_export)
        if ref is None:
            put(ws, sf, f"{CK.STATUS}{r}", "export", "status")
            continue
        put(ws, sf, f"{CK.EXCEL}{r}", F.Formula(f"={ref}"), s_excel)
        put(ws, sf, f"{CK.DIFF}{r}", F.Formula(f"={CK.EXCEL}{r}-{CK.BIDSHEET}{r}"), s_diff)
        put(ws, sf, f"{CK.TOL}{r}", tol, s_tol)
        put(ws, sf, f"{CK.STATUS}{r}",
            F.Formula(f'=IF(ABS({CK.DIFF}{r})<={CK.TOL}{r},"OK","DIFF")'), "status")
    for offset, (code, desc, ref, override) in enumerate(elements):
        r = FIRST_ROW + len(rows) + offset
        e, x = f"{CK.EXCEL}{r}", f"{CK.BIDSHEET}{r}"
        put(ws, sf, f"{CK.KIND}{r}", "element", "label")
        put(ws, sf, f"{CK.CODE}{r}", code, "label")
        put(ws, sf, f"{CK.DESC}{r}", desc, "label")
        put(ws, sf, f"{CK.MEASURE}{r}", "override", "calc_text")
        put(ws, sf, e, F.Formula(f'=IF({ref}="","",{ref})'), "calc_qty")
        put(ws, sf, x, override, "export_value")
        put(ws, sf, f"{CK.STATUS}{r}",
            F.Formula(f'=IF(AND({e}="",{x}=""),"OK",IF({e}={x},"OK","{CHANGED}"))'),
            "status")
    ok_font, ok_fill = sf.dxf("status_ok")
    bad_font, bad_fill = sf.dxf("status_bad")
    ws.conditional_formatting.add(status_range, CellIsRule(operator="equal", formula=['"OK"'],
                                                           font=ok_font, fill=ok_fill))
    ws.conditional_formatting.add(status_range, CellIsRule(operator="equal", formula=['"DIFF"'],
                                                           font=bad_font, fill=bad_fill))
    ws.conditional_formatting.add(status_range, FormulaRule(
        formula=[f'LEFT({CK.STATUS}{FIRST_ROW},7)="CHANGED"'], font=bad_font, fill=bad_fill))
    r = last + 2
    warnings = [(a, w) for a in wb.activities for w in a.warnings]
    put(ws, sf, f"{CK.KIND}{r}", "BidSheet.ai warnings" if warnings else "No BidSheet.ai warnings",
        "label_bold")
    for a, w in warnings:
        r += 1
        put(ws, sf, f"{CK.CODE}{r}", a.code, "label")
        put(ws, sf, f"{CK.DESC}{r}", f"{a.name}: {w}", "note")
    missing = sorted({a.crew_id for a in wb.activities
                      if a.crew_id is not None and wb.crew(a.crew_id) is None})
    for crew_id in missing:
        r += 1
        put(ws, sf, f"{CK.DESC}{r}", f"Crew {crew_id} is not in this export: its cost is shown "
                                     "as of export.", "note")
    # A missing crew's labour is priced per shift as of export; with no
    # shifts at export there is no per-shift figure (H3/H4 are 0).
    for a in wb.activities:
        if (a.crew_id is not None and wb.crew(a.crew_id) is None and not a.steps
                and not a.duration_shifts):
            r += 1
            put(ws, sf, f"{CK.CODE}{r}", a.code, "label")
            put(ws, sf, f"{CK.DESC}{r}", f"{a.name}: crew not in this export and no shifts at "
                                         "export: typing Shifts prices labour at 0 -- re-export",
                "note")
    return {"first": FIRST_ROW, "last": last}
