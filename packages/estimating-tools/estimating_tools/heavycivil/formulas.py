"""Every live HeavyCivil formula, and the BidSheet.ai rule each reproduces.

This is the only module that knows BidSheet.ai's cost arithmetic; the pycel
parity tests (test_parity.py) check each formula against BidSheet.ai's own
figure in the fixture. Sources (BidManager origin/master, 2026-10-20):

- Resource cost: ``Component.calculate_cost`` / ``effective_labor_units`` /
  ``has_missing_production_data`` (Projects/models/assembly.py).
- Activity own cost: ``Assembly.calculate_cost_split`` (crew-priced when
  ``crew_id`` and ``duration_shifts`` are both set: crew cost replaces the
  labour components) and ``Crew.cost_for_duration``; extended by the count
  chain like ``estimate_model._activities``.
- Man-hours: ``estimate_task_rollup.labor_manhours`` (crew: headcount x
  shifts x crew hours/shift, no crew factor; else the labour quantities).
- Item: ``EstimateItem.calculate_total`` / ``get_quantity`` /
  ``apply_breakdown_price`` over the allocation shares.
- A stepped activity's shifts: ``activity_steps.sum_step_shifts`` (what
  ``stamp_duration_from_steps`` writes into ``duration_shifts``).

Every builder returns a :class:`Formula`; a writer's own inline formula is
wrapped in one too.

Same-sheet references are relative (``M7``); cross-sheet ones are absolute
and quoted (``qualified``).
"""
from __future__ import annotations

import functools

from estimating_tools.heavycivil.columns import BF, CR, CW, FL, RC, RT, SC, SH


class Formula(str):
    """A live formula. ``sheets.common.put`` writes only these as formulas;
    any other string -- payload text above all -- is stored as text, even
    one starting with "=" (openpyxl would otherwise make it a formula)."""

    __slots__ = ()


def _formula(builder):
    """Mark a builder's result as a :class:`Formula`."""
    @functools.wraps(builder)
    def wrapped(*args, **kwargs):
        return Formula(builder(*args, **kwargs))
    return wrapped


def qualified(sheet, col, row):
    return "'" + sheet.replace("'", "''") + f"'!${col}${row}"


def qualified_range(sheet, col, first, last):
    return "'" + sheet.replace("'", "''") + f"'!${col}${first}:${col}${last}"


# -- activity ------------------------------------------------------------------

@_formula
def multiplier(row, parent_row):
    """Extended count: own count x every ancestor's (``rollup_cost``'s
    compounding, as ``estimate_model._activities`` reports it)."""
    return f"={CR.COUNT}{row}" if parent_row is None else f"={CR.COUNT}{row}*{CR.MULT}{parent_row}"


def _sum(col, span):
    """Sum over an activity's resource span: its START marker to its END
    marker (at least two rows), so a row inserted above END is included."""
    return "0" if span is None else f"SUM({col}{span[0]}:{col}{span[1]})"


@_formula
def activity_split(col, row, span):
    """A non-labour cost type: the activity's own resources of that type."""
    return f"={_sum(col, span)}*{CR.MULT}{row}"


@_formula
def activity_labor(row, span, *, crew_cells, missing_crew):
    """Labour: the crew's cost when crew-priced (shifts set), else the labour
    resources. ``missing_crew``: the crew is not in the payload, so its
    per-shift, per-unit cost is BidSheet.ai's figure as of export (``AH``),
    times the live shifts."""
    resources = _sum(CR.LAB, span)
    if missing_crew:
        crew = f"{CR.H3}{row}*{CR.SHIFTS}{row}"
    elif crew_cells is not None:
        crew = (f"{crew_cells['rate']}*{CR.SHIFTS}{row}*{crew_cells['hps']}"
                f"*{crew_cells['factor']}")
    else:
        return f"={resources}*{CR.MULT}{row}"
    return f'=IF({CR.SHIFTS}{row}<>"",{crew},{resources})*{CR.MULT}{row}'


@_formula
def activity_manhours(row, span, *, crew_cells, missing_crew):
    labor_hours = ("0" if span is None else
                   f'SUMIF({CR.TYPE}{span[0]}:{CR.TYPE}{span[1]},"labor",'
                   f'{CR.QTY}{span[0]}:{CR.QTY}{span[1]})')
    if missing_crew:
        crew = f"{CR.H4}{row}*{CR.SHIFTS}{row}"
    elif crew_cells is not None:
        crew = f"{crew_cells['headcount']}*{CR.SHIFTS}{row}*{crew_cells['hps']}"
    else:
        return f"={labor_hours}*{CR.MULT}{row}"
    return f'=IF({CR.SHIFTS}{row}<>"",{crew},{labor_hours})*{CR.MULT}{row}'


@_formula
def step_shifts(row, step_rows):
    """``sum_step_shifts``: the step durations in shifts (an HOURS step
    divided by the activity's hours/shift, 8 when blank or zero; a blank unit
    is DAYS), summed and quantized to 0.01 the way ``Decimal.quantize``
    rounds by default -- half to even -- not Excel's half-up ``ROUND``."""
    hps = f'IF(OR({CR.HPS}{row}="",{CR.HPS}{row}=0),8,{CR.HPS}{row})'
    total = "+".join(f'{CR.QTY}{s}*IF({CR.UNIT}{s}="HOURS",1/{hps},1)' for s in step_rows)
    cents = f"({total})*100"
    return (f"=IF(ABS(MOD({cents},1)-0.5)<1E-9,"
            f"(INT({cents})+MOD(INT({cents}),2))/100,ROUND({total},2))")


@_formula
def row_total(row):
    return f"=SUM({CR.LAB}{row}:{CR.OTH}{row})"


# -- resource ------------------------------------------------------------------

@_formula
def resource_units(row, act):
    """``effective_labor_units``: the line's own time (converted between
    HOURS and DAYS with the activity's hours/shift when its unit differs from
    the activity's production unit), else the activity's production rate,
    else blank ("no production": ``has_missing_production_data``)."""
    pu = f'IF({CR.PUNIT}{act}="","DAYS",{CR.PUNIT}{act})'
    tu = f'IF({CR.PUNIT}{row}="",{pu},{CR.PUNIT}{row})'
    own = (f'IF({tu}={pu},{CR.PROD}{row},IF({pu}="DAYS",{CR.PROD}{row}/{CR.HPS}{act},'
           f'{CR.PROD}{row}*{CR.HPS}{act}))')
    return (f'=IF({CR.PROD}{row}<>"",{own},'
            f'IF({CR.PROD}{act}<>"",{CR.PROD}{act},""))')


@_formula
def resource_cost(row, act):
    """``Component.calculate_cost``, per unit (not extended)."""
    qe = f"{CR.QTY}{row}*{CR.UCOST}{row}"
    factor = f'IF({CR.CFACT}{act}="",1,{CR.CFACT}{act})'
    base = (f'IF(OR({CR.BASIS}{row}="flat",{CR.H1}{row}=""),{qe},'
            f'{qe}*{CR.H1}{row}*{factor})')
    burden = (f'IF(AND({CR.BINC}{row}<>"Y",{CR.BURD}{row}<>"",{CR.BURD}{row}<>0),'
              f'1+{CR.BURD}{row}/100,1)')
    return f'=IF({CR.TYPE}{row}="labor",{base}*{burden},{qe})'


@_formula
def resource_split(col, kind, row):
    if kind == "other":
        named = "+".join(f"{c}{row}" for k, c in CR.SPLIT if k != "other")
        return f"={CR.H2}{row}-({named})"
    return f'=IF({CR.TYPE}{row}="{kind}",{CR.H2}{row},0)'


@_formula
def resource_hours(row):
    return f'=IF({CR.TYPE}{row}="labor",{CR.QTY}{row},0)'


# -- element quantity ------------------------------------------------------------

@_formula
def quantity_effective(row):
    return f'=IF({CR.QTY}{row}="",{CR.UCOST}{row},{CR.QTY}{row})'


# -- item ------------------------------------------------------------------------

@_formula
def item_quantity(row):
    """``get_quantity``: the override if set, else the schedule quantity."""
    return f'=IF({CR.QTY}{row}="",{CR.H1}{row},{CR.QTY}{row})'


@_formula
def item_breakdown_split(col_on_shares, row, shares_tab, first, last):
    if last < first:
        return "=0"
    return (f"=SUMIF({qualified_range(shares_tab, SH.ITEM, first, last)},{CR.ID}{row},"
            f"{qualified_range(shares_tab, col_on_shares, first, last)})")


@_formula
def item_breakdown(row):
    return f"=SUM({CR.LAB}{row}:{CR.OTH}{row})"


@_formula
def item_breakdown_total(row, shares_tab, first, last):
    """``get_assembly_total_cost`` over the allocation: the item's shares'
    rounded totals (not the sum of the unrounded per-type splits)."""
    return item_breakdown_split(SH.TOTAL, row, shares_tab, first, last)


@_formula
def item_unit_price(row):
    """``calculated_unit_price``: breakdown / quantity to the cent, blank when
    either is not positive."""
    return (f'=IF(AND({CR.H2}{row}<>"",{CR.H2}{row}>0,{CR.H3}{row}>0),'
            f'ROUND({CR.H3}{row}/{CR.H2}{row},2),"")')


@_formula
def item_cost(row):
    """``calculate_total``: 0 when the quantity is blank or zero (falsy --
    a negative quantity still prices); else quantity x the manual price if
    set, else x the calculated unit price (blank unless the quantity is
    positive), else 0. An item excluded at export has no shares in the
    payload, so its ``AI`` holds the calculated unit price as of export
    (``cost_report._item``) -- not the stored ``total``, which
    ``bid_totals.compute`` does not use for the excluded cost."""
    q = f"{CR.H2}{row}"
    return (f'=IF(OR({q}="",{q}=0),0,IF({CR.UCOST}{row}<>"",{CR.UCOST}{row}*{q},'
            f'IF({CR.H4}{row}<>"",{CR.H4}{row}*{q},0)))')


# -- shares ----------------------------------------------------------------------

@_formula
def share_split(col_on_cost_report, share_row, activity_row, cost_tab):
    return f"={qualified(cost_tab, col_on_cost_report, activity_row)}*{SH.FRACTION}{share_row}"


@_formula
def share_total(share_row, activity_row, cost_tab, *, split):
    """A one-target share keeps the activity's exact cost; a split share is
    cents (BidSheet.ai: largest remainder; here ROUND -- may differ by $0.01)."""
    product = f"{qualified(cost_tab, CR.TOTAL, activity_row)}*{SH.FRACTION}{share_row}"
    return f"=ROUND({product},2)" if split else f"={product}"


@_formula
def share_hours(share_row, activity_row, cost_tab):
    return f"={qualified(cost_tab, CR.MH, activity_row)}*{SH.FRACTION}{share_row}"


# -- crews -----------------------------------------------------------------------

@_formula
def member_library_rate(row, rates_tab, labor_span):
    """``effective_hourly_rate``'s library half: the linked labour rate's
    burdened rate. Not found (a rate the payload omits): BidSheet.ai's figure
    as of export (``P``)."""
    if labor_span is None:
        return f'=IF({CW.RATE_ID}{row}="",0,{CW.EXPORT}{row})'
    first, last = labor_span
    table = ("'" + rates_tab.replace("'", "''") + f"'!${RT.ID}${first}:${RT.RATE}${last}")
    return (f'=IF({CW.RATE_ID}{row}="",0,'
            f'IFERROR(VLOOKUP({CW.RATE_ID}{row},{table},4,FALSE),{CW.EXPORT}{row}))')


@_formula
def member_effective(row):
    return f'=IF({CW.OVERRIDE}{row}<>"",{CW.OVERRIDE}{row},{CW.LIBRATE}{row})'


@_formula
def member_extended(row):
    return f"={CW.COUNT}{row}*{CW.EFFECTIVE}{row}"


@_formula
def crew_sum(col, span):
    if span is None or span[1] < span[0]:
        return "=0"
    return f"=SUM({col}{span[0]}:{col}{span[1]})"


# -- bid form --------------------------------------------------------------------
# ``EstimateBidTotal`` / ``bid_totals.compute`` and ``EstimateItem.bid_unit_price_at``
# / ``bid_total_at``; the estimate figures follow ``Estimate.calculate_totals``.

_V = BF.VALUE
_R = BF.ROWS


@_formula
def bid_direct_cost(first, last):
    """``total_estimated_cost``: the primary items' cost, to the cent."""
    return f"=ROUND(SUM({BF.PCOST}{first}:{BF.PCOST}{last}),2)"


@_formula
def bid_markup_total():
    d, i = f"{_V}{_R['direct_cost']}", f"{_V}{_R['indirect_cost']}"
    pct, amt = f"{_V}{_R['markup_percentage']}", f"{_V}{_R['markup_amount']}"
    return f"=ROUND(({d}+{i})*{pct}/100+{amt},2)"


@_formula
def bid_factor():
    d, i, m = (f"{_V}{_R['direct_cost']}", f"{_V}{_R['indirect_cost']}",
               f"{_V}{_R['markup_total']}")
    return f"=IF({d}<=0,1,({d}+{i}+{m})/{d})"


@_formula
def bid_excluded_cost(first, last):
    return (f'=ROUND(SUMIF({BF.SCOPE}{first}:{BF.SCOPE}{last},"excluded",'
            f"{BF.COST}{first}:{BF.COST}{last}),2)")


@_formula
def bid_item_cost(cost_tab, item_row):
    return f"={qualified(cost_tab, CR.TOTAL, item_row)}"


@_formula
def bid_priced(cost_tab, item_row):
    """Priced = a manual or a calculated unit price. An item excluded at
    export has no shares in the payload; its ``AI`` holds the calculated
    unit price as of export (``cost_report._item``)."""
    m, c = qualified(cost_tab, CR.UCOST, item_row), qualified(cost_tab, CR.H4, item_row)
    return f'=IF(OR({m}<>"",{c}<>""),1,0)'


@_formula
def bid_primary_cost(row):
    return f'=IF(AND({BF.SCOPE}{row}<>"excluded",{BF.PRIMARY}{row}=1),{BF.COST}{row},0)'


@_formula
def bid_unit_price(row):
    """``bid_unit_price_at``: blank when excluded, unpriced or without a
    schedule quantity; else the override, else cost x factor / schedule qty."""
    factor = f"${_V}${_R['bid_factor']}"
    return (f'=IF(OR({BF.SCOPE}{row}="excluded",{BF.PRICED}{row}=0,{BF.QTY}{row}="",'
            f'{BF.QTY}{row}=0),"",IF({BF.OVERRIDE}{row}<>"",{BF.OVERRIDE}{row},'
            f'ROUND({BF.COST}{row}*{factor}/{BF.QTY}{row},2)))')


@_formula
def bid_item_total(row):
    return f'=IF({BF.PRICE}{row}="","",ROUND({BF.PRICE}{row}*{BF.QTY}{row},2))'


@_formula
def bid_total_amount(*, schedule_ids, includes_unscheduled, first, last):
    """``bid_totals.compute``: the sum of the item bid totals on the schedules
    a definition covers (unscheduled items carry schedule id -1). Each id is
    written into the formula, so it is coerced to ``int`` here as well as
    checked by ``model.parse`` -- text never reaches the formula."""
    rng_m = f"{BF.SCHED_ID}{first}:{BF.SCHED_ID}{last}"
    rng_i = f"{BF.TOTAL}{first}:{BF.TOTAL}{last}"
    if schedule_ids is None:
        # Every schedule is covered; unscheduled items only when included.
        if includes_unscheduled:
            return f"=SUM({rng_i})"
        return f"=SUM({rng_i})-SUMIF({rng_m},-1,{rng_i})"
    parts = [f"SUMIF({rng_m},{int(sid)},{rng_i})" for sid in schedule_ids]
    if includes_unscheduled:
        parts.append(f"SUMIF({rng_m},-1,{rng_i})")
    return "=" + ("+".join(parts) if parts else "0")


# -- recap -----------------------------------------------------------------------

@_formula
def recap_ref(sheet, col, row):
    return f"={qualified(sheet, col, row)}"


@_formula
def recap_manhours(item_row_on_cr, cost_tab, shares_tab, first, last):
    if last < first:
        return "=0"
    return (f"=SUMIF({qualified_range(shares_tab, SH.ITEM, first, last)},"
            f"{qualified(cost_tab, CR.ID, item_row_on_cr)},"
            f"{qualified_range(shares_tab, SH.MH, first, last)})")


@_formula
def recap_unit_cost(row):
    return f'=IF(AND({RC.QTY}{row}<>"",{RC.QTY}{row}<>0),{RC.DIRECT}{row}/{RC.QTY}{row},"")'


@_formula
def column_sum(col, first, last):
    return "=0" if last < first else f"=SUM({col}{first}:{col}{last})"


# -- schedule --------------------------------------------------------------------

@_formula
def schedule_duration(row, cost_tab, activity_row):
    """Live working days: the per-pass duration -- the Cost Report Shifts
    when set, else the export's per-pass ``duration_days`` (J) -- times the
    live count multiplier (``estimate_task_rollup``: ``duration_days x
    count``)."""
    j = qualified(cost_tab, CR.SHIFTS, activity_row)
    aa = qualified(cost_tab, CR.MULT, activity_row)
    return f'=IF({j}<>"",{j},{SC.XDURATION}{row})*{aa}'


@_formula
def schedule_finish(row, cal_tab, cal_last):
    """Export finish moved by the change in whole working days (both looked
    up on the working-day calendar ``_cal``), never before the start
    (``estimate_model._finish``: ``max(day, start)``). The change is against
    the export's extended duration (J x K); a move past the calendar's end
    stops on its last day."""
    cal = "'" + cal_tab.replace("'", "''") + f"'!$A$1:$A${cal_last}"
    at_finish = f"MATCH({SC.XFINISH}{row},{cal},1)"
    at_start = f"MATCH({SC.START}{row},{cal},1)"
    shift = (f"CEILING({SC.DURATION}{row},1)"
             f"-CEILING({SC.XDURATION}{row}*{SC.XMULT}{row},1)")
    index = f"MIN({cal_last},MAX({at_start},{at_finish}+{shift}))"
    return (f"=IFERROR(MAX({SC.START}{row},INDEX({cal},{index})),"
            f"{SC.XFINISH}{row})")


# -- flat ------------------------------------------------------------------------

def _crew_priced(cost_tab, act):
    return (f'AND({qualified(cost_tab, CR.REF, act)}<>"",'
            f'{qualified(cost_tab, CR.SHIFTS, act)}<>"")')


@_formula
def flat_crew_cost(cost_tab, act):
    return f"=IF({_crew_priced(cost_tab, act)},{qualified(cost_tab, CR.LAB, act)},0)"


@_formula
def flat_crew_hours(cost_tab, act):
    return f"=IF({_crew_priced(cost_tab, act)},{qualified(cost_tab, CR.MH, act)},0)"


@_formula
def flat_resource_cost(cost_tab, res, act):
    """A resource's extended cost; a labour line on a crew-priced activity
    is skipped (the crew charge prices that labour)."""
    labor = f'{qualified(cost_tab, CR.TYPE, res)}="labor"'
    return (f"=IF(AND({labor},{_crew_priced(cost_tab, act)}),0,"
            f"{qualified(cost_tab, CR.H2, res)}*{qualified(cost_tab, CR.MULT, act)})")


@_formula
def flat_resource_hours(cost_tab, res, act):
    labor = f'{qualified(cost_tab, CR.TYPE, res)}="labor"'
    return (f"=IF(AND({labor},NOT({_crew_priced(cost_tab, act)})),"
            f"{qualified(cost_tab, CR.QTY, res)}*{qualified(cost_tab, CR.MULT, act)},0)")
