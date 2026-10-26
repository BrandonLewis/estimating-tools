"""The Cost Report: one outlined sheet, item -> element quantities ->
activities (nested) with their steps and resources. See layout.py for the
row order and columns.py/the plan's table for the cells each kind fills."""
from __future__ import annotations

from decimal import Decimal

from openpyxl.worksheet.datavalidation import DataValidation

from estimating_tools.heavycivil import formulas as F
from estimating_tools.heavycivil.columns import CR, SH
from estimating_tools.heavycivil.layout import HEADER_ROW, SHARES_FIRST_ROW
from estimating_tools.heavycivil.sheets.common import export_multiplier, factory, put, setup_sheet
from estimating_tools.heavycivil.sheets.crews import crew_cells

#: The END marker's cue: lines inserted above it join the activity's sums.
END_CUE = "insert lines above"
#: The START (and STEPS) marker's row height (points): present, but barely
#: visible.
START_HEIGHT = 6


def _hidden(ws, r, kind, rid, v, parent_id=None):
    put(ws, None, f"{CR.KIND}{r}", kind)
    put(ws, None, f"{CR.ID}{r}", rid)
    put(ws, None, f"{CR.V}{r}", v)
    put(ws, None, f"{CR.PARENT}{r}", parent_id)


def _item(ws, sf, plan, row):
    item, r = row.obj, row.row
    shares_tab, last = "_shares", plan.shares_last_row
    put(ws, sf, f"{CR.CODE}{r}", item.item_number, "item_text")
    put(ws, sf, f"{CR.DESC}{r}", item.description, "item_text")
    put(ws, sf, f"{CR.QTY}{r}", item.quantity_override, "input_qty")
    put(ws, sf, f"{CR.UNIT}{r}", item.unit, "item_text")
    put(ws, sf, f"{CR.UCOST}{r}", item.estimated_unit_price, "input_money")
    for kind, col in CR.SPLIT:
        share_col = dict(SH.SPLIT)[kind]
        put(ws, sf, f"{col}{r}",
            F.item_breakdown_split(share_col, r, shares_tab, SHARES_FIRST_ROW, last), "item_money")
    put(ws, sf, f"{CR.TOTAL}{r}", F.item_cost(r), "item_money")
    _hidden(ws, r, "ITEM", item.id, item.v)
    put(ws, None, f"{CR.REF}{r}", item.scope)
    put(ws, None, f"{CR.H1}{r}", item.schedule_quantity)
    put(ws, None, f"{CR.H2}{r}", F.item_quantity(r))
    put(ws, None, f"{CR.H3}{r}", F.item_breakdown_total(r, shares_tab, SHARES_FIRST_ROW, last))
    if item.scope == "excluded":
        # No shares in the payload: the calculated unit price as of export
        # stands in, so calculate_total (R) stays live in quantity and the
        # manual price (bid_totals.compute's excluded cost).
        put(ws, None, f"{CR.H4}{r}", item.calculated_unit_price)
    else:
        put(ws, None, f"{CR.H4}{r}", F.item_unit_price(r))
    put(ws, None, f"{CR.XCOST}{r}", item.total)


def _quantity(ws, sf, row):
    (element, q), r = row.obj, row.row
    put(ws, sf, f"{CR.CODE}{r}", q.key, "tag")
    put(ws, sf, f"{CR.DESC}{r}", f"{element.name} -- {q.label}", "label")
    put(ws, sf, f"{CR.QTY}{r}", q.override, "input_qty")
    put(ws, sf, f"{CR.UNIT}{r}", q.unit, "calc_text")
    put(ws, sf, f"{CR.UCOST}{r}", q.derived, "export_value")
    _hidden(ws, r, "ELEMENT_QTY", element.id, q.v, q.pay_item_id)
    put(ws, None, f"{CR.KEY}{r}", q.key)
    put(ws, None, f"{CR.REF}{r}", element.id)
    put(ws, None, f"{CR.H2}{r}", F.quantity_effective(r))
    # The override at export, kept for read-back (Checks carries its own copy).
    put(ws, None, f"{CR.H3}{r}", q.override)


def in_bid_fraction(wb, activity):
    """The part of an activity's own cost the payload's shares pay: shares
    to excluded items are dropped (``estimate_workbook.build_workbook``), and
    the activity's ``cost``/``cost_split`` sum only the shares left.

    Fractions that sum to within 1e-12 of 1 (decimal noise from the split)
    are exactly 1, so a fully in-bid activity compares whole."""
    f = sum((s.fraction for s in wb.shares_of_activity(activity.id)), Decimal(0))
    return Decimal(1) if abs(f - 1) < Decimal("1e-12") else f


def _activity(ws, sf, plan, wb, row):
    a, r = row.obj, row.row
    span = plan.resource_span[a.id]
    parent = plan.activity_rows.get(a.parent_id)
    cells = crew_cells(plan, a.crew_id) if a.crew_id is not None else None
    missing = a.crew_id is not None and cells is None
    f = in_bid_fraction(wb, a)
    put(ws, sf, f"{CR.CODE}{r}", a.code, "activity_text")
    put(ws, sf, f"{CR.DESC}{r}", a.name, "input_text")
    put(ws, sf, f"{CR.QTY}{r}", a.basis_quantity, "export_value")
    put(ws, sf, f"{CR.UNIT}{r}", a.basis_unit, "calc_text")
    put(ws, sf, f"{CR.PROD}{r}", a.production_rate, "input_qty")
    put(ws, sf, f"{CR.PUNIT}{r}", a.production_unit, "input_text")
    put(ws, sf, f"{CR.HPS}{r}", a.hours_per_shift, "input_qty")
    put(ws, sf, f"{CR.CFACT}{r}", a.crew_factor, "input_factor")
    if a.steps:
        # BidSheet.ai restamps a stepped activity's shifts from its steps
        # (and refuses a direct edit), so here they follow the step rows:
        # the STEPS..START range, so an inserted step counts too.
        put(ws, sf, f"{CR.SHIFTS}{r}", F.step_shifts(r, plan.step_span[a.id]), "calc_qty")
    else:
        put(ws, sf, f"{CR.SHIFTS}{r}", a.duration_shifts, "input_qty")
    put(ws, sf, f"{CR.COUNT}{r}", a.count, "input_count")
    put(ws, sf, f"{CR.MH}{r}", F.activity_manhours(r, span, crew_cells=cells, missing_crew=missing),
        "activity_hours")
    put(ws, sf, f"{CR.LAB}{r}", F.activity_labor(r, span, crew_cells=cells, missing_crew=missing),
        "activity_money")
    for kind, col in CR.SPLIT[1:]:
        put(ws, sf, f"{col}{r}", F.activity_split(col, r, span), "activity_money")
    put(ws, sf, f"{CR.TOTAL}{r}", F.row_total(r), "activity_money")
    _hidden(ws, r, "ACTIVITY", a.id, a.v, a.parent_id)
    put(ws, None, f"{CR.MULT}{r}", F.multiplier(r, parent.row if parent else None))
    put(ws, None, f"{CR.XCOST}{r}", a.cost)
    put(ws, None, f"{CR.XMH}{r}", a.manhours)
    put(ws, None, f"{CR.REF}{r}", a.crew_id)
    put(ws, None, f"{CR.H1}{r}", f)
    if missing:
        # Per shift and per unit of the extended count, so Shifts and Count
        # stay live. The export's labour is the in-bid part (divided by f for
        # the whole); its man-hours are never reduced, so they are whole.
        per = export_multiplier(wb, a) * (a.duration_shifts or 0)
        labor = a.cost_split.get("labor") or Decimal(0)
        put(ws, None, f"{CR.H3}{r}", labor / f / per if per and f else Decimal(0))
        put(ws, None, f"{CR.H4}{r}", a.manhours / per if per else Decimal(0))


def _step(ws, sf, row):
    s, r = row.obj, row.row
    put(ws, sf, f"{CR.CODE}{r}", "step", "tag")
    put(ws, sf, f"{CR.DESC}{r}", s.name, "input_text")
    put(ws, sf, f"{CR.QTY}{r}", s.duration, "input_qty")
    put(ws, sf, f"{CR.UNIT}{r}", s.duration_unit, "input_text")
    _hidden(ws, r, "STEP", s.id, s.v, row.parent_id)


def _resource(ws, sf, row):
    res, r = row.obj, row.row
    put(ws, sf, f"{CR.DESC}{r}", res.name, "input_text")
    put(ws, sf, f"{CR.QTY}{r}", res.quantity, "input_qty")
    put(ws, sf, f"{CR.UNIT}{r}", res.unit, "input_text")
    put(ws, sf, f"{CR.UCOST}{r}", res.unit_cost, "input_money")
    put(ws, sf, f"{CR.PROD}{r}", res.time_value, "input_qty")
    put(ws, sf, f"{CR.PUNIT}{r}", res.time_unit or None, "input_text")
    put(ws, sf, f"{CR.MH}{r}", F.resource_hours(r), "calc_hours")
    for kind, col in CR.SPLIT:
        put(ws, sf, f"{col}{r}", F.resource_split(col, kind, r), "calc_money")
    put(ws, sf, f"{CR.TOTAL}{r}", F.Formula(f"={CR.H2}{r}"), "calc_money")
    put(ws, sf, f"{CR.TYPE}{r}", res.component_type, "input_text")
    put(ws, sf, f"{CR.BASIS}{r}", res.labor_cost_basis, "input_text")
    put(ws, sf, f"{CR.BURD}{r}", res.burden_percentage, "input_pct")
    put(ws, sf, f"{CR.BINC}{r}", "Y" if res.includes_burden else "N", "input_flag")
    _hidden(ws, r, "RESOURCE", res.id, res.v, res.activity_id)
    put(ws, None, f"{CR.XCOST}{r}", res.cost)
    # The rate link travels with the row on a copy or a paste into another
    # book (read-back's resource.create sends it).
    put(ws, None, f"{CR.REF}{r}", res.rate_link)
    put(ws, None, f"{CR.H1}{r}", F.resource_units(r))
    put(ws, None, f"{CR.H2}{r}", F.resource_cost(r))


def write_cost_report(ws, plan, wb, style):
    sf = factory(style)
    setup_sheet(ws, sf, style, "cost_report", title="Cost Report",
                subtitle=f"{wb.estimate.name} -- {wb.estimate.project_title}")
    ws.sheet_properties.outlinePr.summaryBelow = False
    for row in plan.cost_report:
        if row.kind == "ITEM":
            _item(ws, sf, plan, row)
        elif row.kind == "ELEMENT_QTY":
            _quantity(ws, sf, row)
        elif row.kind == "ACTIVITY":
            _activity(ws, sf, plan, wb, row)
        elif row.kind == "STEP":
            _step(ws, sf, row)
        elif row.kind == "RESOURCE":
            _resource(ws, sf, row)
        elif row.kind == "STEPS":
            put(ws, None, f"{CR.KIND}{row.row}", "STEPS")
            put(ws, None, f"{CR.PARENT}{row.row}", row.parent_id)
            ws.row_dimensions[row.row].height = START_HEIGHT
        elif row.kind == "START":
            put(ws, None, f"{CR.KIND}{row.row}", "START")
            put(ws, None, f"{CR.PARENT}{row.row}", row.parent_id)
            ws.row_dimensions[row.row].height = START_HEIGHT
        elif row.kind == "END":
            put(ws, sf, f"{CR.DESC}{row.row}", END_CUE, "note")
            put(ws, None, f"{CR.KIND}{row.row}", "END")
            put(ws, None, f"{CR.PARENT}{row.row}", row.parent_id)
        else:
            put(ws, sf, f"{CR.DESC}{row.row}", "Unassigned elements", "group")
            put(ws, None, f"{CR.KIND}{row.row}", "GROUP")
        put(ws, None, f"{CR.ACT}{row.row}", F.activity_row(row.row, HEADER_ROW))
        if row.level:
            ws.row_dimensions[row.row].outline_level = min(row.level, 7)
    _validations(ws, plan)


#: The coded inputs' allowed values (BidSheet.ai's choices; blank allowed).
LISTS = {
    "type": ("labor", "equipment", "material", "subcontractor", "other"),
    "basis": ("production", "flat"),
    "flag": ("Y", "N"),
    "unit": ("DAYS", "HOURS"),
}


def _ranges(col, rows):
    """``rows`` as the fewest ``A1:A9`` ranges in one column."""
    out, rows = [], sorted(rows)
    start = prev = None
    for n in rows + [None]:
        if start is not None and n == prev + 1:
            prev = n
            continue
        if start is not None:
            out.append(f"{col}{start}" if start == prev else f"{col}{start}:{col}{prev}")
        start = prev = n
    return out


def _validations(ws, plan):
    """One list validation per value set, over every row it applies to:
    resource Type/Labor basis/Burden incl./time unit, activity Prod unit
    and step duration unit. Blank is allowed throughout."""
    by_kind = {}
    for row in plan.cost_report:
        by_kind.setdefault(row.kind, []).append(row.row)
    # The START..END markers are included, so a line inserted anywhere in
    # an activity's span (inside the range) inherits the validation.
    resources = (by_kind.get("RESOURCE", []) + by_kind.get("START", [])
                 + by_kind.get("END", []))
    activities = by_kind.get("ACTIVITY", [])
    # STEPS..last step, so a step inserted anywhere in the block inherits
    # the unit list. Not START: its D tops the resource block, and a
    # resource row inserted below it must not inherit DAYS/HOURS.
    steps = by_kind.get("STEP", []) + by_kind.get("STEPS", [])
    cells = {
        "type": _ranges(CR.TYPE, resources),
        "basis": _ranges(CR.BASIS, resources),
        "flag": _ranges(CR.BINC, resources),
        "unit": (_ranges(CR.PUNIT, resources + activities)
                 + _ranges(CR.UNIT, steps)),
    }
    for key, values in LISTS.items():
        if not cells[key]:
            continue
        dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True)
        dv.sqref = " ".join(cells[key])
        ws.add_data_validation(dv)
