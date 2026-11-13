"""Walk the book's sheets top to bottom, as the declaration declares them
(engine spec, Read: Scan and Markers): one walker for a ``blocks`` sheet,
one for a ``flat`` sheet.

Each row's kind, id, ``v``, parent, key and name come from the hidden tag
cells the declaration names -- never from row numbers, which go stale the
moment the estimator inserts or deletes a row. The owner of a block row or
marker comes from position -- the occurrence it sits in -- when the
declaration says its parent tag is derived: that cell holds a formula the
build writes, and it is never read. A ``blocks`` sheet's walk tracks
context (``reader.blocks.Blocks`` holds the sheet's rules):

- the current container: the owner block's ``within`` kinds end an open
  occurrence, and the contract's container among them (an ITEM row, until
  the next ITEM or GROUP row) is what the rows below sit under;
- the current occurrence: its owner row (an ACTIVITY, a CREW), then each
  child block in turn -- opened by its open marker (STEPS, START) or by the
  owner row itself (a crew's members), closed by the last child's close
  marker (END, CREW_END) -- the brackets every formula sums over; a banner
  kind (a crew's NOTE) inside is skipped, its position checked only for
  belonging to the right owner.

A row with no kind is spacing when every visible cell is empty, else a
*typed* row -- a candidate new row, placed by the block it sits in. A
kind-tagged row with a blank id is a new row too (an Estimate Navigator
prototype, or a hand copy of one); a new activity's markers carry a blank
owner id, as its ACTIVITY row does. A new STEP, RESOURCE or MEMBER row
left blank (``untouched_row``) where no row of its kind can go is skipped
with a note rather than refused. Marker integrity is checked here: a marker
that is missing, duplicated, out of order or under the wrong owner refuses
the read. So does a value typed on a marker row: the book prices it live (a
crew's SUMs span its CREW_END and NOTE rows, an activity's SUMIF its STEPS
and START rows), but read-back would drop it. Only the cue cell may hold
its cue.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from estimating_tools.exchange import contract
from estimating_tools.exchange.reader.blocks import Blocks
from estimating_tools.exchange.reader.errors import REBUILD

MARKER = f"a marker row was deleted or moved -- undo it, or {REBUILD}"
FIRST_STEP = ("add the activity's first step in BidSheet.ai, then rebuild -- its Shifts "
              "is typed, and a first step would restamp it to a figure the book never showed")
#: A step in a new activity made from the plain prototype (not yet in
#: BidSheet.ai, so FIRST_STEP's advice can't be followed).
FIRST_STEP_NEW = ("a new activity made from the plain prototype has no steps -- insert a "
                  "new stepped activity instead")
TYPED_ON_MARKER = ("something was typed on a marker row -- insert a row above the "
                   "marker and type there")

#: The contract's bid item kind on a flat sheet: a typed row with no kind
#: above its last row sits among the bid items (``Scan.ignored``).
ITEM_ROW = "ITEM_BID"

#: What a problem calls a row of a contract kind, where that is not the
#: kind lowered.
_NOUNS = {"ELEMENT_QTY": "element quantity", "MEMBER": "crew member"}

#: The Line attributes a row's tags fill (``Declaration.row_kinds()`` names).
_IDENT = ("id", "v", "parent", "key", "name")

#: Collection name -> the row kind it holds (``contract.COLLECTIONS`` inverted).
_KIND_OF = {collection: kind for kind, collection in contract.COLLECTIONS.items()}


def cue(decl, key, kind):
    """The cue cell and text of marker ``kind`` on sheet ``key``: ``(column,
    text)``, or None when the marker has none."""
    marker = decl.sheets[key].markers.get(kind)
    return marker.cue if marker is not None else None


def visible(decl, key) -> tuple:
    """The columns an estimator sees (and can type in) on sheet ``key``."""
    return decl.visible(key)


def written(decl, key, kind) -> dict:
    """Fixed text a row's writer puts in a visible cell of ``kind`` (a step's
    ``step`` tag): ``{column: text}``; not typed, so it doesn't make a new
    row touched."""
    return decl.sheets[key].written.get(kind, {})


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
    #: Blocks sheet: the container row the row sits under (the item on the
    #: Cost Report; None outside any, and on a sheet without a container).
    item_id: object = None
    #: Blocks sheet: the occurrence (an activity's, a crew's) whose block
    #: the row sits in.
    occ: Occurrence | None = None
    #: Blocks sheet: "head" (owner row..first marker), else the child block
    #: the row sits in ("steps", "resources", "members").
    zone: str | None = None
    #: The cells read as fields: ``fields``' cache of ``fields.Read`` by how
    #: the row was read (``(kind, stepped)``, or ``("estimate", name)``).
    read: object = None
    #: The row's kind as tagged -- a pack's form (fieldbook's TASK, CREW,
    #: LINE); ``kind`` is its contract kind. None for a typed row, and on a
    #: flat sheet (read as ``kind``).
    form: str | None = None
    #: ``(sheet rank, row)``: where the row sits across several sheets (one
    #: per item), the order lists of rows are sorted in.
    at: tuple = ()


@dataclass(eq=False)
class Occurrence:
    """One owner row (an ACTIVITY, a CREW) and its bracketed block.
    ``original`` is decided by classify (False for a copy)."""
    line: Line
    blocks: Blocks
    #: The container row it sits under (an item), or None.
    item_id: object = None
    zone: str = "head"
    closed: bool = False
    #: Child blocks whose open marker was seen (or that the owner row opened).
    opened: set = field(default_factory=set)
    #: Child block name -> its rows.
    rows: dict = field(default_factory=dict)
    typed: list = field(default_factory=list)
    original: bool = True
    #: The occurrence of its parent activity it sits under by position (set
    #: by classify): the nearest one above it in the same item, or None.
    pos_parent: Occurrence | None = None
    #: ``new:aN`` for a copy or a new activity (set by classify).
    token: str | None = None
    #: A new activity whose rows are all blank (set by classify): dropped
    #: with one note, its rows unread.
    skipped: bool = False
    #: Blank-id rows of an optional child block found in the head zone
    #: (owner row..first marker): judged once the block shows whether it
    #: has that child (``_resolve_head_steps``).
    head_steps: list = field(default_factory=list)
    #: The closing marker's row, once reached.
    end_row: int | None = None
    #: Joined kind -> its rows in this block (a task's notes, joined into
    #: its description by a ``rows`` binding).
    joined: dict = field(default_factory=dict)

    def rows_of(self, kind) -> list:
        """The rows of the child block holding ``kind`` (empty when the
        sheet declares no such block)."""
        name = self.blocks.rows_named(kind)
        return self.rows.setdefault(name, []) if name else []

    # The same lookups under the read model's names (``contract.COLLECTIONS``).
    @property
    def steps(self):
        return self.rows_of(_KIND_OF["steps"])

    @property
    def resources(self):
        return self.rows_of(_KIND_OF["resources"])

    @property
    def members(self):
        return self.rows_of(_KIND_OF["members"])

    @property
    def has_steps_marker(self) -> bool:
        return self.blocks.rows_named("STEP") in self.opened

    @property
    def id(self):
        return self.line.id

    @property
    def ref(self):
        """What an op names this owner by: its id, or its copy's token."""
        return self.id if self.original else self.token


@dataclass
class Scan:
    """The scanned sheets: per sheet key, its lines and (a blocks sheet) its
    occurrences. The named properties find a sheet by the contract kind it
    owns (``cost_report``: the ACTIVITY sheets'; ``crew_lines``: the CREW
    sheet; ``bid_form``: the flat sheet)."""
    decl: object = None
    lines: dict = field(default_factory=dict)
    owners: dict = field(default_factory=dict)
    #: Typed rows outside any block (each refuses the read).
    stray: list = field(default_factory=list)
    #: Untouched new rows where no row of their kind can go, dropped with a
    #: note: (sheet key, row, what) -- ``classify.Changes.skipped``.
    skipped: list = field(default_factory=list)
    #: Flat sheet rows with a value but no kind among its bid item rows: not
    #: read (bid items are added in BidSheet.ai), named in the notes.
    ignored: list = field(default_factory=list)

    def _sheets(self):
        return self.decl.sheets.items() if self.decl is not None else ()

    def sheets_of(self, owner_kind) -> list:
        """The keys of the blocks sheets whose owner block is
        ``owner_kind``, in declaration order (fieldbook: one per item)."""
        return [key for key, sheet in self._sheets()
                if sheet.role == "blocks" and any(b.kind == owner_kind
                                                  for b in sheet.owner_blocks())]

    def sheet_of(self, owner_kind):
        """The key of the first blocks sheet whose owner block is ``owner_kind``, or None."""
        found = self.sheets_of(owner_kind)
        return found[0] if found else None

    @property
    def flat_sheet(self):
        """The key of the first flat sheet, or None."""
        return next((key for key, sheet in self._sheets() if sheet.role == "flat"), None)

    def _lines(self, key) -> list:
        return self.lines.setdefault(key, []) if key is not None else []

    def _owners(self, key) -> list:
        return self.owners.setdefault(key, []) if key is not None else []

    def all_lines(self) -> list:
        """Every scanned line, in scan order."""
        return [line for lines in self.lines.values() for line in lines]

    @property
    def cost_report(self) -> list:
        """Every line of every ACTIVITY sheet, sheet by sheet."""
        return [x for key in self.sheets_of("ACTIVITY") for x in self._lines(key)]

    @property
    def crew_lines(self) -> list:
        return self._lines(self.sheet_of("CREW"))

    @property
    def bid_form(self) -> list:
        return self._lines(self.flat_sheet)

    @property
    def activities(self) -> list:
        """Every activity occurrence of every ACTIVITY sheet, sheet by sheet."""
        return [o for key in self.sheets_of("ACTIVITY") for o in self._owners(key)]

    @property
    def crews(self) -> list:
        return self._owners(self.sheet_of("CREW"))


def is_formula(cell) -> bool:
    return cell.data_type == "f"


def _typed(ws, r, letters) -> bool:
    return any(not is_blank(ws[f"{col}{r}"].value) for col in letters)


def untouched_row(decl, ws, r, sheet, kind) -> bool:
    """Row ``r``, a row of ``kind``, holds nothing typed: every visible cell
    is blank, a formula (a prototype's own formulas don't count), its
    kind's written text or, on a marker, its cue. Every input cell is
    visible, so this covers the declaration's bound fields too."""
    expected = dict(written(decl, sheet, kind))
    marker_cue = cue(decl, sheet, kind)
    if marker_cue is not None:
        expected[marker_cue[0]] = marker_cue[1]
    for col in visible(decl, sheet):
        cell = ws[f"{col}{r}"]
        if is_blank(cell.value) or is_formula(cell):
            continue
        if col in expected and _text(cell.value) == expected[col]:
            continue
        return False
    return True


_SKIP_WHAT = {"STEP": "an empty inserted step", "RESOURCE": "an empty inserted resource line",
              "MEMBER": "an empty inserted crew member"}


def _skip_blank_new(decl, ws, s, sheet, line) -> bool:
    """A blank-id row left untouched: noted in ``s.skipped`` (True), not read."""
    if line.id is not None or not untouched_row(decl, ws, line.row, sheet,
                                                line.form or line.kind):
        return False
    s.skipped.append((sheet, line.row,
                      _SKIP_WHAT.get(line.kind, f"an empty inserted {_noun(line.kind)}")))
    return True


def _line(decl, ws, sheet, r, kind, ident) -> Line:
    """A kind-tagged row: each of its tags (``ident``: tag name -> letter)
    read into the Line attribute of that name. A tag the sheet declares
    derived for ``kind`` is a formula the reader does not read."""
    tags = decl.sheets[sheet].tags
    line = Line(sheet=sheet, row=r, kind=kind)
    for name, letter in ident.items():
        if name not in _IDENT:
            continue
        tag = tags.get(name)
        if tag is not None and kind in tag.derived:
            continue
        value = ws[f"{letter}{r}"].value
        setattr(line, name, norm_id(value) if name in ("id", "parent") else _text(value))
    return line


# -- labels ----------------------------------------------------------------------

def _a(noun: str) -> str:
    return "an" if noun[:1] in "aeiou" else "a"


def _noun(kind: str) -> str:
    return _NOUNS.get(kind, kind.lower())


def _baseline(book, kind, ident):
    """The baseline row of owner ``kind`` with id ``ident``, or None. The
    model's lookups are per contract kind."""
    lookup = {"ACTIVITY": book.model.activity, "CREW": book.model.crew}.get(kind)
    return lookup(ident) if lookup is not None and ident is not None else None


def owner_label(book, kind, ident, fallback=None):
    """``activity <id> (<name>)`` / ``crew <id> (<name>)`` for the estimator;
    the name from the baseline, else ``fallback``. A blank id names a
    marker with no owner id."""
    noun = _noun(kind)
    if ident is None:
        return f"{_a(noun)} {noun} marker with no {noun} id"
    base = _baseline(book, kind, ident)
    name = base.name if base is not None else fallback
    return f"{noun} {ident} ({name})" if name else f"{noun} {ident}"


def activity_label(book, activity_id, fallback=None):
    return owner_label(book, "ACTIVITY", activity_id, fallback)


def _growable(book, key, kind) -> bool:
    """The book may grow ``kind`` on sheet ``key``: a blank id there is a new row."""
    return kind in book.decl.growable(key)


def _block_label(book, occ):
    """An occurrence's label: an owner row with a blank id is a new one
    where the book may grow the owner kind."""
    kind = occ.blocks.owner.kind
    if occ.id is None and _growable(book, occ.line.sheet, kind):
        return f"a new {_noun(kind)}"
    return owner_label(book, kind, occ.id)


def _marker_label(book, blocks, line, occ):
    """A misplaced marker's label. With a derived owner tag (a formula the
    reader does not read) position names it: the open occurrence it sits
    in (a new owner's when that row has no id), else -- outside any block,
    or after one closed -- a stray marker. With a stored tag, one with a
    blank owner id is a new owner's (the prototypes' markers carry none)
    where the book may grow the owner kind, unless it sits in an existing
    occurrence's open block: that one's id was cleared."""
    kind = blocks.owner.kind
    tag = book.decl.sheets[line.sheet].tags.get("parent")
    if tag is not None and line.kind in tag.derived:
        if occ is None or occ.closed:
            return f"a stray {line.kind} marker"
        if occ.id is None and _growable(book, line.sheet, kind):
            return f"a new {_noun(kind)}'s {line.kind} marker"
        return owner_label(book, kind, occ.id)
    inside_existing = occ is not None and not occ.closed and occ.id is not None
    if line.parent is None and not inside_existing and _growable(book, line.sheet, kind):
        return f"a new {_noun(kind)}'s {line.kind} marker"
    return owner_label(book, kind, line.parent)


def _row_label(kind) -> str:
    noun = _noun(kind)
    return f"{_a(noun)} {noun} row"


def _outside(blocks, kind) -> str:
    """A child block's row outside any occurrence's block: named by the
    block's markers, or by the owner row when that opens the block."""
    child = blocks.block_of_row(kind)
    owner = _noun(blocks.owner.kind)
    if child.open == blocks.owner.kind:
        where = f"between its {owner} row and its end marker"
    else:
        where = f"between its {child.open} and {child.close} markers"
    return (f"this {_noun(kind)} row sits outside {_a(owner)} {owner}'s block ({where}) "
            "-- move it back")


def _inside(book, blocks, occ, kind) -> str:
    """A flat row inside an occurrence's block."""
    back = (f"under its {_noun(blocks.container)}" if blocks.container else "")
    return (f"{_row_label(kind)} sits inside {_block_label(book, occ)}'s block -- move it back"
            + (f" {back}" if back else ""))


# -- markers ---------------------------------------------------------------------

def _check_marker_blank(decl, ws, key, tab, r, kind, problems):
    """A marker row's visible cells are blank, bar its cue cell holding its cue."""
    marker_cue = cue(decl, key, kind)
    for col in visible(decl, key):
        value = ws[f"{col}{r}"].value
        if is_blank(value):
            continue
        if marker_cue is not None and col == marker_cue[0] and _text(value) == marker_cue[1]:
            continue
        problems.add(tab, r, col, TYPED_ON_MARKER)


def _foreign(sheet, line, occ) -> bool:
    """A marker or banner whose stored owner tag names another owner (one
    pasted in from another block). A derived tag is a formula the reader
    does not read, so it cannot say; position decides."""
    tag = sheet.tags.get("parent")
    if tag is None or line.kind in tag.derived:
        return False
    return line.parent != occ.id


def _resolve_head_steps(book, ws, s, occ, problems, tab):
    """Judge the blank-id rows of an optional child block parked in
    ``occ``'s head zone, now that the block shows whether it has that
    child: skipped when untouched; else misplaced in an occurrence that has
    it (they belong between its markers), or a first step in one without."""
    key = occ.line.sheet
    for line in occ.head_steps:
        if _skip_blank_new(book.decl, ws, s, key, line):
            continue
        if occ.blocks.rows_named(line.kind) in occ.opened:
            problems.add(tab, line.row, None, _outside(occ.blocks, line.kind))
        else:
            problems.add(tab, line.row, None, FIRST_STEP if occ.id is not None
                         else FIRST_STEP_NEW)
    occ.head_steps = []


def _close(book, ws, s, occ, problems, tab):
    """An occurrence still open when its sheet, its container or the next
    owner row ends it: its closing marker is gone."""
    if occ is None or occ.closed:
        return
    _resolve_head_steps(book, ws, s, occ, problems, tab)
    problems.add(tab, occ.line.row, None, f"{_block_label(book, occ)}: {MARKER}")
    occ.closed = True


def _check_steps_marker(book, occ, problems, tab):
    """An optional child's open marker (STEPS) appears exactly when the
    baseline owner has rows of that block: the collection its row kind
    names in the read model (``contract.COLLECTIONS``: an activity's
    ``steps``)."""
    kind = occ.blocks.owner.kind
    base = _baseline(book, kind, occ.id)
    if base is None:
        return
    for child in occ.blocks.children:
        if not child.optional or child.open == kind:
            continue
        if _has_rows(book, base, child.row) != (child.name in occ.opened):
            problems.add(tab, occ.line.row, None, f"{owner_label(book, kind, occ.id)}: {MARKER}")


def _has_rows(book, base, row_kind) -> bool:
    """Whether the baseline owner ``base`` has rows of ``row_kind``. Steps and
    members hang off their owner in the read model; resources are kept flat
    on the workbook with an ``activity_id``, so they are looked up there."""
    if row_kind == "RESOURCE":
        return bool(book.model.resources_of(base.id))
    return bool(getattr(base, contract.COLLECTIONS[row_kind], ()))


# -- the walks -------------------------------------------------------------------

def _walk_blocks(book, s, problems, key):
    sheet = book.decl.sheets[key]
    blocks = Blocks(sheet)
    classes = sheet.kinds()
    ws, tab = book.ws(key), book.tab(key)
    conf = book.kinds[key]
    kind_col, kinds = conf["kind_cell"], conf["kinds"]
    seen = visible(book.decl, key)
    container, occ = None, None
    lines, owners = s.lines.setdefault(key, []), s.owners.setdefault(key, [])
    for r in range(book.first_row(key), ws.max_row + 1):
        kind = _text(ws[f"{kind_col}{r}"].value)
        if kind is None:
            if not _typed(ws, r, seen):
                continue
            inside = occ is not None and not occ.closed
            line = Line(sheet=key, row=r, kind=None, item_id=container,
                        occ=occ if inside else None, zone=occ.zone if inside else None)
            lines.append(line)
            (occ.typed if inside else s.stray).append(line)
            continue
        if kind not in kinds:
            problems.add(tab, r, kind_col, f"unknown row kind {kind!r} -- {REBUILD}")
            continue
        # The tag names the row's form; blocks and markers speak contract kinds.
        form, kind = kind, sheet.contract_kind(kind)
        line = _line(book.decl, ws, key, r, kind, kinds[form])
        line.form = form
        line.item_id = container
        lines.append(line)
        if kind in blocks.within:
            _close(book, ws, s, occ, problems, tab)
            occ = None
            container = line.id if kind == blocks.container else None
        elif classes.get(form) == "joined":
            # A joined row (a task's note) belongs to the block it sits in;
            # outside one it is the sheet's own (an item's scope note), and
            # nothing reads it.
            if occ is not None and not occ.closed:
                line.occ = occ
                occ.joined.setdefault(form, []).append(line)
        elif classes.get(form) == "row":
            if occ is not None and not occ.closed:
                problems.add(tab, r, None, _inside(book, blocks, occ, kind))
        elif kind == blocks.owner.kind:
            _close(book, ws, s, occ, problems, tab)
            occ = Occurrence(line=line, blocks=blocks, item_id=container)
            line.occ = occ
            owners.append(occ)
            first = blocks.opened_by_owner
            if first is not None:
                occ.zone = first.name
                occ.opened.add(first.name)
            if blocks.container and container is None:
                what = _noun(blocks.container)
                problems.add(tab, r, None, f"{_block_label(book, occ)} sits outside any "
                             f"{what} -- move it back under {_a(what)} {what}")
        elif blocks.is_marker(kind):
            if (occ is None or occ.closed or occ.zone not in blocks.allowed_zones(kind)
                    or _foreign(sheet, line, occ)):
                problems.add(tab, r, None, f"{_marker_label(book, blocks, line, occ)}: {MARKER}")
                continue
            line.occ = occ
            _check_marker_blank(book.decl, ws, key, tab, r, kind, problems)
            child = blocks.opens(kind)
            if child is not None:
                occ.zone = child.name
                occ.opened.add(child.name)
                _resolve_head_steps(book, ws, s, occ, problems, tab)
            else:
                occ.closed, occ.end_row = True, r
                _check_steps_marker(book, occ, problems, tab)
        elif classes.get(form) == "banner":
            if occ is None or occ.closed or _foreign(sheet, line, occ):
                problems.add(tab, r, None, f"{_marker_label(book, blocks, line, occ)}: {MARKER}")
                continue
            line.occ = occ
            _check_marker_blank(book.decl, ws, key, tab, r, kind, problems)
        elif classes.get(form) == "child":
            child = blocks.block_of_row(kind)
            if (kind in blocks.optional_head_rows and line.id is None
                    and occ is not None and not occ.closed):
                if occ.zone == "head":
                    # Above the block's first marker: whether the occurrence
                    # has this child shows only at a later marker.
                    occ.head_steps.append(line)
                    continue
                if child.name not in occ.opened:
                    # A new step in an activity without steps: as for a typed
                    # one (a new activity's can't be added in BidSheet.ai first).
                    if not _skip_blank_new(book.decl, ws, s, key, line):
                        problems.add(tab, r, None, FIRST_STEP if occ.id is not None
                                     else FIRST_STEP_NEW)
                    continue
            if occ is None or occ.closed or occ.zone != child.name:
                if _skip_blank_new(book.decl, ws, s, key, line):
                    continue
                problems.add(tab, r, None, _outside(blocks, kind))
                continue
            line.occ, line.zone = occ, child.name
            occ.rows.setdefault(child.name, []).append(line)
    _close(book, ws, s, occ, problems, tab)


def _walk_flat(book, s, problems, key):
    """Only rows with a kind are read: a flat sheet's labels and headings
    carry none. The walk starts at the declaration's first row and steps
    over the header row (the Bid Form's named rows sit above its column
    headings). A typed row without a kind is not a new row here, unlike on
    a blocks sheet: a flat sheet has no block to add it to, and its labels
    carry no kind either. One with a value among the bid item rows is kept
    in ``ignored``, so the change set can say it was not read."""
    sheet = book.decl.sheets[key]
    ws, tab = book.ws(key), book.tab(key)
    conf = book.kinds[key]
    kind_col, kinds = conf["kind_cell"], conf["kinds"]
    seen = visible(book.decl, key)
    lines = s.lines.setdefault(key, [])
    candidates = []
    header_row = book.header_row(key)
    for r in range(book.first_row(key), ws.max_row + 1):
        if r == header_row:
            continue
        kind = _text(ws[f"{kind_col}{r}"].value)
        if kind is None:
            if _typed(ws, r, seen):
                candidates.append(Line(sheet=key, row=r, kind=None))
            continue
        if kind not in kinds:
            problems.add(tab, r, kind_col, f"unknown row kind {kind!r} -- {REBUILD}")
            continue
        lines.append(_line(book.decl, ws, key, r, kind, kinds[kind]))
    rows = [x.row for x in lines if x.kind in sheet.rows]
    if rows:
        last_item = max((x.row for x in lines if x.kind == ITEM_ROW), default=0)
        s.ignored += [x for x in candidates if min(rows) < x.row < last_item]


def _walk_order(item) -> int:
    """Blocks sheets first, the one with a container (the Cost Report)
    before the rest (the Crews), then flat sheets: the order problems are
    reported in."""
    _key, sheet = item
    if sheet.role == "blocks":
        return 0 if Blocks(sheet).container else 1
    return 2


def sheet_ranks(decl) -> dict:
    """Sheet key -> its rank in the walk (``_walk_order``, then declaration
    order): the first part of ``Line.at``, and how notes across sheets sort."""
    return {key: n for n, (key, _sheet) in enumerate(sorted(decl.sheets.items(),
                                                             key=_walk_order))}


def scan(book, problems) -> Scan:
    s = Scan(decl=book.decl)
    ranks = sheet_ranks(book.decl)
    for key, sheet in sorted(book.decl.sheets.items(), key=_walk_order):
        rank = ranks[key]
        if sheet.role == "blocks":
            _walk_blocks(book, s, problems, key)
        elif sheet.role == "flat":
            _walk_flat(book, s, problems, key)
        for line in s.lines.get(key, ()):
            line.at = (rank, line.row)
    return s
