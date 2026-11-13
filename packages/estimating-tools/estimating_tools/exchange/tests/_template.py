"""A small template pack, written by the tests themselves (``make(dir)``): one
blocks sheet ``Estimate`` whose formulas use every form the lint accepts --
a resource's own row and its activity's multiplier, found through the
owner-row helper by whole-column ``INDEX`` (so a resource prices right
only where the helper is), an activity's sums over its brackets, a stepped
activity's shifts over its steps, an item's total by whole-column lookup
of its activities' costs, the rows-above form for a parent's multiplier --
plus two ``display`` sheets -- ``Shares`` (one row per allocation share)
and ``Lines`` (two regions: each activity's resource lines, a crew activity
adding a charge row from its variant; then the warnings under a fixed
heading) -- a blocks sheet ``Crews`` (each crew its block of members, a
library crew from its ``library`` variant with a NOTE banner), a flat sheet
``Bid`` (bid lines and bid totals in two regions under three named rows), a rates sheet ``Rates`` (a section per rate
kind), the hidden
``_wb`` and ``_templates`` sheets, and the pack's
``pack.yaml``. The payload the tests
fill it from is HeavyBook's fixture (``heavybook/tests/fixtures``)."""
from __future__ import annotations

from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.workbook.defined_name import DefinedName

TAB, SHARES, LINES, PROTO = "Estimate", "Shares", "Lines", "_templates"
CREWS = "Crews"
BID = "Bid"
RATES = "Rates"
HEADER, FIRST = 3, 4
#: The Crews sheet's prototypes (its own kind column, no activity key).
CREW_PROTOS = ("mb.tpl.crew", "mb.tpl.library", "mb.tpl.member")
#: Visible columns and their headings.
COLUMNS = {"A": "Code", "B": "Description", "C": "Qty / count", "D": "Shifts / type",
           "E": "Unit cost", "F": "Total"}
#: Hidden tag and helper columns.
KIND, ID, V, PARENT, KEY, REF, OWNER = "G", "H", "I", "J", "K", "L", "M"
ITEM_OF, COST, MULT, AKEY = "N", "O", "P", "Q"
#: An activity's crew id (a label) and its crew's heads, read live off the
#: Crews sheet by the crew key helper there (Crews column ``S``).
CREW_OF, CREW_HEADS = "R", "S"

DECLARATION = {
    "schema": 1,
    "pack": {"name": "mini-book", "version": "1", "contract": "1"},
    "kind": "template",
    "prototypes": {"item": "mb.tpl.item", "element_qty": "mb.tpl.element_qty",
                   "group": "mb.tpl.group", "activity": "mb.tpl.activity",
                   "stepped": "mb.tpl.stepped", "step": "mb.tpl.step",
                   "resource": "mb.tpl.resource", "crew": "mb.tpl.crew",
                   "library": "mb.tpl.library", "member": "mb.tpl.member"},
    "sheets": {
        "estimate": {
            "tab": TAB, "role": "blocks", "first_row": FIRST, "header_row": HEADER,
            "columns": dict(COLUMNS),
            "tags": {"kind": KIND, "id": ID, "v": V,
                     "parent": {"column": PARENT,
                                "derived": ["STEP", "RESOURCE", "STEPS", "START", "END"]},
                     "key": KEY, "ref": REF, "owner_row": OWNER},
            "rows": ["ITEM", "ELEMENT_QTY", "GROUP"],
            "blocks": {
                "activity": {"kind": "ACTIVITY", "recursive": True, "within": ["ITEM", "GROUP"],
                             "children": ["steps", "resources"]},
                "steps": {"marker": {"open": "STEPS", "close": "START"}, "row": "STEP",
                          "optional": True},
                "resources": {"marker": {"open": "START", "close": "END"}, "row": "RESOURCE"},
            },
            "markers": {"STEPS": {}, "START": {}, "END": {}},
            "fields": {
                "ITEM": {"estimated_unit_price": "E"},
                "ELEMENT_QTY": {"override_value": "C"},
                "ACTIVITY": {"name": "B", "count": "C", "duration_shifts": "D"},
                "STEP": {"name": "B", "duration": "C"},
                "RESOURCE": {"name": "B", "quantity": "C", "component_type": "D",
                             "unit_cost": "E"},
            },
            "formulas": {"ITEM": ["F"], "ACTIVITY": ["F", COST, MULT, CREW_HEADS],
                         "RESOURCE": ["F"],
                         "ACTIVITY.stepped": ["D"], "*": [AKEY]},
            "labels": {"ITEM": {"A": "item_number", "B": "description"},
                       "ELEMENT_QTY": {"A": "key", "B": "element.name"},
                       "ACTIVITY": {"A": "code", ITEM_OF: "item_id", CREW_OF: "crew_id"}},
            "header": {"A1": "estimate.name", "A2": "exported_at"},
        },
        "shares": {
            "tab": SHARES, "role": "display", "first_row": 2, "header_row": 1,
            "tags": {"kind": "F", "id": "G"},
            "regions": [{"at": 2, "rows": ["SHARE"]}],
            "prototypes": {"SHARE": "mb.fill.share"},
            "labels": {"SHARE": {"A": "activity_id", "B": "item_id", "C": "fraction"}},
        },
        "crews": {
            "tab": CREWS, "role": "blocks", "first_row": 4, "header_row": 3,
            "columns": {"A": "Class", "B": "Name", "C": "Count", "E": "Override", "I": "Heads"},
            "tags": {"kind": "K", "id": "L", "v": "M",
                     "parent": {"column": "N", "derived": ["MEMBER", "NOTE", "CREW_END"]},
                     "ref": "O", "owner_row": "R"},
            "blocks": {"crew": {"kind": "CREW", "children": ["members"]},
                       "members": {"marker": {"open": "CREW", "close": "CREW_END"},
                                   "row": "MEMBER", "banner": "NOTE"}},
            "markers": {"NOTE": {}, "CREW_END": {}},
            "fields": {"MEMBER": {"classification": "A", "count": "C",
                                  "hourly_rate_override": "E"}},
            "formulas": {"CREW": ["I"], "*": ["S"]},
            "labels": {"CREW": {"B": "name"}},
        },
        "bid": {
            "tab": BID, "role": "flat", "first_row": 1, "header_row": 6,
            "columns": {"A": "Item", "C": "Value", "F": "Scope", "G": "Override", "I": "Total"},
            "tags": {"kind": "J", "id": "K", "v": "L", "name": "T"},
            "rows": ["SECTION", "ITEM_BID", "GROUP", "BID_TOTAL"],
            "regions": [{"at": 7, "rows": ["SECTION", "ITEM_BID", "GROUP"]},
                        {"at": 9, "rows": ["BID_TOTAL"]}],
            "prototypes": {"SECTION": "mb.fill.section", "ITEM_BID": "mb.fill.item_bid",
                           "GROUP": "mb.fill.bid_group", "BID_TOTAL": "mb.fill.bid_total"},
            "fields": {"ITEM_BID": {"scope": "F", "bid_unit_price_override": "G"}},
            "formulas": {"BID_TOTAL": ["I"]},
            "labels": {"SECTION": {"A": "name"}, "ITEM_BID": {"A": "item_number"},
                       "BID_TOTAL": {"A": "name"}},
            "named_rows": {"name_column": "T", "value_column": "C",
                           "rows": {"markup_percentage": {"kind": "ESTIMATE", "input": True},
                                    "markup_amount": {"kind": "BID_INPUT", "input": True},
                                    "indirect_cost": {"kind": "BID_FIGURE"}}},
        },
        "rates": {
            "tab": RATES, "role": "rates", "first_row": 1, "tags": {"kind": "F"},
            "columns_by_key": {"id": "A", "name": "B", "unit": "C", "rate": "D"},
            "sections": {"labor": "Labor rates", "equipment": "Equipment rates",
                         "material": "Material costs"},
            "regions": [{"at": 1, "rows": ["RATE_SECTION"]}],
            "prototypes": {"RATE_SECTION": "mb.fill.rates"},
            "labels": {"RATE_TITLE": {"A": "title"},
                       "RATE": {"A": "id", "B": "name", "C": "unit", "D": "rate", "E": "link"}},
        },
        "lines": {
            "tab": LINES, "role": "display", "first_row": 2, "header_row": 1,
            "tags": {"kind": "F", "id": "G"},
            "regions": [{"at": 2, "rows": ["ACTIVITY"]}, {"at": 4, "rows": ["WARNING"]}],
            "prototypes": {"ACTIVITY": "mb.fill.lines", "ACTIVITY.crew": "mb.fill.lines.crew",
                           "WARNING": "mb.fill.warning"},
            "labels": {"CHARGE": {"A": "code", "B": "crew.name"},
                       "RESOURCE": {"A": "activity.code", "B": "name",
                                    "C": "activity.item.item_number"},
                       "WARNING": {"A": "activity.code", "B": "text"}},
        },
    },
}


def _owner_row(r):
    return f'=IF({KIND}{r}="ACTIVITY",ROW(),MAX({OWNER}${HEADER}:{OWNER}{r - 1}))'


def _chain(r):
    return f"=INDEX(${ID}:${ID},MAX(${OWNER}{r},1))"


def _resource_total(r):
    """A resource's total: quantity x unit cost x its activity's extended
    multiplier, found at the row the owner-row helper names (HeavyBook's
    ``formulas._act``) -- a row without the helper prices at 0."""
    return f"=C{r}*E{r}*INDEX(${MULT}:${MULT},MAX(${OWNER}{r},1))"


def _activity(ws, r, start, end, steps=None):
    ws[f"{KIND}{r}"] = "ACTIVITY"
    ws[f"F{r}"] = f"=SUM(F{start}:F{end})"
    ws[f"{COST}{r}"] = f"=F{r}"
    ws[f"{MULT}{r}"] = (f'=C{r}*IF(${PARENT}{r}="",1,INDEX({MULT}${HEADER}:{MULT}{r - 1},'
                        f'MATCH(${PARENT}{r},${AKEY}${HEADER}:${AKEY}{r - 1},0)))')
    if steps:
        ws[f"D{r}"] = f"=SUM(C{steps[0]}:C{steps[1]})"
    ws[f"{CREW_HEADS}{r}"] = (f'=IF(${CREW_OF}{r}="",0,INDEX({CREWS}!$I:$I,'
                              f'MATCH(${CREW_OF}{r},{CREWS}!$S:$S,0)))')


def _block_row(ws, r, kind):
    ws[f"{KIND}{r}"] = kind
    ws[f"{PARENT}{r}"] = _chain(r)
    if kind == "RESOURCE":
        ws[f"F{r}"] = _resource_total(r)


def make(directory: Path, *, declaration=None, edit=None) -> Path:
    """Write the pack (``pack.yaml``, ``template.xlsx``) into ``directory``.
    ``declaration`` replaces the document; ``edit(wb)`` changes the workbook
    before it is saved (a test's defect)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = TAB
    for letter, heading in COLUMNS.items():
        ws[f"{letter}{HEADER}"] = heading
    for letter in "GHIJKLMNOPQRS":
        ws.column_dimensions[letter].hidden = True
    sh = wb.create_sheet(SHARES)
    for letter, heading in zip("ABCDE", ("activity", "item", "fraction", "row", "cost")):
        sh[f"{letter}1"] = heading
    sh["G1"] = "id"
    sh.column_dimensions["F"].hidden = sh.column_dimensions["G"].hidden = True
    ln = wb.create_sheet(LINES)
    for letter, heading in zip("ABCDE", ("code", "line", "item", "qty", "cost")):
        ln[f"{letter}1"] = heading
    ln["A3"] = "Warnings"                         # between the two regions
    ln.column_dimensions["F"].hidden = ln.column_dimensions["G"].hidden = True
    cw = wb.create_sheet(CREWS)
    for letter, heading in (("A", "Class"), ("B", "Name"), ("C", "Count"), ("E", "Override"),
                            ("I", "Heads")):
        cw[f"{letter}3"] = heading
    for letter in "KLMNORS":
        cw.column_dimensions[letter].hidden = True
    bid = wb.create_sheet(BID)
    for r_, (name, kind) in enumerate((("markup_percentage", "ESTIMATE"),
                                       ("markup_amount", "BID_INPUT"),
                                       ("indirect_cost", "BID_FIGURE")), start=2):
        bid[f"A{r_}"], bid[f"J{r_}"], bid[f"T{r_}"] = name, kind, name
    for letter, heading in (("A", "Item"), ("C", "Value"), ("F", "Scope"), ("G", "Override"),
                            ("I", "Total")):
        bid[f"{letter}6"] = heading
    bid["A8"] = "Bid totals"
    for letter in "JKLMT":
        bid.column_dimensions[letter].hidden = True
    rt = wb.create_sheet(RATES)
    rt.column_dimensions["E"].hidden = rt.column_dimensions["F"].hidden = True
    stamp = wb.create_sheet("_wb")
    stamp.sheet_state = "hidden"
    tpl = wb.create_sheet(PROTO)
    tpl.sheet_state = "hidden"
    names = {}
    r = FIRST
    # item, element quantity, group: one row each.
    tpl[f"{KIND}{r}"] = "ITEM"
    tpl[f"F{r}"] = f"=SUMIF(${ITEM_OF}:${ITEM_OF},${ID}{r},${COST}:${COST})"
    names["mb.tpl.item"] = (r, r)
    r += 1
    tpl[f"{KIND}{r}"] = "ELEMENT_QTY"
    names["mb.tpl.element_qty"] = (r, r)
    r += 1
    tpl[f"{KIND}{r}"] = "GROUP"
    tpl[f"B{r}"] = "Unassigned elements"
    names["mb.tpl.group"] = (r, r)
    r += 1
    # activity: ACTIVITY, START, RESOURCE, END.
    _activity(tpl, r, r + 1, r + 3)
    for n, kind in enumerate(("START", "RESOURCE", "END"), 1):
        _block_row(tpl, r + n, kind)
    names["mb.tpl.activity"] = (r, r + 3)
    r += 4
    # stepped: ACTIVITY, STEPS, STEP, START, RESOURCE, END.
    _activity(tpl, r, r + 3, r + 5, steps=(r + 1, r + 3))
    for n, kind in enumerate(("STEPS", "STEP", "START", "RESOURCE", "END"), 1):
        _block_row(tpl, r + n, kind)
    names["mb.tpl.stepped"] = (r, r + 5)
    r += 6
    _block_row(tpl, r, "RESOURCE")
    names["mb.tpl.resource"] = (r, r)
    r += 1
    _block_row(tpl, r, "STEP")
    names["mb.tpl.step"] = (r, r)
    r += 2
    # share (display): its activity's cost, found by id, times its fraction.
    tpl[f"F{r}"] = "SHARE"
    tpl[f"D{r}"] = f"=MATCH($A{r},'{TAB}'!${AKEY}:${AKEY},0)"
    tpl[f"E{r}"] = f"=INDEX('{TAB}'!${COST}:${COST},$D{r})*$C{r}"
    names["mb.fill.share"] = (r, r)
    r += 1
    # Lines (display): an activity's resource lines; its crew
    # variant adds a charge row above them.
    tpl[f"F{r}"] = "RESOURCE"
    tpl[f"E{r}"] = f"=INDEX('{TAB}'!$F:$F,MATCH($G{r},'{TAB}'!${ID}:${ID},0))"
    names["mb.fill.lines"] = (r, r)
    r += 1
    tpl[f"F{r}"], tpl[f"D{r}"] = "CHARGE", "crew"
    tpl[f"F{r + 1}"] = "RESOURCE"
    tpl[f"E{r + 1}"] = f"=INDEX('{TAB}'!$F:$F,MATCH($G{r + 1},'{TAB}'!${ID}:${ID},0))"
    names["mb.fill.lines.crew"] = (r, r + 1)
    r += 2
    tpl[f"F{r}"] = "WARNING"
    names["mb.fill.warning"] = (r, r)
    r += 2

    def crew_block(key, kinds):
        nonlocal r
        end = r + len(kinds) - 1
        for n, kind in enumerate(kinds):
            tpl[f"K{r + n}"] = kind
            if kind != "CREW":
                tpl[f"N{r + n}"] = f"=INDEX($L:$L,MAX($R{r + n},1))"
            tpl[f"S{r + n}"] = f'=IF($K{r + n}="CREW",$L{r + n},"")'   # the crew key
        tpl[f"I{r}"] = f"=SUM(C{r}:C{end})"
        names[key] = (r, end)
        r = end + 1
    crew_block("mb.tpl.crew", ("CREW", "MEMBER", "CREW_END"))
    crew_block("mb.tpl.library", ("CREW", "NOTE", "MEMBER", "CREW_END"))
    crew_block("mb.tpl.member", ("MEMBER",))
    tpl[f"I{r - 1}"] = None                     # a member row sums nothing
    r += 1
    # Bid (flat): one row per kind, each its own prototype.
    for key, kind in (("mb.fill.section", "SECTION"), ("mb.fill.item_bid", "ITEM_BID"),
                      ("mb.fill.bid_group", "GROUP"), ("mb.fill.bid_total", "BID_TOTAL")):
        tpl[f"J{r}"] = kind
        if kind == "GROUP":
            tpl[f"A{r}"] = "Other items"
        if kind == "BID_TOTAL":
            tpl[f"I{r}"] = f"=SUM(I$8:I{r - 1})*0"
        names[key] = (r, r)
        r += 1
    # Rates: per section its title, the headings, one row per rate, a gap.
    for n, kind in enumerate(("RATE_TITLE", "RATE_HEAD", "RATE", "RATE_GAP")):
        tpl[f"F{r + n}"] = kind
    for letter, heading in zip("ABCD", ("Id", "Name", "Unit", "Rate")):
        tpl[f"{letter}{r + 1}"] = heading
    names["mb.fill.rates"] = (r, r + 3)
    r += 4
    for name, (first, last) in names.items():
        if name.startswith("mb.tpl.") and name not in CREW_PROTOS:   # the Estimate sheet's
            for row in range(first, last + 1):
                tpl[f"{AKEY}{row}"] = f'=IF(${KIND}{row}="ACTIVITY",${ID}{row},"")'
    for name, (first, last) in names.items():
        wb.defined_names[name] = DefinedName(name, attr_text=f"'{PROTO}'!${first}:${last}")
    if edit is not None:
        edit(wb)
    wb.save(directory / "template.xlsx")
    (directory / "pack.yaml").write_text(
        yaml.safe_dump(declaration if declaration is not None else DECLARATION, sort_keys=False),
        encoding="utf-8")
    return directory
