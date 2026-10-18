"""What the reader knows about the fieldbook workbook's layout.

Everything here mirrors `packs/fieldbook/units.yaml`; `test_readback_layout.py`
reads that file and fails the moment the two disagree, so a pack edit can
never leave the reader looking at the wrong column.
"""
from __future__ import annotations

#: The pack whose workbooks this reader understands (the `estimate_format`
#: custom property is `"<name> <version>"`).
PACK_NAME = "fieldbook"

#: Item sheets: the hidden kind tag column.
KIND_COL = "Q"
#: Every kind tag the pack writes.
KINDS = frozenset({"ITEM", "NOTE", "HEAD", "TAKEOFF", "RECAP", "TOTAL", "TASK",
                   "CREW", "LINE", "END", "SUBTOTAL"})
#: Columns whose content makes an untagged row worth reporting (A..P).
VISIBLE_COLS = "ABCDEFGHIJKLMNOP"

# Input columns, by row kind.
ITEM_QTY = "G"
#: The ITEM row's description and unit: shown, but not inputs (band styles) --
#: an edit there is noticed, never read back (decision 13).
ITEM_DESC, ITEM_UOM = "B", "H"
TASK_CODE, TASK_DESC = "A", "B"
NOTE_TEXT = "A"
CREW_TRADE, CREW_COUNT, CREW_DAYS = "A", "D", "E"
LINE_NAME, LINE_QTY, LINE_UOM, LINE_PRICE = "A", "B", "C", "G"
LINE_TYPE, LINE_SOURCE, LINE_VENDOR = "H", "I", "J"
#: Takeoff rows: {takeoff kind: ((spec field, column, numeric?), ...)}.
TAKEOFF_FIELDS = {
    "linear":   (("label", "A", False), ("length_lf", "B", True), ("ref", "C", False)),
    "count":    (("label", "A", False), ("count", "B", True), ("ref", "C", False)),
    "measured": (("label", "A", False), ("length", "D", True), ("height", "E", True),
                 ("footing_cy", "F", True), ("wall_cy", "G", True), ("deck_cy", "H", True),
                 ("other_cy", "I", True)),
}
#: The spec list each takeoff kind keeps its rows in.
TAKEOFF_LIST = {"linear": "segments", "count": "units", "measured": "lines"}

#: Every input cell the pack styles as one, by (kind, takeoff kind or None).
#: The drift test checks units.yaml's input-styled cells against this.
INPUT_COLS = {
    ("ITEM", None): ITEM_QTY,
    ("TASK", None): TASK_CODE + TASK_DESC,
    ("CREW", None): CREW_TRADE + CREW_COUNT + CREW_DAYS,
    ("LINE", None): LINE_NAME + LINE_QTY + LINE_UOM + LINE_PRICE + LINE_TYPE + LINE_SOURCE + LINE_VENDOR,
    **{("TAKEOFF", k): "".join(col for _, col, _ in fields) for k, fields in TAKEOFF_FIELDS.items()},
}

#: Dropdown labels -> spec values (the `type_*` / `src_*` / `kind_*` /
#: `op_*` params' defaults in units.yaml).
LINE_TYPES = {"Material": "material", "Subcontract": "subcontract",
              "Equipment": "equipment", "Other": "other"}
LINE_SOURCES = {"QUOTE": "quote", "PLUG": "plug"}
RATE_KINDS = {"Labor": "labor", "Equipment": "equipment"}
OPERATOR = {"Yes": True, "No": False}


def formula_columns(kind: str, *, label=None, in_task: bool = False,
                    takeoff_kind: str | None = None, has_takeoff: bool = True) -> str:
    """The columns a row of `kind` holds formulas in -- a literal there was
    typed over a formula. `label` is the row's column-A text (TOTAL rows
    differ by it), `in_task` whether a NOTE sits in a task block."""
    if kind == "CREW":
        return "FGHKLMPRST"
    if kind == "LINE":
        return "MNOPRST"
    if kind == "TASK":
        return "RS"
    if kind == "END":
        return "R"
    if kind == "NOTE":
        return "R" if in_task else ""
    if kind == "SUBTOTAL":
        return "AIKLMNOPRT"
    if kind == "RECAP":
        return "ABIKLMNOP"
    if kind == "ITEM":
        return "J" if has_takeoff else ""
    if kind == "TAKEOFF":
        return "B" if takeoff_kind == "measured" else ""
    if kind == "TOTAL":
        if label == "Takeoff total":
            return "BFG"
        if label == "ITEM TOTAL":
            return "IKLMNOP"
        if isinstance(label, str) and label.startswith("PER "):
            return "KLMNOP"
    return ""


# Book sheets, located by their own labels.
#: The hidden prototype-row sheet Estimate Navigator copies from. It looks like
#: an item sheet (its row 1 is tagged ITEM) but is never one of the spec's.
TEMPLATES_SHEET = "_templates"
RATES_SHEET = "Rates"
RATES_HEAD = "Resource"                              # A of the table's head row
RATES_MARKER = "insert new rates above this row"     # A of the insert-above marker
SHIFT_LABEL = "Hours per crew-day"                   # A; the value is in B
RATE_NAME, RATE_KIND, RATE_BASE, RATE_BURDEN = "A", "B", "C", "D"
RATE_FRINGE, RATE_OPERATOR, RATE_FLAT, RATE_HOURLY = "E", "F", "G", "H"

MARKUP_SHEET = "Markup"
MARKUP_HEAD = "% of direct cost"                     # A of the grid's head row
MARKUP_TOTAL = "Total"                               # A of the grid's total row
MARKUP_ROWS = ("overhead", "insurance", "profit")    # the rows fieldbook lays out
#: Markup grid columns -> the spec's cost-type keys.
MARKUP_COLS = (("B", "labor"), ("C", "equipment"), ("D", "material"), ("E", "subcontract"))
BOND_LABEL = "Bond (% of bid)"                       # A; the value is in B
UNBALANCE_HEAD = "Unbalance $"                       # C of the unbalance head row
UNBALANCE_TOTAL = "Net unbalance (must be 0)"        # A of the unbalance total row

BID_FORM_SHEET = "Bid Form"
BID_DATE_LABEL = "Bid date"                          # A; the value is in B
#: The project name (bid_form_head's first row): shown, not an input.
BID_FORM_PROJECT = "A1"

#: Fixed-shape book sheets scanned for typed-over formulas against a fresh
#: build of the spec (their shape depends only on the items, which must match).
BASELINE_SHEETS = ("Bid Form", "Cost Summary", "Markup", "Checks")
