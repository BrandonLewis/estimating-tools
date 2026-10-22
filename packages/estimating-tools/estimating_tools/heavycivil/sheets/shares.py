"""Hidden ``_shares``: one row per allocation share. The money is live (it
follows its activity's Cost Report total) but the fraction is frozen at
export -- the allocation that produced it (element quantities, spreads)
is BidSheet.ai's to redo."""
from __future__ import annotations

from collections import Counter

from estimating_tools.heavycivil import formulas as F
from estimating_tools.heavycivil.columns import CR, SH
from estimating_tools.heavycivil.sheets.common import set_value

SHEET = "_shares"
_HEADINGS = (SH.ACTIVITY, "activity_id"), (SH.ITEM, "item_id"), (SH.FRACTION, "fraction"), \
    (SH.ROW, "cost_report_row"), (SH.LAB, "labor"), (SH.EQP, "equipment"), \
    (SH.MAT, "material"), (SH.SUB, "subcontractor"), (SH.OTH, "other"), \
    (SH.TOTAL, "total"), (SH.MH, "manhours"), (SH.EXPORT, "export_cost")


def write_shares(ws, plan, wb):
    ws.sheet_state = "hidden"
    for col, heading in _HEADINGS:
        ws[f"{col}1"] = heading
    per_activity = Counter(s.activity_id for s in wb.shares)
    cost_tab = plan.tabs["cost_report"]
    for row in plan.share_rows:
        share, r = row.obj, row.row
        act = plan.activity_rows[share.activity_id].row
        # Ids are payload values: pinned to text if a string (set_value).
        set_value(ws[f"{SH.ACTIVITY}{r}"], share.activity_id)
        set_value(ws[f"{SH.ITEM}{r}"], share.item_id)
        ws[f"{SH.FRACTION}{r}"] = share.fraction
        ws[f"{SH.ROW}{r}"] = act
        for (_, cr_col), (_, sh_col) in zip(CR.SPLIT, SH.SPLIT):
            ws[f"{sh_col}{r}"] = F.share_split(cr_col, r, act, cost_tab)
        ws[f"{SH.TOTAL}{r}"] = F.share_total(r, act, cost_tab,
                                             split=per_activity[share.activity_id] > 1)
        ws[f"{SH.MH}{r}"] = F.share_hours(r, act, cost_tab)
        ws[f"{SH.EXPORT}{r}"] = share.cost
