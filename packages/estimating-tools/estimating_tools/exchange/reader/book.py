"""Open an edited book and decode the baseline it carries.

The book carries the payload it was built from: ``_wb`` column B holds it
(zlib + base64, chunked) and the exchange stamp in A1 (``exchange.stamp``)
names the chunk count and the SHA-256 of the decoded JSON; ``exchange.baseline``
encodes it at build and decodes it here. Read-back diffs the book against that, never against a
fresh fetch: a re-fetch cannot tell an estimator's edit from a change made in
BidSheet.ai since the export.
"""
from __future__ import annotations

import functools
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from estimating_tools.exchange import baseline as hc_baseline
from estimating_tools.exchange import model
from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange.reader.errors import REBUILD, refuse

if TYPE_CHECKING:
    from estimating_tools.exchange.declaration import Declaration
    from estimating_tools.exchange.stamp import Stamp

#: The custom document property a pack's patch stamps on a book whose
#: committed apply it could not patch fully (the old baseline kept): every
#: read refuses such a book until it is rebuilt, which never carries it.
STALE_PROPERTY = "exchange_stale"


@dataclass
class Index:
    """Lookups over the baseline built once per read: the payload's raw rows
    by id (for fields the model does not keep -- ``description``, ``trade``,
    ``pieces``, cost codes), each activity's children, depth and cost code,
    and each step's activity."""
    raw_activities: dict
    raw_resources: dict
    raw_steps: dict
    children: dict
    depth: dict
    activity_code: dict
    step_owner: dict

    @classmethod
    def of(cls, doc, data):
        from estimating_tools.exchange.reader.scan import norm_id

        raw_activities = {norm_id(r.get("id")): r for r in doc.get("activities") or ()}
        raw_steps = {norm_id(st.get("id")): st for r in raw_activities.values()
                     for st in r.get("steps") or ()}
        children = {}
        for a in data.activities:
            children.setdefault(a.parent_id, []).append(a)
        by_id = {a.id: a for a in data.activities}
        depth = {}
        for a in data.activities:
            d, node = 0, a
            while node.parent_id is not None:
                d, node = d + 1, by_id[node.parent_id]
            depth[a.id] = d
        return cls(
            raw_activities=raw_activities,
            raw_resources={norm_id(r.get("id")): r for r in doc.get("resources") or ()},
            raw_steps=raw_steps,
            children=children,
            depth=depth,
            activity_code={aid: norm_id((r.get("activity_code") or {}).get("id"))
                           for aid, r in raw_activities.items()},
            step_owner={st.id: a for a in data.activities for st in a.steps},
        )

    def subtree(self, activity_id) -> list:
        """Every activity under ``activity_id`` (not itself)."""
        out, frontier = [], [activity_id]
        while frontier:
            kids = [k for f in frontier for k in self.children.get(f, ())]
            out += kids
            frontier = [k.id for k in kids]
        return out


@dataclass
class Book:
    """An opened book: the openpyxl workbook (formulas, not cached values),
    its stamp, its declaration, the decoded baseline payload (``doc``) and
    that payload parsed (``model``). ``kinds`` is the declaration's
    ``row_kinds()``: per sheet key, the kind cell and each kind's tags."""
    path: Path
    wb: object
    stamp: "Stamp"
    #: The stamp's declaration, loaded.
    decl: "Declaration"
    doc: dict
    model: model.Workbook
    kinds: dict = field(default_factory=dict)

    def tab(self, key):
        return self.decl.sheets[key].tab

    def first_row(self, key) -> int:
        return self.decl.sheets[key].first_row

    def header_row(self, key):
        return self.decl.sheets[key].header_row

    @functools.cached_property
    def index(self) -> Index:
        return Index.of(self.doc, self.model)

    @functools.cached_property
    def estimate_inputs(self) -> dict:
        """The estimate's input cells by name (``fields.estimate_inputs``),
        built once per book."""
        from estimating_tools.exchange.reader.fields import estimate_inputs

        return estimate_inputs(self)

    def ws(self, key):
        return self.wb[self.tab(key)]


def decode(ws, meta) -> dict:
    """The baseline payload from ``_wb`` column B (B1 down to the first empty
    cell), checked against ``meta`` (the stamp's ``baseline``) by the
    builder's own ``exchange.baseline.decode``."""
    if not isinstance(meta, dict):
        refuse(f"the book carries no baseline -- {REBUILD}", sheet=exchange_stamp.SHEET)
    # Not only text: a chunk Excel turned into a number is handed on, so
    # ``exchange.baseline.decode`` names it ("chunk k ... is not text").
    try:
        return hc_baseline.decode(exchange_stamp.chunks_of(ws), meta)
    except hc_baseline.BaselineError as exc:
        refuse(f"{exc} -- {REBUILD}", sheet=exchange_stamp.SHEET)


def load(path, pack=None) -> Book:
    """Open ``path`` and check it is a stamped book whose declaration loads,
    whose tabs are present and whose baseline is intact, or raise
    ReadRefused. ``pack`` is the detected pack, when the caller has one:
    every stamp goes through the pack's ``upgrade_stamp``, which upgrades an
    older stamp it wrote in memory and returns a current one unchanged. A
    book stamped before the exchange stamp is refused without one."""
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    path = Path(path)
    try:
        wb = load_workbook(path, data_only=False)
    except FileNotFoundError:
        refuse(f"no such file: {path}")
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError) as exc:
        refuse(f"cannot read {path} as an .xlsx workbook: {exc}")
    if exchange_stamp.SHEET not in wb.sheetnames:
        refuse(f"not an exchange workbook (no {exchange_stamp.SHEET} sheet) -- {REBUILD}")
    try:
        raw = exchange_stamp.read_cell(wb[exchange_stamp.SHEET])
    except exchange_stamp.StampError as exc:
        refuse(f"{exc} -- {REBUILD}", sheet=exchange_stamp.SHEET)
    # The pack upgrades any older stamp it wrote (a layout-2 book's layout
    # document, a stamp whose declaration predates this reader) and returns
    # a current one unchanged; the reader itself upgrades nothing.
    if hasattr(pack, "upgrade_stamp"):
        try:
            raw = pack.upgrade_stamp(raw, wb)
        except exchange_stamp.StampError as exc:
            refuse(f"{exc} -- {REBUILD}", sheet=exchange_stamp.SHEET)
    elif exchange_stamp.is_legacy(raw):
        version = raw.get("layout_version")
        refuse(f"this book was stamped before the exchange stamp (layout {version!r}); "
               f"the pack that can upgrade it was not given -- {REBUILD}",
               sheet=exchange_stamp.SHEET)
    try:
        st = exchange_stamp.parse(raw)
    except exchange_stamp.StampError as exc:
        refuse(f"{exc} -- {REBUILD}", sheet=exchange_stamp.SHEET)
    if st.contract != exchange_stamp.CONTRACT:
        refuse(f"this book targets contract {st.contract!r}; this reader reads contract "
               f"{exchange_stamp.CONTRACT} -- update the plugin, or {REBUILD}", sheet=exchange_stamp.SHEET)
    from estimating_tools.exchange.declaration import DeclarationError, load as load_declaration
    try:
        decl = load_declaration(st.declaration)
    except DeclarationError as exc:
        # A schema the reader does not know already says what to do.
        advice = "" if "update the plugin" in str(exc) else f" -- {REBUILD}"
        refuse(f"the book's declaration cannot be read ({exc}){advice}", sheet=exchange_stamp.SHEET)
    # The stamp and the declaration it carries name one pack. (A book
    # stamped under an older name is normalised by the pack's
    # ``upgrade_stamp`` before it gets here.)
    if st.pack.get("name") != decl.pack.name:
        refuse(f"the stamp names pack {st.pack.get('name')!r} but its declaration is "
               f"{decl.pack.name!r} -- {REBUILD}", sheet=exchange_stamp.SHEET)
    kinds = decl.row_kinds()
    stale = next((p.value for p in wb.custom_doc_props.props if p.name == STALE_PROPERTY), None)
    if stale not in (None, ""):
        refuse(f"this book's last apply was done but could not be patched fully ({stale}) -- "
               f"do not apply it again; {REBUILD}")
    doc = decode(wb[exchange_stamp.SHEET], st.baseline)
    try:
        data = model.parse(doc)
    except model.PayloadError as exc:
        refuse(f"the embedded baseline is not valid ({exc}) -- {REBUILD}", sheet=exchange_stamp.SHEET)
    for key, sheet in decl.sheets.items():
        if sheet.tab not in wb.sheetnames:
            refuse(f"the {key.replace('_', ' ')} tab ({sheet.tab!r}) is missing or was "
                   f"renamed -- rename it back, or {REBUILD}")
    return Book(path=path, wb=wb, stamp=st, decl=decl, doc=doc, model=data, kinds=kinds)
