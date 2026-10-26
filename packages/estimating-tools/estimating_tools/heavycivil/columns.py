"""Every HeavyCivil sheet's columns, fixed in code.

Read-back depends on these letters, so a style pack may rename a column's
heading, change its width, or hide an ``optional`` one -- and nothing else.
Hidden columns (kind, id, v, ...) are never styleable at all.

Cost Report rows of different kinds reuse the same columns (HeavyBid style);
``layout.py`` documents which cells each kind fills.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    key: str
    letter: str
    heading: str
    hidden: bool = False
    optional: bool = False


class CR:
    """Cost Report letters."""
    CODE, DESC, QTY, UNIT, UCOST = "A", "B", "C", "D", "E"
    PROD, PUNIT, HPS, CFACT, SHIFTS, COUNT = "F", "G", "H", "I", "J", "K"
    MH, LAB, EQP, MAT, SUB, OTH, TOTAL = "L", "M", "N", "O", "P", "Q", "R"
    TYPE, BASIS, BURD, BINC = "S", "T", "U", "V"
    KIND, ID, V, PARENT, MULT, XCOST, XMH, KEY, REF = "W", "X", "Y", "Z", "AA", "AB", "AC", "AD", "AE"
    H1, H2, H3, H4 = "AF", "AG", "AH", "AI"
    #: The row of the nearest ACTIVITY at or above (every data row; see
    #: ``formulas.activity_row``): resource formulas find their activity here.
    ACT = "AJ"
    #: The cost-type columns, in BidSheet.ai's component_type order.
    SPLIT = (("labor", "M"), ("equipment", "N"), ("material", "O"),
             ("subcontractor", "P"), ("other", "Q"))


COST_REPORT = (
    Column("code", CR.CODE, "Code"),
    Column("description", CR.DESC, "Description"),
    Column("quantity", CR.QTY, "Quantity"),
    Column("unit", CR.UNIT, "Unit"),
    Column("unit_cost", CR.UCOST, "Unit cost"),
    Column("production", CR.PROD, "Production"),
    Column("production_unit", CR.PUNIT, "Prod unit"),
    Column("hours_per_shift", CR.HPS, "Hrs/shift", optional=True),
    Column("crew_factor", CR.CFACT, "Crew factor", optional=True),
    Column("shifts", CR.SHIFTS, "Shifts"),
    Column("count", CR.COUNT, "Count"),
    Column("manhours", CR.MH, "Man-hours"),
    Column("labor", CR.LAB, "Labor"),
    Column("equipment", CR.EQP, "Equipment"),
    Column("material", CR.MAT, "Material"),
    Column("subcontract", CR.SUB, "Subcontract", optional=True),
    Column("other", CR.OTH, "Other", optional=True),
    Column("total", CR.TOTAL, "Total"),
    Column("type", CR.TYPE, "Type"),
    Column("labor_basis", CR.BASIS, "Labor basis", optional=True),
    Column("burden_pct", CR.BURD, "Burden %", optional=True),
    Column("burden_included", CR.BINC, "Burden incl.", optional=True),
    Column("kind", CR.KIND, "kind", hidden=True),
    Column("id", CR.ID, "id", hidden=True),
    Column("v", CR.V, "v", hidden=True),
    Column("parent_id", CR.PARENT, "parent_id", hidden=True),
    Column("multiplier", CR.MULT, "multiplier", hidden=True),
    Column("export_cost", CR.XCOST, "export_cost", hidden=True),
    Column("export_mh", CR.XMH, "export_mh", hidden=True),
    Column("key", CR.KEY, "key", hidden=True),
    Column("ref", CR.REF, "ref", hidden=True),
    Column("h1", CR.H1, "h1", hidden=True),
    Column("h2", CR.H2, "h2", hidden=True),
    Column("h3", CR.H3, "h3", hidden=True),
    Column("h4", CR.H4, "h4", hidden=True),
    Column("activity_row", CR.ACT, "activity_row", hidden=True),
)


class CW:
    """Crews letters."""
    CODE, NAME, COUNT, LIBRATE, OVERRIDE, EFFECTIVE = "A", "B", "C", "D", "E", "F"
    HPS, CFACT, HEADCOUNT, RATE = "G", "H", "I", "J"
    KIND, ID, V, CREW, RATE_ID, EXPORT, EXTENDED = "K", "L", "M", "N", "O", "P", "Q"


CREWS = (
    Column("code", CW.CODE, "Code / class"),
    Column("name", CW.NAME, "Name"),
    Column("count", CW.COUNT, "Count"),
    Column("library_rate", CW.LIBRATE, "Library rate"),
    Column("override", CW.OVERRIDE, "Rate override"),
    Column("effective", CW.EFFECTIVE, "Rate"),
    Column("hours_per_shift", CW.HPS, "Hrs/shift"),
    Column("crew_factor", CW.CFACT, "Crew factor"),
    Column("headcount", CW.HEADCOUNT, "Headcount"),
    Column("hourly_rate", CW.RATE, "Crew $/hr"),
    Column("kind", CW.KIND, "kind", hidden=True),
    Column("id", CW.ID, "id", hidden=True),
    Column("v", CW.V, "v", hidden=True),
    Column("crew_id", CW.CREW, "crew_id", hidden=True),
    Column("labor_rate_id", CW.RATE_ID, "labor_rate_id", hidden=True),
    Column("export", CW.EXPORT, "export", hidden=True),
    Column("extended", CW.EXTENDED, "extended", hidden=True),
)


class RT:
    ID, NAME, UNIT, RATE = "A", "B", "C", "D"


RATES = (
    Column("id", RT.ID, "Id"),
    Column("name", RT.NAME, "Name"),
    Column("unit", RT.UNIT, "Unit"),
    Column("rate", RT.RATE, "Rate"),
)


class CK:
    KIND, CODE, DESC, MEASURE, EXCEL, BIDSHEET, DIFF, TOL, STATUS = (
        "A", "B", "C", "D", "E", "F", "G", "H", "I")


CHECKS = (
    Column("kind", CK.KIND, "Kind"),
    Column("code", CK.CODE, "Code"),
    Column("description", CK.DESC, "Description"),
    Column("measure", CK.MEASURE, "Measure"),
    Column("excel", CK.EXCEL, "Excel"),
    Column("bidsheet", CK.BIDSHEET, "BidSheet.ai"),
    Column("difference", CK.DIFF, "Difference"),
    Column("tolerance", CK.TOL, "Tolerance"),
    Column("status", CK.STATUS, "Status"),
)


class SH:
    """``_shares`` letters (hidden sheet; not styleable)."""
    ACTIVITY, ITEM, FRACTION, ROW = "A", "B", "C", "D"
    LAB, EQP, MAT, SUB, OTH, TOTAL, MH, EXPORT = "E", "F", "G", "H", "I", "J", "K", "L"
    SPLIT = (("labor", "E"), ("equipment", "F"), ("material", "G"),
             ("subcontractor", "H"), ("other", "I"))


class BF:
    """Bid Form letters. Inputs: estimate markup (C4, C5), item scope (F)
    and bid unit price override (G). Each estimate row (``ROWS``) carries its
    name in ``INPUT`` (hidden), so read-back finds it by name, not address."""
    CODE, DESC, SCHED, QTY, UNIT, SCOPE, OVERRIDE, PRICE, TOTAL = (
        "A", "B", "C", "D", "E", "F", "G", "H", "I")
    KIND, ID, V, SCHED_ID, COST, PRIMARY, PRICED, PCOST, XPRICE, XTOTAL = (
        "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S")
    #: The estimate row's name (a ``ROWS`` key) on rows 4-10.
    INPUT = "T"
    #: Estimate inputs and derived figures, in column C.
    VALUE = "C"
    ROWS = {"markup_percentage": 4, "markup_amount": 5, "indirect_cost": 6,
            "direct_cost": 7, "markup_total": 8, "bid_factor": 9, "excluded_cost": 10}
    #: The editable ones (the rest are derived, or as of export).
    INPUTS = ("markup_percentage", "markup_amount")
    HEADER_ROW = 12
    FIRST_ROW = 13


BID_FORM = (
    Column("item", BF.CODE, "Item"),
    Column("description", BF.DESC, "Description"),
    Column("schedule", BF.SCHED, "Schedule"),
    Column("quantity", BF.QTY, "Bid qty"),
    Column("unit", BF.UNIT, "Unit"),
    Column("scope", BF.SCOPE, "Scope"),
    Column("override", BF.OVERRIDE, "Price override"),
    Column("unit_price", BF.PRICE, "Bid unit price"),
    Column("total", BF.TOTAL, "Bid total"),
    Column("kind", BF.KIND, "kind", hidden=True),
    Column("id", BF.ID, "id", hidden=True),
    Column("v", BF.V, "v", hidden=True),
    Column("schedule_id", BF.SCHED_ID, "schedule_id", hidden=True),
    Column("cost", BF.COST, "cost", hidden=True),
    Column("primary", BF.PRIMARY, "primary", hidden=True),
    Column("priced", BF.PRICED, "priced", hidden=True),
    Column("primary_cost", BF.PCOST, "primary_cost", hidden=True),
    Column("export_price", BF.XPRICE, "export_price", hidden=True),
    Column("export_total", BF.XTOTAL, "export_total", hidden=True),
    Column("input", BF.INPUT, "input", hidden=True),
)


class RC:
    """Recap letters."""
    CODE, DESC, QTY, UNIT, MH, LAB, EQP, MAT, SUB, OTH, DIRECT, UCOST, PRICE, TOTAL = (
        "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N")
    KIND, ID = "O", "P"
    SPLIT = (("labor", "F"), ("equipment", "G"), ("material", "H"),
             ("subcontractor", "I"), ("other", "J"))


RECAP = (
    Column("item", RC.CODE, "Item"),
    Column("description", RC.DESC, "Description"),
    Column("quantity", RC.QTY, "Quantity"),
    Column("unit", RC.UNIT, "Unit"),
    Column("manhours", RC.MH, "Man-hours"),
    Column("labor", RC.LAB, "Labor"),
    Column("equipment", RC.EQP, "Equipment"),
    Column("material", RC.MAT, "Material"),
    Column("subcontract", RC.SUB, "Subcontract", optional=True),
    Column("other", RC.OTH, "Other", optional=True),
    Column("direct", RC.DIRECT, "Direct cost"),
    Column("unit_cost", RC.UCOST, "Unit cost"),
    Column("bid_unit_price", RC.PRICE, "Bid unit price"),
    Column("bid_total", RC.TOTAL, "Bid total"),
    Column("kind", RC.KIND, "kind", hidden=True),
    Column("id", RC.ID, "id", hidden=True),
)


class SC:
    """Schedule letters."""
    CODE, NAME, ITEM, START, DURATION, FINISH = "A", "B", "C", "D", "E", "F"
    #: XDURATION is BidSheet.ai's per-pass ``duration_days``; XMULT the
    #: count multiplier at export (own count x every ancestor's), so
    #: XDURATION x XMULT is the extended duration the export dates span.
    KIND, ID, XFINISH, XDURATION, XMULT = "G", "H", "I", "J", "K"
    #: Week columns start here and are not part of the style contract.
    FIRST_WEEK = "L"


SCHEDULE = (
    Column("code", SC.CODE, "Code"),
    Column("activity", SC.NAME, "Activity"),
    Column("item", SC.ITEM, "Item"),
    Column("start", SC.START, "Start"),
    Column("duration", SC.DURATION, "Days"),
    Column("finish", SC.FINISH, "Finish"),
    Column("kind", SC.KIND, "kind", hidden=True),
    Column("id", SC.ID, "id", hidden=True),
    Column("export_finish", SC.XFINISH, "export_finish", hidden=True),
    Column("export_duration", SC.XDURATION, "export_duration", hidden=True),
    Column("export_multiplier", SC.XMULT, "export_multiplier", hidden=True),
)


class FL:
    """Flat letters."""
    ITEM, CODE, ACTIVITY, LINE, TYPE, QTY, UNIT, MH, COST = (
        "A", "B", "C", "D", "E", "F", "G", "H", "I")
    KIND, ID = "J", "K"


FLAT = (
    Column("item", FL.ITEM, "Item"),
    Column("code", FL.CODE, "Code"),
    Column("activity", FL.ACTIVITY, "Activity"),
    Column("line", FL.LINE, "Line"),
    Column("type", FL.TYPE, "Type"),
    Column("quantity", FL.QTY, "Quantity"),
    Column("unit", FL.UNIT, "Unit"),
    Column("manhours", FL.MH, "Man-hours"),
    Column("cost", FL.COST, "Cost"),
    Column("kind", FL.KIND, "kind", hidden=True),
    Column("id", FL.ID, "id", hidden=True),
)


#: Styleable sheets, in tab order (``_shares``/``_wb`` are hidden machinery,
#: never styled).
SHEETS = {"bid_form": BID_FORM, "recap": RECAP, "cost_report": COST_REPORT, "crews": CREWS,
          "rates": RATES, "schedule": SCHEDULE, "checks": CHECKS, "flat": FLAT}
