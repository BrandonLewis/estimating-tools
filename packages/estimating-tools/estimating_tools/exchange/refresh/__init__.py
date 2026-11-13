"""Bring BidSheet.ai's changes since a book's baseline into the book, in
place (engine spec, "Refresh"; contract part 5, "Patch, never rebuild").

``refresh(book, payload, *, pack, dry_run=False)``: ``payload`` is the fresh
read model (the CLI fetched it -- for a page, with the page's items). The
book is read through the reader (a refused read, or one with problems, is
refused here: fix the book first; a stale book is refused by the reader).
``merge.plan`` decides row by row; when it reports anything -- a row changed
on both sides, or a change the book cannot take in place -- nothing is
written and the baseline stays, so the book still reads back against the
baseline it was built on (rule 10: a surface that cannot tell an edit from
a server change must not guess). Otherwise ``layout`` turns the decision
into row ops and cells, the pack adds its own cells
(``Pack.refresh_extras``), and the whole of it -- with the new baseline,
stamp and export time -- is written to a copy beside the book and read back.
The book takes the copy only when that read has no problems and sends the
same ops the book sent before (by op, ref and fields), less what both sides
made equal (``merge.expected``); a dry run reads the copy and discards it.

What a patch found stale (the stamp's ``stale``) is a note here, not a
refusal: the baseline already holds BidSheet.ai's version of it, so taking
the rest cannot make the book worse; only a change the pack finds now
refuses (``Pack.refresh_extras``' structural lines).

Known limits: display rows (a template pack's display sheets) are brought
up to date in place -- labels rewritten, a row whose object BidSheet.ai
removed blanked -- but rows BidSheet.ai added are not listed there: a note
says so, and a rebuild lists them. A code-built HeavyBook book's summary
sheets are refreshed only as far as its Checks figures. Hidden figures a
pack computes from the export rather than copies from it stay as of the
build too: for HeavyBook, an activity's cost and man-hours at export
(``AB``/``AC``) and, for an activity whose crew is not on the Crews sheet,
its per-shift labour and man-hours (``AH``/``AI``). Those do price: when
BidSheet.ai changes such an activity's labour, rebuild the book."""
from __future__ import annotations

import json
from pathlib import Path

from estimating_tools.exchange import model, rowops
from estimating_tools.exchange.patch import verify
from estimating_tools.exchange.refresh import layout as layout_mod
from estimating_tools.exchange.refresh import merge as merge_mod
from estimating_tools.exchange.types import RefreshReport

__all__ = ["refresh"]

#: Refresh's refusal when the book changed under it.
CHANGED = ("the book changed while it was being refreshed -- nothing was written; run the "
           "refresh again")


def _refused(problems: list) -> str:
    return (f"the book does not read back cleanly ({verify.shown(problems)}) -- fix the book "
            "first, then refresh")


def _op_text(sig) -> str:
    name, ref, fields = sig
    return f"{name} {ref} {fields}"


def _accept(tmp, pack, expected) -> list:
    """Why the refreshed copy is not the book it should be: the read's
    problems, or ops other than ``expected`` (each one that differs, named);
    empty when it is."""
    from estimating_tools.exchange.reader import ReadRefused, run

    try:
        opened, _scanned, _changes, again, problems = run(tmp, pack=pack)
    except ReadRefused as exc:
        return [str(p) for p in exc.problems] or ["the book could not be read"]
    opened.wb.close()
    if problems.items:
        return [str(p) for p in problems.items]
    got = sorted(merge_mod.signature(op) for op in again.ops)
    if got != expected:
        extra, missing = list(got), []
        for sig in expected:
            if sig in extra:
                extra.remove(sig)
            else:
                missing.append(sig)
        return ([f"it would send {len(got)} op(s) where this book sends {len(expected)}"]
                + [f"it would also send {_op_text(x)}" for x in extra]
                + [f"it would no longer send {_op_text(x)}" for x in missing])
    return []


def _same(a: dict, b: dict) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def refresh(book, payload: dict, *, pack, dry_run: bool = False) -> RefreshReport:
    """Refresh ``book`` from ``payload``; see the module docstring. Raises
    ``ValueError`` (nothing written) for a book that does not read back
    cleanly, a copy that would not read back as the book does, a book that
    changed while being refreshed, a payload that does not parse, and any
    writer refusal; ``OSError`` when the book cannot be written."""
    from estimating_tools.exchange.reader import ReadRefused, run

    book = Path(book)
    fresh = model.parse(payload)
    seen = verify.fingerprint(book)
    try:
        opened, scanned, changes, change_set, problems = run(book, pack=pack)
    except ReadRefused as exc:
        raise ValueError(_refused([str(p) for p in exc.problems])) from None
    try:
        if problems.items:
            raise ValueError(_refused([str(p) for p in problems.items]))
        if _same(opened.doc, payload):
            # Current. What a patch stamped stale is still said (the pack's
            # notes) until a rebuild.
            notes = (list(verify.extras(pack, opened, payload, fresh, verify.now()).notes)
                     if opened.stamp.stale else [])
            return RefreshReport(dry_run=dry_run, baseline_replaced=False, current=True,
                                 notes=notes)
        merge = merge_mod.plan(opened, scanned, changes, change_set, fresh)
        exported_at = verify.now()
        extras = verify.extras(pack, opened, payload, fresh, exported_at)
        merge.structural += list(extras.structural)
        merge.notes += list(extras.notes)
        if not merge.clean:
            return RefreshReport(dry_run=dry_run, baseline_replaced=False,
                                 collisions=list(merge.collisions),
                                 structural=list(merge.structural), notes=list(merge.notes))
        rows, cells = layout_mod.layout(opened, merge)
        # The pack's cells are addressed as the book stands (a header cell
        # above a sheet's rows, a display row): moved where the row ops
        # move their rows.
        for tab, refs in layout_mod.remap(extras.cells, rowops.RowMap(rows)).items():
            cells.setdefault(tab, {}).update(refs)
        cells.setdefault(verify.STAMP_SHEET, {}).update(
            verify.stamp_cells(opened, payload, exported_at, stale=extras.stale))
        expected = merge_mod.expected(change_set, merge)
        lost_ok = verify.display_tabs(opened)
        recalc = bool(rows) or bool(merge.cells) or extras.recalc
    finally:
        opened.wb.close()
    written, why, lost = verify.verified_write(
        book, rows=rows, cells=cells, properties={"exported_at": exported_at}, recalc=recalc,
        seen=seen, accept=lambda tmp: _accept(tmp, pack, expected), lost_ok=lost_ok,
        keep=not dry_run, changed=CHANGED)
    if why:
        raise ValueError(f"the refreshed book would not read back as this book does "
                         f"({verify.shown(why)}) -- nothing written")
    rowmap = rowops.RowMap(rows)
    notes = list(merge.notes)
    notes += [f"{tab}!{ref} pointed at a row BidSheet.ai deleted and reads #REF! until the "
              "book is rebuilt" for tab, ref, _text in lost]
    added = sum(len(ins.rows) for ins in merge.inserts)
    if added:
        notes.append(f"{added} row(s) added from BidSheet.ai price live where the declaration "
                     "binds them; summary sheets list them after a rebuild")
    return RefreshReport(dry_run=dry_run, baseline_replaced=not dry_run, cells_written=written,
                         rows_added=added, rows_removed=len(merge.deletes),
                         written=[w.render(rowmap) for w in merge.written], notes=notes)
