"""What the reader knows about the fieldbook workbook's layout.

Everything here mirrors `packs/fieldbook/units.yaml`; `test_readback_layout.py`
reads that file -- and the units.yaml of every pack that declares
`derived_from: fieldbook` -- and fails the moment they disagree, so a pack
edit can never leave the reader looking at the wrong column.
"""
from __future__ import annotations

#: The layout contract this reader understands: a pack's
#: `format_pack.readback_family` (its `derived_from`, else its own name) must
#: be this. The workbook's own `estimate_format` stamp names the pack itself.
FAMILY = "fieldbook"

ROOT_PACK = FAMILY

#: Item sheets: the hidden kind tag column.
KIND_COL = "Q"
#: Every kind tag the pack writes.
KINDS = frozenset({"ITEM", "NOTE", "HEAD", "TAKEOFF", "RECAP", "TOTAL", "TASK",
                   "CREW", "LINE", "END", "SUBTOTAL", "PKG"})
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
    "measured": (("label", "A", False), ("unit", "C", False), ("count", "D", True),
                 ("length", "E", True), ("width", "F", True), ("height", "G", True),
                 ("footing_cy", "H", True), ("wall_cy", "I", True), ("deck_cy", "J", True),
                 ("other_cy", "K", True), ("weight_lb", "L", True), ("adjust", "N", True)),
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
        return "FGHKLMPRSTV"
    if kind == "LINE":
        return "MNOPRSTV"
    if kind == "TASK":
        return "RS"
    if kind == "END":
        return "R"
    if kind == "NOTE":
        return "R" if in_task else ""
    if kind == "SUBTOTAL":
        return "AIKLMNOPRTV"
    if kind == "RECAP":
        return "ABIKLMNOP"
    if kind == "ITEM":
        return "J" if has_takeoff else ""
    if kind == "TAKEOFF":
        return "B" if takeoff_kind == "measured" else ""
    if kind == "TOTAL":
        if label == "Takeoff total":
            # the measured total adds the unit, the other-units note and the model sum
            return "BCFGHM" if takeoff_kind == "measured" else "BFG"
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

#: Work packages (only when the spec has `work_packages`): the summary sheet,
#: and the tag in Q1 of each `Sub <package>` sheet (laid out per package by a
#: `for_each` book entry, so its title is the package's, not a fixed name).
SUMMARY_SHEET = "Sub Spreads"
PKG_TAG = "PKG"
PACKAGE_SUMMARY_SHEET, PACKAGE_TAG = SUMMARY_SHEET, PKG_TAG
#: Package sheets: the selector's label (column E of its head row; the value is
#: in the next column), and the header texts of the vendors row (`package_lines`).
PKG_SELECTOR_LABEL = "CARRYING"
PKG_HEADERS = {"item": "Item", "line": "Line", "qty": "Qty", "uom": "U/M", "rate": "$ / unit",
               "pick": "Carry from", "arr": "ARR", "arr_ext": "ARR ext", "carry": "CARRY",
               "source": "Source", "state": "State", "ext": "ext"}
#: Column-A labels of the two rows under the vendors row.
PKG_QUOTE_REF_LABEL = "Quote ref"
PKG_SURCHARGE_LABEL = "Surcharge % of invoice"
#: The items block: its head row's B text, and the B text of each item row.
PKG_ITEMS_HEAD = "By item"
PKG_ITEM_ROW_LABEL = "item ARR cost"
#: The totals row's A text; the conditions grid's head row (B text).
PKG_TOTAL_LABEL = "TOTAL"
PKG_CONDITIONS_LABEL = "Conditions"
#: Item sheets' work-package columns: the SP/PKG row tag and the ARR-basis cost.
PACKAGE_ROW_TAG_COL, ARR_BASIS_COL = "U", "V"

#: Fixed-shape book sheets scanned for typed-over formulas against a fresh
#: build of the spec (their shape depends only on the items, which must match).
BASELINE_SHEETS = ("Bid Form", "Cost Summary", "Markup", "Checks", SUMMARY_SHEET)
