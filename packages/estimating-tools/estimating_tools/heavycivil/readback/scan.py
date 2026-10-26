"""Walk the Cost Report, Crews and Bid Form top to bottom.

Each row's kind, id, ``v``, parent and key come from the hidden cells the
layout's ``row_kinds`` names -- never from row numbers, which go stale the
moment the estimator inserts or deletes a row. The walk tracks context:

- the current item (an ITEM row, until the next ITEM or GROUP row);
- the current activity occurrence: its ACTIVITY row, then (if it has steps)
  its STEPS marker and STEP rows, its START marker, its RESOURCE rows and its
  END marker -- the brackets every formula sums over;
- the current crew: its CREW row until its CREW_END marker (a NOTE banner
  inside is skipped; its position is checked only for belonging to the
  right crew -- the banner is display-only).

A row with no kind is spacing when every visible cell is empty, else a
*typed* row -- a candidate new row, placed by the block it sits in. Marker
integrity is checked here: a marker that is missing, duplicated, out of
order or under the wrong activity or crew refuses the read. So does a value
typed on a marker row: the book prices it live (a crew's SUMs span its
CREW_END and NOTE rows, an activity's SUMIF its STEPS and START rows), but
read-back would drop it. Only the cue cell may hold its cue.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from estimating_tools.heavycivil import columns as C
from estimating_tools.heavycivil.readback.errors import REBUILD
from estimating_tools.heavycivil.sheets.cost_report import END_CUE
from estimating_tools.heavycivil.sheets.crews import CREW_END_CUE, LIBRARY_BANNER

MARKER = f"a marker row was deleted or moved -- undo it, or {REBUILD}"
TYPED_ON_MARKER = ("something was typed on a marker row -- insert a row above the "
                   "marker and type there")

#: Per sheet and marker kind: the cue cell and the cue it holds. A marker's
#: visible cells are blank except that one, and only while it holds its cue.
CUES = {
    "cost_report": {"STEPS": None, "START": None, "END": (C.CR.DESC, END_CUE)},
    "crews": {"NOTE": (C.CW.NAME, LIBRARY_BANNER), "CREW_END": (C.CW.NAME, CREW_END_CUE)},
}

#: The columns an estimator sees (and can type in), per sheet.
VISIBLE = {
    "cost_report": tuple(c.letter for c in C.COST_REPORT if not c.hidden),
    "crews": tuple(c.letter for c in C.CREWS if not c.hidden),
    "bid_form": tuple(c.letter for c in C.BID_FORM if not c.hidden),
}

#: Bid Form kinds that bound its bid item rows.
_BID_ROWS = ("SECTION", "GROUP", "ITEM_BID")

#: identified_by key -> Line attribute.
_IDENT = {"id": "id", "element_id": "id", "v": "v", "parent_id": "parent",
          "activity_id": "parent", "crew_id": "parent", "quantity_key": "key",
          "name": "name"}


def norm_id(value):
    """A hidden id cell as the payload spells it: an int when it is one
    (Excel may hand back 7.0 or "7"), else the text, else None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    text = str(value).strip()
    if not text:
        return None
    return int(text) if text.isascii() and text.isdigit() else text


def _text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


@dataclass(eq=False)
class Line:
    """One scanned row. ``kind`` is None for a typed row."""
    sheet: str
    row: int
    kind: str | None
    id: object = None
    v: object = None
    parent: object = None
    key: object = None
    name: object = None
    #: Cost Report: the item the row sits under (None outside any item).
    item_id: object = None
    #: Cost Report: the activity occurrence whose block the row sits in.
    occ: Occurrence | None = None
    #: Cost Report: "head" (ACTIVITY..first marker), "steps" (STEPS..START),
    #: "resources" (START..END); Crews: "members".
    zone: str | None = None
    #: Crews: the crew block the row sits in.
    crew: CrewBlock | None = None
    #: The cells read as fields: ``fields``' cache of ``fields.Read`` by how
    #: the row was read (``(kind, stepped)``, or ``("estimate", name)``).
    read: object = None


@dataclass(eq=False)
class Occurrence:
    """One ACTIVITY row and its bracketed block. ``original`` is decided by
    classify (False for a copy)."""
    line: Line
    item_id: object
    zone: str = "head"
    has_steps_marker: bool = False
    closed: bool = False
    steps: list = field(default_factory=list)
    resources: list = field(default_factory=list)
    typed: list = field(default_factory=list)
    original: bool = True
    #: The occurrence of its parent activity it sits under by position (set
    #: by classify): the nearest one above it in the same item, or None.
    pos_parent: Occurrence | None = None
    #: ``new:aN`` for a copy (set by classify).
    token: str | None = None

    @property
    def id(self):
        return self.line.id

    @property
    def ref(self):
        """What an op names this activity by: its id, or its copy's token."""
        return self.id if self.original else self.token


@dataclass(eq=False)
class CrewBlock:
    line: Line
    members: list = field(default_factory=list)
    typed: list = field(default_factory=list)
    closed: bool = False

    @property
    def id(self):
        return self.line.id


@dataclass
class Scan:
    cost_report: list = field(default_factory=list)
    activities: list = field(default_factory=list)
    crews: list = field(default_factory=list)
    crew_lines: list = field(default_factory=list)
    bid_form: list = field(default_factory=list)
    #: Typed rows outside any block (each refuses the read).
    stray: list = field(default_factory=list)
    #: Bid Form rows with a value but no kind among its bid item rows: not
    #: read (bid items are added in BidSheet.ai), named in the notes.
    ignored: list = field(default_factory=list)


def _typed(ws, r, letters) -> bool:
    return any(not is_blank(ws[f"{col}{r}"].value) for col in letters)


def _line(ws, sheet, r, kind, ident) -> Line:
    line = Line(sheet=sheet, row=r, kind=kind)
    for key, letter in ident.items():
        attr = _IDENT.get(key)
        if attr is None:
            continue
        value = ws[f"{letter}{r}"].value
        if attr in ("id", "parent"):
            value = norm_id(value)
        elif attr in ("v", "key", "name"):
            value = _text(value)
        setattr(line, attr, value)
    return line


def _activity_label(book, activity_id, fallback=None):
    if activity_id is None:
        return "an activity marker with no activity id"
    a = book.model.activity(activity_id)
    name = a.name if a is not None else fallback
    return f"activity {activity_id} ({name})" if name else f"activity {activity_id}"


def _crew_label(book, crew_id):
    if crew_id is None:
        return "a crew marker with no crew id"
    c = book.model.crew(crew_id)
    return f"crew {crew_id} ({c.name})" if c is not None and c.name else f"crew {crew_id}"


def _check_marker_blank(ws, sheet, tab, r, kind, problems):
    """A marker row's visible cells are blank, bar its cue cell holding its cue."""
    cue = CUES[sheet][kind]
    for col in VISIBLE[sheet]:
        value = ws[f"{col}{r}"].value
        if is_blank(value):
            continue
        if cue is not None and col == cue[0] and _text(value) == cue[1]:
            continue
        problems.add(tab, r, col, TYPED_ON_MARKER)


def _close_activity(book, occ, problems, tab):
    if occ is None or occ.closed:
        return
    problems.add(tab, occ.line.row, None,
                 f"{_activity_label(book, occ.id)}: {MARKER}")
    occ.closed = True


def _check_steps_marker(book, occ, problems, tab):
    """STEPS appears exactly when the activity has steps in the baseline."""
    base = book.model.activity(occ.id)
    if base is not None and bool(base.steps) != occ.has_steps_marker:
        problems.add(tab, occ.line.row, None, f"{_activity_label(book, occ.id)}: {MARKER}")


def _cost_report(book, s, problems):
    ws, tab = book.ws("cost_report"), book.tab("cost_report")
    conf = book.kinds["cost_report"]
    kind_col, kinds = conf["kind_cell"], conf["kinds"]
    item, occ = None, None
    for r in range(book.layout["first_row"], ws.max_row + 1):
        kind = _text(ws[f"{kind_col}{r}"].value)
        if kind is None:
            if not _typed(ws, r, VISIBLE["cost_report"]):
                continue
            inside = occ is not None and not occ.closed
            line = Line(sheet="cost_report", row=r, kind=None, item_id=item,
                        occ=occ if inside else None, zone=occ.zone if inside else None)
            s.cost_report.append(line)
            (occ.typed if inside else s.stray).append(line)
            continue
        if kind not in kinds:
            problems.add(tab, r, kind_col, f"unknown row kind {kind!r} -- {REBUILD}")
            continue
        line = _line(ws, "cost_report", r, kind, kinds[kind])
        line.item_id = item
        s.cost_report.append(line)
        if kind in ("ITEM", "GROUP"):
            _close_activity(book, occ, problems, tab)
            occ = None
            item = line.id if kind == "ITEM" else None
        elif kind == "ELEMENT_QTY":
            if occ is not None and not occ.closed:
                problems.add(tab, r, None, "an element quantity row sits inside "
                             f"{_activity_label(book, occ.id)}'s block -- move it back "
                             "under its item")
        elif kind == "ACTIVITY":
            _close_activity(book, occ, problems, tab)
            occ = Occurrence(line=line, item_id=item)
            line.occ = occ
            s.activities.append(occ)
            if item is None:
                problems.add(tab, r, None, f"{_activity_label(book, line.id)} sits outside "
                             "any item -- move it back under an item")
        elif kind in ("STEPS", "START", "END"):
            allowed = {"STEPS": ("head",), "START": ("head", "steps"), "END": ("resources",)}
            if (occ is None or occ.closed or line.parent != occ.id
                    or occ.zone not in allowed[kind]):
                problems.add(tab, r, None, f"{_activity_label(book, line.parent)}: {MARKER}")
                continue
            line.occ = occ
            _check_marker_blank(ws, "cost_report", tab, r, kind, problems)
            if kind == "STEPS":
                occ.zone, occ.has_steps_marker = "steps", True
            elif kind == "START":
                occ.zone = "resources"
            else:
                occ.closed = True
                _check_steps_marker(book, occ, problems, tab)
        elif kind in ("STEP", "RESOURCE"):
            zone = "steps" if kind == "STEP" else "resources"
            if occ is None or occ.closed or occ.zone != zone:
                where = "STEPS and START" if kind == "STEP" else "START and END"
                problems.add(tab, r, None, f"this {kind.lower()} row sits outside an "
                             f"activity's block (between its {where} markers) -- move it back")
                continue
            line.occ, line.zone = occ, zone
            (occ.steps if kind == "STEP" else occ.resources).append(line)
    _close_activity(book, occ, problems, tab)


def _crews(book, s, problems):
    ws, tab = book.ws("crews"), book.tab("crews")
    conf = book.kinds["crews"]
    kind_col, kinds = conf["kind_cell"], conf["kinds"]
    crew = None

    def close():
        if crew is not None and not crew.closed:
            problems.add(tab, crew.line.row, None, f"{_crew_label(book, crew.id)}: {MARKER}")

    for r in range(book.layout["first_row"], ws.max_row + 1):
        kind = _text(ws[f"{kind_col}{r}"].value)
        if kind is None:
            if not _typed(ws, r, VISIBLE["crews"]):
                continue
            inside = crew is not None and not crew.closed
            line = Line(sheet="crews", row=r, kind=None, crew=crew if inside else None,
                        zone="members" if inside else None)
            s.crew_lines.append(line)
            (crew.typed if inside else s.stray).append(line)
            continue
        if kind not in kinds:
            problems.add(tab, r, kind_col, f"unknown row kind {kind!r} -- {REBUILD}")
            continue
        line = _line(ws, "crews", r, kind, kinds[kind])
        s.crew_lines.append(line)
        if kind == "CREW":
            close()
            crew = CrewBlock(line=line)
            line.crew = crew
            s.crews.append(crew)
        elif kind in ("NOTE", "CREW_END"):
            if crew is None or crew.closed or line.parent != crew.id:
                problems.add(tab, r, None, f"{_crew_label(book, line.parent)}: {MARKER}")
                continue
            _check_marker_blank(ws, "crews", tab, r, kind, problems)
            if kind == "CREW_END":
                crew.closed = True
        elif kind == "MEMBER":
            if crew is None or crew.closed:
                problems.add(tab, r, None, "this crew member row sits outside a crew's block "
                             "(between its crew row and its end marker) -- move it back")
                continue
            line.crew, line.zone = crew, "members"
            crew.members.append(line)
    close()


def _bid_form(book, s, problems):
    """Only rows with a kind: the Bid Form's labels and headings carry none
    (its estimate rows sit above the column headings, so the walk starts at
    row 1 and steps over the heading row). A typed row without a kind is
    ignored here, unlike on the Cost Report and Crews: the Bid Form has no
    blocks to add rows to, and its labels carry no kind either. One with a
    value among the bid item rows is kept in ``ignored``, so the change set
    can say it was not read."""
    ws, tab = book.ws("bid_form"), book.tab("bid_form")
    conf = book.kinds["bid_form"]
    kind_col, kinds = conf["kind_cell"], conf["kinds"]
    candidates = []
    for r in range(1, ws.max_row + 1):
        if r == C.BF.HEADER_ROW:
            continue
        kind = _text(ws[f"{kind_col}{r}"].value)
        if kind is None:
            if _typed(ws, r, VISIBLE["bid_form"]):
                candidates.append(Line(sheet="bid_form", row=r, kind=None))
            continue
        if kind not in kinds:
            problems.add(tab, r, kind_col, f"unknown row kind {kind!r} -- {REBUILD}")
            continue
        s.bid_form.append(_line(ws, "bid_form", r, kind, kinds[kind]))
    rows = [x.row for x in s.bid_form if x.kind in _BID_ROWS]
    if rows:
        last_item = max((x.row for x in s.bid_form if x.kind == "ITEM_BID"), default=0)
        s.ignored = [x for x in candidates if min(rows) < x.row < last_item]


def scan(book, problems) -> Scan:
    s = Scan()
    _cost_report(book, s, problems)
    _crews(book, s, problems)
    _bid_form(book, s, problems)
    return s
