"""Bid Form: the estimate's markup inputs and derived TEC / markup / bid
factor (rows 4-10, column C), the items by section with their scope and bid
unit price override inputs, and one row per bid total definition. The
item's unit price and quantity override are edited on the Cost Report; the
bid quantity is the schedule quantity (BidSheet.ai prices bids on it)."""
from __future__ import annotations

from openpyxl.worksheet.datavalidation import DataValidation

from estimating_tools.heavycivil import formulas as F
from estimating_tools.heavycivil.columns import BF
from estimating_tools.heavycivil.layout import _covers, primary_total
from estimating_tools.heavycivil.sheets.common import factory, put, setup_sheet

_LABELS = {"markup_percentage": "Markup %", "markup_amount": "Markup $",
           "indirect_cost": "Indirect cost (as of export)",
           "direct_cost": "Direct cost (primary bid)", "markup_total": "Markup",
           "bid_factor": "Bid factor", "excluded_cost": "Excluded cost"}

#: An item's scope choices (``EstimateItem.scope``): the Scope column's
#: drop-down, and the spelling read-back normalises a typed scope to.
SCOPES = ("included", "excluded")


def _estimate(ws, sf, plan, wb):
    e, rows = wb.estimate, plan.bid_inputs
    first, last = plan.bid_items_span
    v = BF.VALUE
    for name, r in rows.items():
        put(ws, sf, f"A{r}", _LABELS[name], "label_bold")
    put(ws, sf, f"{v}{rows['markup_percentage']}", e.markup_percentage, "input_pct")
    put(ws, sf, f"{v}{rows['markup_amount']}", e.markup_amount, "input_money")
    put(ws, sf, f"{v}{rows['indirect_cost']}", e.indirect_cost, "export_money")
    put(ws, sf, f"{v}{rows['direct_cost']}", F.bid_direct_cost(first, last), "calc_money")
    put(ws, sf, f"{v}{rows['markup_total']}", F.bid_markup_total(), "calc_money")
    put(ws, sf, f"{v}{rows['bid_factor']}", F.bid_factor(), "calc_factor")
    put(ws, sf, f"{v}{rows['excluded_cost']}", F.bid_excluded_cost(first, last), "calc_money")
    # Every estimate row is marked by name (T), so read-back finds it by its
    # marker, not its address; the first also identifies the estimate.
    for name, r in rows.items():
        put(ws, None, f"{BF.KIND}{r}", "BID_INPUT" if name in BF.INPUTS else "BID_FIGURE")
        put(ws, None, f"{BF.INPUT}{r}", name)
    r0 = rows["markup_percentage"]
    put(ws, None, f"{BF.KIND}{r0}", "ESTIMATE")
    put(ws, None, f"{BF.ID}{r0}", e.id)
    put(ws, None, f"{BF.V}{r0}", e.v)


def _item(ws, sf, plan, row, primary, cost_tab):
    item, r = row.obj, row.row
    cr = plan.item_rows[item.id].row
    put(ws, sf, f"{BF.CODE}{r}", item.item_number, "label_bold")
    put(ws, sf, f"{BF.DESC}{r}", item.description, "label")
    put(ws, sf, f"{BF.SCHED}{r}", item.schedule_label, "calc_text")
    put(ws, sf, f"{BF.QTY}{r}", item.schedule_quantity, "export_value")
    put(ws, sf, f"{BF.UNIT}{r}", item.unit, "calc_text")
    put(ws, sf, f"{BF.SCOPE}{r}", item.scope, "input_select")
    put(ws, sf, f"{BF.OVERRIDE}{r}", item.bid_unit_price_override, "input_money")
    put(ws, sf, f"{BF.PRICE}{r}", F.bid_unit_price(r), "calc_money")
    put(ws, sf, f"{BF.TOTAL}{r}", F.bid_item_total(r), "calc_money")
    put(ws, None, f"{BF.KIND}{r}", "ITEM_BID")
    put(ws, None, f"{BF.ID}{r}", item.id)
    put(ws, None, f"{BF.V}{r}", item.v)
    put(ws, None, f"{BF.SCHED_ID}{r}", item.schedule_id if item.schedule_id is not None else -1)
    put(ws, None, f"{BF.COST}{r}", F.bid_item_cost(cost_tab, cr))
    put(ws, None, f"{BF.PRIMARY}{r}",
        1 if primary is not None and _covers(primary, item.schedule_id) else 0)
    put(ws, None, f"{BF.PRICED}{r}", F.bid_priced(cost_tab, cr))
    put(ws, None, f"{BF.PCOST}{r}", F.bid_primary_cost(r))
    put(ws, None, f"{BF.XPRICE}{r}", item.bid_unit_price)
    put(ws, None, f"{BF.XTOTAL}{r}", item.bid_total)


def write_bid_form(ws, plan, wb, style):
    sf = factory(style)
    setup_sheet(ws, sf, style, "bid_form", title="Bid Form",
                subtitle=f"{wb.estimate.name} -- {wb.estimate.project_title}",
                header_row=BF.HEADER_ROW)
    _estimate(ws, sf, plan, wb)
    first, last = plan.bid_items_span
    cost_tab = plan.tabs["cost_report"]
    for sec in plan.bid_sections:
        if sec.kind == "SECTION":
            put(ws, sf, f"{BF.CODE}{sec.row}", sec.obj.name, "section_text")
            put(ws, None, f"{BF.KIND}{sec.row}", "SECTION")
            put(ws, None, f"{BF.ID}{sec.row}", sec.id)
            put(ws, None, f"{BF.V}{sec.row}", sec.v)
        else:
            put(ws, sf, f"{BF.CODE}{sec.row}", "Other items", "section_text")
            put(ws, None, f"{BF.KIND}{sec.row}", "GROUP")
    primary = primary_total(wb)
    for row in plan.bid_rows.values():
        _item(ws, sf, plan, row, primary, cost_tab)
    if plan.bid_rows:
        dv = DataValidation(type="list", formula1='"' + ",".join(SCOPES) + '"',
                            allow_blank=False)
        dv.add(f"{BF.SCOPE}{first}:{BF.SCOPE}{last}")
        ws.add_data_validation(dv)
    if plan.bid_total_rows:
        heading = plan.bid_total_rows[0].row - 1
        put(ws, sf, f"{BF.CODE}{heading}", "Bid totals", "total_label")
    for row in plan.bid_total_rows:
        t, r = row.obj, row.row
        put(ws, sf, f"{BF.CODE}{r}", t.name + (" (primary)" if t.is_primary else ""),
            "label_bold")
        put(ws, sf, f"{BF.TOTAL}{r}",
            F.bid_total_amount(schedule_ids=t.schedule_ids,
                               includes_unscheduled=t.includes_unscheduled,
                               first=first, last=last), "total_money")
        put(ws, None, f"{BF.KIND}{r}", "BID_TOTAL")
        put(ws, None, f"{BF.ID}{r}", t.id)
