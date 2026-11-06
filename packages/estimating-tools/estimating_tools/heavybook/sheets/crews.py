"""Crews: the estimate's own crews plus the library crews its activities
use. Members' count, classification and rate override are inputs
(``crew.update_members``); a library crew carries a banner saying an edit
copies it into the estimate, which is what the apply does."""
from __future__ import annotations

from estimating_tools.heavybook import formulas as F
from estimating_tools.heavybook.columns import CW
from estimating_tools.heavybook.layout import DERIVED, HEADER_ROW
from estimating_tools.heavybook.sheets.common import factory, put, setup_sheet

LIBRARY_BANNER = "Library crew -- an edit copies it into this estimate."
#: The CREW_END marker's cue: members inserted above it join the crew's sums.
CREW_END_CUE = "insert members above"


def _tags(ws, r, kind, ident=None, v=None):
    """The hidden tags of a Crews row, with the crew-row helper (R) every
    data row carries. A derived kind's crew tag (``layout.DERIVED``) is the
    formula ``F.crew_id``: the id at the row the helper names, so a row
    names the crew it sits in wherever it lands; a CREW row carries none."""
    put(ws, None, f"{CW.KIND}{r}", kind)
    put(ws, None, f"{CW.ID}{r}", ident)
    put(ws, None, f"{CW.V}{r}", v)
    if kind in DERIVED["crews"]:
        put(ws, None, f"{CW.CREW}{r}", F.crew_id(r))
    put(ws, None, f"{CW.OWNER}{r}", F.crew_row(r, HEADER_ROW))


def write_crews(ws, plan, wb, style):
    sf = factory(style)
    setup_sheet(ws, sf, style, "crews", title="Crews",
                subtitle=f"{wb.estimate.name} -- crew rates feed the Cost Report")
    for r in plan.crews:
        if r.kind == "CREW":
            crew, span = r.obj, plan.crew_span[r.id]
            put(ws, sf, f"{CW.CODE}{r.row}", crew.code or crew.name, "crew_head")
            put(ws, sf, f"{CW.NAME}{r.row}", crew.name, "crew_head")
            # No apply op writes these: shown as export values (they still
            # feed the Cost Report's crew-priced formulas).
            put(ws, sf, f"{CW.HPS}{r.row}", crew.hours_per_shift, "export_value")
            put(ws, sf, f"{CW.CFACT}{r.row}", crew.crew_factor, "export_value")
            put(ws, sf, f"{CW.HEADCOUNT}{r.row}", F.crew_sum(CW.COUNT, span), "crew_head")
            put(ws, sf, f"{CW.RATE}{r.row}", F.crew_sum(CW.EXTENDED, span), "crew_money")
            _tags(ws, r.row, "CREW", crew.id, crew.v)
            put(ws, sf, f"{CW.EXPORT}{r.row}", crew.hourly_rate)
        elif r.kind == "NOTE":
            put(ws, sf, f"{CW.NAME}{r.row}", LIBRARY_BANNER, "banner")
            _tags(ws, r.row, "NOTE")
        elif r.kind == "CREW_END":
            put(ws, sf, f"{CW.NAME}{r.row}", CREW_END_CUE, "note")
            _tags(ws, r.row, "CREW_END")
        else:
            write_member(ws, sf, plan, r)


def write_member(ws, sf, plan, r):
    """One MEMBER row. ``sheets/templates.py`` writes Estimate Navigator's
    prototype member with it: its crew-row helper (R) anchors at the Crews
    header row, so the pasted copy's ``MAX(R$4:R{row-1})`` is right on the
    Crews sheet (on ``_templates`` it spans the Cost Report prototypes'
    column R, harmless)."""
    m = r.obj
    put(ws, sf, f"{CW.CODE}{r.row}", m.classification, "input_text")
    put(ws, sf, f"{CW.COUNT}{r.row}", m.count, "input_count")
    put(ws, sf, f"{CW.LIBRATE}{r.row}",
        F.member_library_rate(r.row, plan.tabs["rates"], plan.labor_span), "calc_rate")
    put(ws, sf, f"{CW.OVERRIDE}{r.row}", m.hourly_rate_override, "input_money")
    put(ws, sf, f"{CW.EFFECTIVE}{r.row}", F.member_effective(r.row), "calc_rate")
    _tags(ws, r.row, "MEMBER", m.id)
    put(ws, sf, f"{CW.RATE_ID}{r.row}", m.labor_rate_id)
    put(ws, sf, f"{CW.EXPORT}{r.row}", m.effective_hourly_rate)
    put(ws, sf, f"{CW.EXTENDED}{r.row}", F.member_extended(r.row))


def crew_cells(plan, crew_id):
    """The Crews cells a Cost Report activity formula reads, or None."""
    row = plan.crew_rows.get(crew_id)
    if row is None:
        return None
    tab = plan.tabs["crews"]
    return {"rate": F.qualified(tab, CW.RATE, row.row), "hps": F.qualified(tab, CW.HPS, row.row),
            "factor": F.qualified(tab, CW.CFACT, row.row),
            "headcount": F.qualified(tab, CW.HEADCOUNT, row.row)}
