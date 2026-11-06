"""Hidden ``_templates``: the prototype rows Estimate Navigator's Insert
copies (#1486 sub-project 4).

Every prototype row is written by the Cost Report's and Crews' own writers
(``cost_report.write_row``, ``crews.write_member``) from a blank payload
object, so its formulas, styles, number formats and data validation are a
real row's. Each carries its kind marker, a blank id and ``v``, its owner
tag as the chain formula every block row holds (``formulas.owner_id``,
``formulas.crew_id``: a pasted row names the block it lands in; the
prototype activity's own parent is blank, a root), and blank inputs
(``exchange.reader.fields.inputs_for_decl`` over HeavyBook's own
declaration: what read-back reads is what is blanked). The Cost Report's
column set and its header row 4 are kept, so the activity-row helper's
absolute ``AJ$4`` anchor is right after a paste; the member sits below, in
the Crews column set, with its crew-row helper anchored at ``R$4`` the same
way (``formulas.crew_row``).

A prototype activity is a root (``AA = K``) with no crew; a prototype
member has no rate id, so its library rate reads 0 until a Rate override is
typed or the change is applied and the book rebuilt. Read-back never reads
this sheet (the declaration does not list it).
"""
from __future__ import annotations

import functools

from estimating_tools.heavybook import columns as C
from estimating_tools.heavybook.columns import CR
from estimating_tools.heavybook.layout import FIRST_ROW, Plan, Row
from estimating_tools.exchange.reader import fields as RF
from estimating_tools.heavybook.sheets.common import factory, put, setup_sheet
from estimating_tools.heavybook.sheets.cost_report import write_row, write_validations
from estimating_tools.heavybook.sheets.crews import write_member

SHEET = "_templates"
TITLE = "Estimate Navigator templates"
SUBTITLE = "Prototype rows Estimate Navigator's Insert copies -- do not edit"

#: Cost Report prototypes, top to bottom from ``FIRST_ROW``: the
#: ``layout.TEMPLATE_NAMES`` key and its rows' kinds.
BLOCKS = (
    ("activity", ("ACTIVITY", "START", "RESOURCE", "END")),
    ("stepped", ("ACTIVITY", "STEPS", "STEP", "START", "RESOURCE", "END")),
    ("resource", ("RESOURCE",)),
    ("step", ("STEP",)),
)


class _Blank:
    """A prototype row's payload object: every attribute is blank (None)
    except the ones given."""

    def __init__(self, **given):
        self.__dict__.update(given)

    def __getattr__(self, name):
        if name.startswith("__"):   # hasattr, copy and pickle probe dunders
            raise AttributeError(name)
        return None


class _NoShares:
    """The payload a prototype activity sees: no allocation shares."""

    def shares_of_activity(self, activity_id):
        return []


@functools.lru_cache(maxsize=None)
def _declaration():
    """HeavyBook's own declaration (the default tab titles: the bound fields
    do not depend on them), loaded once by the pack's one path
    (``HeavyBookPack.declaration``). Imported here, not at the top, so the
    build's import graph stays flat: a sheet writer does not pull in the
    pack, the reader and the CLI it imports."""
    from estimating_tools.heavybook.pack import pack

    return pack().declaration()


def _clear(ws, sheet, row, *, stepped=False):
    """Blank what a blank payload object still writes: every input cell (a
    resource's Burden incl. reads "N" from a None flag) and the activity's
    in-bid fraction (0 with no shares)."""
    for inp in RF.inputs_for_decl(_declaration(), sheet, row.kind, stepped=stepped):
        ws[f"{inp.letter}{row.row}"].value = None
    if sheet == "cost_report" and row.kind == "ACTIVITY":
        ws[f"{CR.H1}{row.row}"].value = None


def _block(ws, sf, plan, rows):
    """One prototype block on its own throwaway plan: the spans its
    activity's formulas sum are its own START..END and STEPS..START rows."""
    mini = Plan(tabs=plan.tabs)
    first = {}
    for row in rows:
        first.setdefault(row.kind, row.row)
    stepped = "STEPS" in first
    if "START" in first:
        mini.resource_span[None] = (first["START"], first["END"])
    if stepped:
        mini.step_span[None] = (first["STEPS"], first["START"])
    for row in rows:
        row.obj = _Blank(steps=[_Blank()] if stepped else [])
        write_row(ws, sf, mini, _NoShares(), row)
        _clear(ws, "cost_report", row, stepped=stepped)


def write_templates(ws, plan, style) -> dict:
    """Write the prototypes; returns ``{TEMPLATE_NAMES key: (first row, last
    row)}``."""
    sf = factory(style)
    ws.sheet_state = "hidden"
    setup_sheet(ws, sf, style, "cost_report", title=TITLE, subtitle=SUBTITLE)
    out, written, r = {}, [], FIRST_ROW
    for key, kinds in BLOCKS:
        rows = [Row(row=r + n, kind=kind) for n, kind in enumerate(kinds)]
        _block(ws, sf, plan, rows)
        written += rows
        out[key] = (r, r + len(kinds) - 1)
        r += len(kinds)
    write_validations(ws, written)
    r += 1   # a blank row, then the Crews headings over the member
    for col in C.CREWS:
        put(ws, sf, f"{col.letter}{r}", style.column("crews", col.key)["heading"], "head")
    r += 1
    member = Row(row=r, kind="MEMBER", obj=_Blank())
    write_member(ws, sf, plan, member)
    _clear(ws, "crews", member)
    out["member"] = (r, r)
    return out
