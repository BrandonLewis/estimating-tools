"""The contract's tables (contract spec parts 2 and 3), as every pack and the
reader share them. A pack binds a field to a column; whether the field may
be written, how it is read and what it may hold is decided here.

``FIELDS`` is the ``WRITABLE`` set per kind in the reader's spelling: each
``Field`` names how the cell is read (``reader``), whether BidSheet.ai
accepts a cleared value (``clear``) and the baseline attribute when it is
not the field's name (``attr``). ``TAGS`` is part 2's identity table: the
hidden tags a row of each kind carries. ``CHOICES`` are the coded inputs'
allowed spellings. Nothing here knows a column letter."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    reader: str
    clear: bool = False
    attr: str | None = None


#: How a cell is read into BidSheet.ai's spelling. ``number``, ``count`` and
#: ``summed`` parse numbers (``count`` whole; ``summed`` refuses a number
#: typed as text, because the book sums the column with ``SUMIF``, which
#: skips text); ``name`` and ``text`` strip text (``name`` reads blank as
#: None, ``text`` as ""); the rest are coded (``CHOICES``).
READERS = ("number", "count", "summed", "name", "text", "unit", "step_unit", "time_unit",
           "type", "basis", "flag", "scope")

#: Coded readers -> allowed spellings (matched case-insensitively).
CHOICES = {
    "unit": ("DAYS", "HOURS"),
    "step_unit": ("DAYS", "HOURS"),
    "time_unit": ("DAYS", "HOURS"),
    "type": ("labor", "equipment", "material", "subcontractor", "other"),
    "basis": ("production", "flat"),
    "flag": ("Y", "N"),
    "scope": ("included", "excluded"),
}
#: What a blank coded cell reads as, per reader (None: blank stays None).
BLANK_CHOICE = {"step_unit": "DAYS", "time_unit": ""}

#: The writable fields per kind (``WRITABLE``, contract part 3). ACTIVITY
#: ``duration_shifts`` is writable only on an activity without steps
#: (source takeover, part 2); the reader applies that with the ``stepped``
#: qualifier. ESTIMATE's two inputs are the Bid Form's named rows.
FIELDS = {
    "ITEM": {"quantity_override": Field("number", clear=True),
             "estimated_unit_price": Field("number")},
    "ELEMENT_QTY": {"override_value": Field("number", clear=True, attr="override")},
    "ACTIVITY": {"name": Field("name"), "production_rate": Field("number"),
                 "production_unit": Field("unit"), "hours_per_shift": Field("number"),
                 "crew_factor": Field("number"), "duration_shifts": Field("number"),
                 "count": Field("count")},
    "STEP": {"name": Field("name"), "duration": Field("summed"),
             "duration_unit": Field("step_unit")},
    "RESOURCE": {"name": Field("name"), "quantity": Field("number"),
                 "unit": Field("text", clear=True), "unit_cost": Field("number"),
                 "time_value": Field("number", clear=True),
                 "time_unit": Field("time_unit", clear=True), "component_type": Field("type"),
                 "labor_cost_basis": Field("basis"),
                 "burden_percentage": Field("number", clear=True),
                 "includes_burden": Field("flag")},
    "MEMBER": {"classification": Field("name"), "count": Field("number"),
               "hourly_rate_override": Field("number", clear=True)},
    "ITEM_BID": {"scope": Field("scope"), "bid_unit_price_override": Field("number", clear=True)},
    "ESTIMATE": {"markup_percentage": Field("number"), "markup_amount": Field("number")},
}

#: Fields written only when the kind has no steps block (``stepped`` qualifier).
STEPLESS_ONLY = {"ACTIVITY": ("duration_shifts",)}

#: Part 2's identity table: the hidden tags a row of each contract kind
#: carries. ``parent`` is the owning row (an activity for a step or
#: resource, a crew for a member, the parent activity for an activity).
TAGS = {
    "ESTIMATE": ("id", "v", "name"),
    "SECTION": ("id", "v"),
    "ITEM": ("id", "v"),
    "ITEM_BID": ("id", "v"),
    "BID_TOTAL": ("id",),
    "ELEMENT_QTY": ("id", "key", "v"),
    "ACTIVITY": ("id", "v", "parent"),
    "STEP": ("id", "v", "parent"),
    "RESOURCE": ("id", "v", "parent"),
    "CREW": ("id", "v"),
    "MEMBER": ("id", "parent"),
}
#: A marker row names its owner and nothing else; a named row (a Bid Form
#: input or figure found by name) carries its name.
MARKER_TAGS = ("parent",)
NAMED_ROW_TAGS = ("name",)

#: Kinds a book may grow: rows an estimator inserts, copies or types.
GROWABLE = ("ACTIVITY", "STEP", "RESOURCE", "MEMBER")
#: The container of an owner kind: the flat row its occurrences sit under
#: (an activity's rows sit under an item). A sheet that lists the container
#: among its rows names it in the owner block's ``within``.
CONTAINER = {"ACTIVITY": "ITEM"}
#: The read model's collection per growable row kind: the attribute of the
#: owning row's baseline that holds its rows (``Activity.steps`` ...). A
#: child block's ``row`` is one of these.
COLLECTIONS = {"STEP": "steps", "RESOURCE": "resources", "MEMBER": "members"}
#: The library rate kinds, in the order the payload lists them
#: (``model.Workbook.rates``) and a pack's rates sheet lays them out.
RATE_KINDS = ("labor", "equipment", "material")
#: Kinds the contract has a move op for.
MOVABLE = ("ACTIVITY",)
#: The two conditions a ``formulas`` entry may carry (``KIND.stepped``: an
#: activity whose block has the optional steps block; ``KIND.included``: an
#: item whose scope is not excluded).
QUALIFIERS = ("stepped", "included")


def tags_for(kind: str, *, marker: bool = False, named: bool = False) -> tuple:
    """The tags a row of ``kind`` carries: the identity table's for a contract
    kind, ``parent`` for a marker, ``name`` for a named row, none otherwise."""
    if kind in TAGS:
        return TAGS[kind]
    if marker:
        return MARKER_TAGS
    if named:
        return NAMED_ROW_TAGS
    return ()


#: The server's ref kind an op names its row by, per op prefix
#: (``resource.update`` -> ``resource``): what a plan's ``created`` and
#: ``versions`` key rows by.
OP_KINDS = {"estimate": "estimate", "item": "item", "element": "element",
            "activity": "activity", "step": "step", "resource": "resource", "crew": "crew"}
#: The book row kind an existing row's op names, per op prefix.
OP_ROWS = {"estimate": "ESTIMATE", "item": "ITEM", "element": "ELEMENT_QTY",
           "activity": "ACTIVITY", "step": "STEP", "resource": "RESOURCE", "crew": "CREW"}
#: The row kind a creating op makes (a typed row with no kind becomes one).
CREATES = {"activity.create": "ACTIVITY", "step.add": "STEP", "resource.create": "RESOURCE"}
#: What a row's ``ref`` tag holds, per kind: the read-model attribute (a
#: resource's rate link as ``labor:<id>``, a member's labour rate id).
REF_ATTR = {"RESOURCE": "rate_link", "MEMBER": "labor_rate_id"}
#: The read-model attributes that place a row among others: a server change
#: to one moves cells the book's formulas address by position (an
#: activity's item, parent and crew), so a refresh cannot patch it in place.
PLACEMENT = {"ACTIVITY": ("item_id", "parent_id", "crew_id")}
