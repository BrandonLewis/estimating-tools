"""Flat: one row per resource line and per crew charge, as an Excel Table
(``hc_flat``) for pivots and filters. Every figure is a live formula over the
Cost Report; the cost column sums to the activities' own extended costs."""
from __future__ import annotations

from openpyxl.worksheet.table import Table, TableStyleInfo

from estimating_tools.heavycivil import formulas as F
from estimating_tools.heavycivil.columns import CR, FL
from estimating_tools.heavycivil.layout import HEADER_ROW
from estimating_tools.heavycivil.sheets.common import factory, put, setup_sheet

TABLE = "hc_flat"


def write_flat(ws, plan, wb, style):
    sf = factory(style)
    setup_sheet(ws, sf, style, "flat", title="Flat", subtitle=wb.estimate.name)
    cost_tab = plan.tabs["cost_report"]
    for row in plan.flat_rows:
        r = row.row
        a = wb.activity(row.parent_id)
        act = plan.activity_rows[a.id].row
        put(ws, sf, f"{FL.ITEM}{r}", wb.item(a.item_id).item_number, "label")
        put(ws, sf, f"{FL.CODE}{r}", a.code, "label")
        put(ws, sf, f"{FL.ACTIVITY}{r}", a.name, "label")
        if row.kind == "CREW_CHARGE":
            crew = wb.crew(a.crew_id)
            put(ws, sf, f"{FL.LINE}{r}", f"Crew: {crew.name if crew else a.crew_id}", "label")
            put(ws, sf, f"{FL.TYPE}{r}", "labor", "calc_text")
            put(ws, sf, f"{FL.QTY}{r}", F.recap_ref(cost_tab, CR.SHIFTS, act), "calc_qty")
            put(ws, sf, f"{FL.UNIT}{r}", "shifts", "calc_text")
            put(ws, sf, f"{FL.MH}{r}", F.flat_crew_hours(cost_tab, act), "calc_hours")
            put(ws, sf, f"{FL.COST}{r}", F.flat_crew_cost(cost_tab, act), "calc_money")
        else:
            res, rr = row.obj, plan.resource_rows[row.id].row
            put(ws, sf, f"{FL.LINE}{r}", res.name, "label")
            put(ws, sf, f"{FL.TYPE}{r}", F.recap_ref(cost_tab, CR.TYPE, rr), "calc_text")
            put(ws, sf, f"{FL.QTY}{r}", F.recap_ref(cost_tab, CR.QTY, rr), "calc_qty")
            put(ws, sf, f"{FL.UNIT}{r}", res.unit, "calc_text")
            put(ws, sf, f"{FL.MH}{r}", F.flat_resource_hours(cost_tab, rr, act), "calc_hours")
            put(ws, sf, f"{FL.COST}{r}", F.flat_resource_cost(cost_tab, rr, act), "calc_money")
        put(ws, None, f"{FL.KIND}{r}", row.kind)
        put(ws, None, f"{FL.ID}{r}", row.id)
    if plan.flat_rows:
        last = plan.flat_rows[-1].row
        table = Table(displayName=TABLE, ref=f"{FL.ITEM}{HEADER_ROW}:{FL.COST}{last}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
        ws.add_table(table)
