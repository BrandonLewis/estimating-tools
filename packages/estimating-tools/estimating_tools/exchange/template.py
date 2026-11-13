"""A template pack (engine spec, Layer 2): a directory holding ``pack.yaml``
(the declaration, ``kind: template``) and ``template.xlsx`` (the book its
author built in Excel, prototypes on a hidden sheet), behind the ``Pack``
protocol with no code of its own. Build is the engine's fill
(``exchange.fill``); read, patch and refresh are the engine's reader,
patch and refresh; detection reads the stamp.

A pack ships as a Python package that registers a factory under the
``estimating_tools.packs`` entry point group::

    def pack():
        return TemplatePack.from_package("my_pack_package")

``TemplatePack(directory)`` takes a directory on disk (a test, or a pack
being authored)."""
from __future__ import annotations

import functools
import json
from datetime import date, datetime, timezone
from importlib import resources
from pathlib import Path

from estimating_tools.exchange import contract
from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange.declaration import DeclarationError, load
from estimating_tools.exchange.types import (ApplyResult, BookFacts, BuildRefused, BuildReport,
                                             InsertKind, PatchReport, ReadResult, RefreshExtras,
                                             Verdict)

__all__ = ["DECLARATION", "TEMPLATE", "TemplatePack", "as_of_export"]

DECLARATION = "pack.yaml"
TEMPLATE = "template.xlsx"


def as_of_export(decl) -> tuple:
    """The read-model collections a template book shows as of export with no
    sheet laying them out: the crews unless a blocks sheet owns CREW, the
    library rates unless a rates sheet lays them out. A BidSheet.ai change
    to one leaves the book's figures stale: patch and refresh report it."""
    owners = {b.kind for s in decl.sheets.values() for b in s.owner_blocks()}
    roles = {s.role for s in decl.sheets.values()}
    out = []
    if "CREW" not in owners:
        out.append("crews")
    if "rates" not in roles:
        out.append("rates")
    return tuple(out)


def _prototype_kinds(book, sheet) -> dict:
    """``{row kind: source kind}`` of a display sheet's prototype rows, read
    from the book's own prototypes (the stamped declaration names them)."""
    from estimating_tools.exchange.fill.lint import _prototype_names

    names = _prototype_names(book.wb)
    out = {}
    for key, name in sheet.prototypes.items():
        got = names.get(name)
        if got is None or got[0] not in book.wb.sheetnames:
            continue
        title, first, last = got
        ws = book.wb[title]
        for r in range(first, last + 1):
            kind = ws[f"{sheet.tag('kind')}{r}"].value
            if kind:
                out[str(kind).strip()] = key.partition(".")[0]
    return out


def _queues(pairs) -> dict:
    """``{key: [object, ...]}`` in order: a display row is matched to the
    next object of its key, so rows that share an id (an activity's
    warnings) are each matched to their own."""
    out = {}
    for key, obj in pairs:
        out.setdefault(key, []).append(obj)
    return out


def _same_cell(have, want) -> bool:
    from openpyxl.utils.datetime import to_excel

    from estimating_tools.exchange.reader.fields import number_equal, parse_number

    if isinstance(have, (date, datetime)):
        have = to_excel(have)                  # a date label: the fill wrote its serial
    a, ea = parse_number(have)
    b, eb = parse_number(want)
    if ea is None and eb is None and a is not None and b is not None:
        return number_equal(a, b)
    return str("" if have is None else have).strip() == str("" if want is None else want).strip()


def _display_refresh(book, fresh, key, sheet, cells, notes, stale):
    """A display sheet brought up to date in place: each row matched by its
    kind and id tags to the fresh read model's object (a source's child by
    its own kind and id; rows sharing an id in order; a source with no ids,
    the calendar, row by row in order), its changed labels rewritten. A row
    whose object BidSheet.ai no longer has is blanked (its label cells; the
    tags stay) with a note -- as a row BidSheet.ai added is a note: a
    display sheet's rows are never added or removed here, a rebuild does
    that. A ``priced`` source whose set changed is stale instead (``stale``
    gets ``<sheet key>.<SOURCE>``) and its rows are left as built."""
    from collections import Counter

    from estimating_tools.exchange import display, labels
    from estimating_tools.exchange.patch.prototypes import spelled
    from estimating_tools.exchange.reader.scan import is_blank

    tab = book.tab(key)
    by_source = {}
    for region in sheet.regions:
        for source in region.rows:
            src = display.SOURCES[source]
            old_objs = list(src.rows(book.model, sheet))
            new_objs = list(src.rows(fresh, sheet))
            keyed = any(src.ident(o) is not None for o in old_objs + new_objs)
            if keyed:
                old = Counter(str(src.ident(o)) for o in old_objs)
                new = Counter(str(src.ident(o)) for o in new_objs)
                changed, gained = old != new, sum((new - old).values())
            else:                              # an id-less source (the calendar): its objects
                changed = old_objs != new_objs
                gained = max(0, len(new_objs) - len(old_objs))
            if changed and src.priced:
                stale.append(f"{key}.{source}")
            elif gained:
                notes.append(f"{tab}: {gained} {source.lower()} row(s) BidSheet.ai has now are "
                             "not in the book; a rebuild adds them")
            for kind, (_cls, fn) in src.children.items():
                was = Counter(str(display.child_ident(c)) for o in old_objs
                              for c in fn(book.model, o))
                now = Counter(str(display.child_ident(c)) for o in new_objs for c in fn(fresh, o))
                more = sum((now - was).values())
                if more:
                    notes.append(f"{tab}: {more} {kind.lower()} row(s) BidSheet.ai has now are "
                                 f"not listed under their {source.lower()} -- rebuild to list "
                                 "them")
            found = _queues((str(src.ident(o)), o) for o in new_objs)
            children = _queues(((kind, str(display.child_ident(c))), c) for o in new_objs
                               for kind, (_cls, fn) in src.children.items()
                               for c in fn(fresh, o))
            by_source[source] = (src, keyed, found, children, set(src.children))
    if tab not in book.wb.sheetnames:
        return
    id_tag = sheet.tag("id")
    kinds = _prototype_kinds(book, sheet)
    ws = book.wb[tab]
    out = cells.setdefault(tab, {})
    taken, blanked = {}, Counter()
    for r in range(sheet.first_row, ws.max_row + 1):
        kind = str(ws[f"{sheet.tag('kind')}{r}"].value or "").strip()
        ident = ws[f"{id_tag}{r}"].value if id_tag else None
        source = kinds.get(kind)
        if source not in by_source:
            continue
        src, keyed, found, children, child_kinds = by_source[source]
        if ident in (None, ""):
            if keyed or kind in child_kinds:
                continue                       # a row the source does not lay out by id
            ref = "None"                       # an id-less source's rows: in order
        else:
            ref = str(ident)
        queue = children.get((kind, ref)) if kind in child_kinds else found.get(ref)
        # Rows of one kind that share an id take that id's objects in order.
        n = taken.get((kind, ref), 0)
        taken[(kind, ref)] = n + 1
        row_labels = sheet.labels.get(kind, {})
        if not queue or n >= len(queue):
            if src.priced:
                continue                       # stale: the rebuild the structural line asks for
            gone = [letter for letter in row_labels if not is_blank(ws[f"{letter}{r}"].value)]
            for letter in gone:
                out[f"{letter}{r}"] = None
            if gone:
                blanked[kind.lower() if kind in child_kinds else source.lower()] += 1
            continue
        obj = queue[n]
        for letter, label in row_labels.items():
            want = spelled(labels.resolve(label, obj, fresh))
            if not _same_cell(ws[f"{letter}{r}"].value, want):
                out[f"{letter}{r}"] = want
    for what, count in blanked.items():
        notes.append(f"{tab}: {count} {what} row(s) BidSheet.ai no longer has are blanked; a "
                     "rebuild removes them")


def _header_refresh(book, fresh, key, sheet, cells, exported_at) -> bool:
    """The sheet's header cells whose value changed, rewritten; True when one
    other than the export time did (the export time changes every refresh
    and feeds no figure)."""
    from estimating_tools.exchange import labels
    from estimating_tools.exchange.patch.prototypes import spelled

    tab = book.tab(key)
    ws = book.wb[tab] if tab in book.wb.sheetnames else None
    scope = {"estimate": fresh.estimate, "exported_at": exported_at, "host": book.stamp.host}
    other = False
    for cell, label in sheet.header.items():
        want = spelled(labels.resolve(label, scope, fresh))
        if ws is not None and _same_cell(ws[cell].value, want):
            continue
        cells.setdefault(tab, {})[cell] = want
        other = other or label.paths != ("exported_at",)
    return other


def _stale_message(decl, what: str) -> str:
    """The structural line for a stale entry found now: an as-of-export
    collection, or a priced display source (``<sheet key>.<SOURCE>``)."""
    from estimating_tools.exchange.refresh.merge import REBUILD_HINT

    key, dot, source = what.partition(".")
    if dot and key in decl.sheets:
        return (f"BidSheet.ai added or removed {source.lower()} rows, which the "
                f"{decl.sheets[key].tab} sheet lays out and the book prices from -- "
                f"{REBUILD_HINT}")
    return (f"BidSheet.ai changed the estimate's {what}, which this book shows as of export "
            f"-- {REBUILD_HINT}")


def _carried_message(decl, what: str) -> str:
    """The note for a stale entry the stamp carries (a patch found it and
    took the new baseline) that is not found again now."""
    from estimating_tools.exchange.refresh.merge import REBUILD_HINT

    earlier = "were found changed in BidSheet.ai earlier (a patch took its new baseline)"
    key, dot, source = what.partition(".")
    if dot and key in decl.sheets:
        return (f"{decl.sheets[key].tab}: the {source.lower()} rows {earlier}; the sheet "
                f"shows them as of the last build -- {REBUILD_HINT} to show them")
    return (f"the estimate's {what} {earlier}; this book shows them as of the last build -- "
            f"{REBUILD_HINT} to show them")


class TemplatePack:
    """A template pack read from ``root`` (a directory, or a package's
    resources)."""

    def __init__(self, root):
        self.root = root
        doc = self._doc()
        if not isinstance(doc, dict):
            raise DeclarationError(f"{DECLARATION} is not a mapping")
        pack = doc.get("pack") or {}
        if not isinstance(pack, dict):
            raise DeclarationError(f"{DECLARATION}: pack is {pack!r}; it names the pack "
                                   "(pack: {name: ..., version: ...})")
        self.name = str(pack.get("name") or "")
        self.version = str(pack.get("version") or "")
        self.contract = str(pack.get("contract") or "")

    @classmethod
    def from_package(cls, package: str) -> "TemplatePack":
        return cls(resources.files(package))

    def _doc(self) -> dict:
        import yaml

        return yaml.safe_load((self.root / DECLARATION).read_text(encoding="utf-8"))

    @functools.cached_property
    def _declaration(self):
        decl = load(self._doc())
        if decl.kind != "template":
            raise DeclarationError(f"{DECLARATION}: kind is {decl.kind!r}; a template pack's is "
                                   "'template'")
        return decl

    def declaration(self):
        """The pack's declaration, loaded (``DeclarationError`` for one that
        does not load or is not a template pack's)."""
        return self._declaration

    def template(self):
        """A context manager giving the template's path on disk."""
        return resources.as_file(self.root / TEMPLATE)

    # -- the protocol ------------------------------------------------------

    def detect(self, facts: BookFacts) -> Verdict:
        fmt = str(facts.properties.get(exchange_stamp.PROPERTY, "")).split(" ")[0]
        if fmt != self.name:
            return "none"
        raw = facts.names.get(exchange_stamp.NAME)
        try:
            st = exchange_stamp.parse(json.loads(raw))
        except (TypeError, ValueError):
            return "bad"
        if st.pack.get("name") != self.name:
            return "bad"
        if st.schema > exchange_stamp.SCHEMA_VERSION or st.contract != exchange_stamp.CONTRACT:
            return "newer"
        return "ok"

    def build(self, payload: dict, out: Path, *, options: dict) -> BuildReport:
        """Fill the template from ``payload`` (``exchange.fill``). Options:
        ``exported_at`` (ISO; default now, UTC), ``host`` (a bare host or an
        https URL; default ``www.bidsheet.ai``), ``allow_dropped`` (fill
        even though the template holds what the fill does not copy onto new
        rows; the report lists it). ``BuildRefused`` writes nothing."""
        from estimating_tools.exchange.fill import fill

        exported_at = options.get("exported_at") or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        try:
            host = exchange_stamp.bare_host(options.get("host") or "")
        except ValueError as exc:
            raise BuildRefused("host", str(exc)) from exc
        try:
            self.declaration()
        except DeclarationError as exc:
            raise BuildRefused("template", f"{self.name}: {exc}") from exc
        with self.template() as template:
            report = fill(self, template, payload, out, exported_at=exported_at, host=host,
                          allow_dropped=bool(options.get("allow_dropped")))
        return BuildReport(path=report.path, exported_at=report.exported_at,
                           dropped=list(report.dropped))

    def read(self, book: Path) -> ReadResult:
        from estimating_tools.exchange.reader import ReadRefused, read_book

        try:
            return ReadResult(change_set=read_book(Path(book), pack=self))
        except ReadRefused as exc:
            return ReadResult(problems=[str(p) for p in exc.problems])

    def patch(self, book: Path, change_set, result: ApplyResult, payload: dict) -> PatchReport:
        from estimating_tools.exchange.patch import patch

        return patch(Path(book), change_set, result, payload, pack=self)

    def refresh(self, book: Path, payload: dict, *, dry_run: bool = False):
        from estimating_tools.exchange.refresh import refresh

        return refresh(Path(book), payload, pack=self, dry_run=dry_run)

    def refresh_extras(self, book, payload: dict, fresh, *, exported_at: str) -> RefreshExtras:
        """What the book shows that BidSheet.ai changed since its baseline:
        display rows' labels and the header cells that changed rewritten in
        place, a display row BidSheet.ai removed blanked; a display source's
        added or removed rows a note, or -- a ``priced`` source --
        structural; crews and rates the book shows as of export
        (``as_of_export``) structural when they changed. Each structural
        change is ``stale`` too. What a patch already found stale (the
        stamp's ``stale``) and is not found again is a note: the baseline
        holds BidSheet.ai's version of it, so it never blocks a refresh.
        ``recalc`` when a display cell or a header cell other than the
        export time changed."""
        decl = book.decl
        cells, notes, found = {}, [], []
        for collection in as_of_export(decl):
            if getattr(book.model, collection) != getattr(fresh, collection):
                found.append(collection)
        header = False
        for key, sheet in decl.sheets.items():
            if sheet.role == "display":
                _display_refresh(book, fresh, key, sheet, cells, notes, found)
            header = _header_refresh(book, fresh, key, sheet, cells, exported_at) or header
        found = list(dict.fromkeys(found))
        notes += [_carried_message(decl, s) for s in book.stamp.stale if s not in found]
        display_tabs = {book.tab(k) for k, s in decl.sheets.items() if s.role == "display"}
        recalc = header or any(c for tab, c in cells.items() if tab in display_tabs)
        cells = {tab: c for tab, c in cells.items() if c}
        return RefreshExtras(cells=cells, structural=[_stale_message(decl, s) for s in found],
                             notes=notes, recalc=recalc, stale=tuple(found))

    def covered(self, book: Path) -> tuple:
        return exchange_stamp.covered(Path(book))

    def templates(self) -> list[InsertKind]:
        """The prototypes an estimator's tool may insert: the growable kinds'
        and their variants."""
        decl = self.declaration()
        growable = {k.lower() for k in contract.GROWABLE}
        # A variant of a growable owner (a stepped activity); a library crew
        # is never inserted.
        growable |= {v for owner, variants in contract.VARIANTS.items()
                     if owner in contract.GROWABLE for v in variants.values()}
        return [InsertKind(kind=k, name=n) for k, n in decl.prototypes.items() if k in growable]
