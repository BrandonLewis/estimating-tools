"""Recap: one row per item -- man-hours, direct cost by type, unit cost and
bid price -- all formulas over the Cost Report, _shares and the Bid Form.
Read-only."""
from __future__ import annotations

from estimating_tools.heavycivil import formulas as F
from estimating_tools.heavycivil.columns import BF, CR, RC
from estimating_tools.heavycivil.layout import FIRST_ROW, SHARES_FIRST_ROW
from estimating_tools.heavycivil.sheets.common import factory, put, setup_sheet
from estimating_tools.heavycivil.sheets.shares import SHEET as SHARES_SHEET


def write_recap(ws, plan, wb, style):
    sf = factory(style)
    setup_sheet(ws, sf, style, "recap", title="Recap", subtitle=wb.estimate.name)
    cost_tab, bid_tab = plan.tabs["cost_report"], plan.tabs["bid_form"]
    for item in wb.items:
        r = plan.recap_rows[item.id]
        cr, bf = plan.item_rows[item.id].row, plan.bid_rows[item.id].row
        put(ws, sf, f"{RC.CODE}{r}", item.item_number, "label_bold")
        put(ws, sf, f"{RC.DESC}{r}", item.description, "label")
        put(ws, sf, f"{RC.QTY}{r}", F.recap_ref(cost_tab, CR.H2, cr), "calc_qty")
        put(ws, sf, f"{RC.UNIT}{r}", item.unit, "calc_text")
        put(ws, sf, f"{RC.MH}{r}", F.recap_manhours(cr, cost_tab, SHARES_SHEET, SHARES_FIRST_ROW,
                                                   plan.shares_last_row), "calc_hours")
        for (_, rc_col), (_, cr_col) in zip(RC.SPLIT, CR.SPLIT):
            put(ws, sf, f"{rc_col}{r}", F.recap_ref(cost_tab, cr_col, cr), "calc_money")
        put(ws, sf, f"{RC.DIRECT}{r}", F.recap_ref(cost_tab, CR.TOTAL, cr), "calc_money")
        put(ws, sf, f"{RC.UCOST}{r}", F.recap_unit_cost(r), "calc_rate")
        put(ws, sf, f"{RC.PRICE}{r}", F.recap_ref(bid_tab, BF.PRICE, bf), "calc_money")
        put(ws, sf, f"{RC.TOTAL}{r}", F.recap_ref(bid_tab, BF.TOTAL, bf), "calc_money")
        put(ws, None, f"{RC.KIND}{r}", "ITEM")
        put(ws, None, f"{RC.ID}{r}", item.id)
    t = plan.recap_total_row
    # Every item's direct cost, an excluded one's too (the bid total
    # column leaves those out: they have no bid price).
    put(ws, sf, f"{RC.CODE}{t}", "Total (all items, incl. excluded)", "total_label")
    put(ws, sf, f"{RC.MH}{t}", F.column_sum(RC.MH, FIRST_ROW, t - 1), "total_hours")
    for col in (RC.LAB, RC.EQP, RC.MAT, RC.SUB, RC.OTH, RC.DIRECT, RC.TOTAL):
        put(ws, sf, f"{col}{t}", F.column_sum(col, FIRST_ROW, t - 1), "total_money")
