"""Write an apply's outcome back into the book the change set came from
(contract part 5 "Patch, never rebuild"; rule 13: only the cells needed),
for any pack whose book the generic reader reads: every fact about where a
row sits is the declaration's (the book's stamp carries it) or the
contract's.

What is written, per op's rows (``change_set.rows``):

- every tag the row's kind carries in the declaration (the book's
  ``kinds``) -- ``id``, ``v`` and ``parent`` -- from the fresh payload
  (``v`` from the plan's ``versions`` first). A kind that declares no ``v``
  (an estimate input row, MEMBER, the markers) gets none: ``estimate.update``'s
  ``v`` goes on the ESTIMATE row (``rows``);
- a created activity's whole block: its markers and its step and resource
  rows take the new id as their parent (``rows``);
- a row typed with no kind (a step, resource or crew member): its kind and
  its prototype row's formulas and constants, into blank cells only; and a
  created row's blank inputs that the server filled with a default
  (``prototypes``);
- crews whose roster was replaced or that the apply copied out of the
  library: new member ids, a copy's new crew id (``crews``).

The baseline (the stamp sheet's column B, and the stamp's ``baseline``,
``estimate_v`` and ``exported_at``) is replaced by the fresh payload, and
the ``exported_at`` property is updated -- but only once the result is
verified (``verify.verified_write``): the whole patch is written to a copy
beside the book and that copy is read back; the book takes it only when the
read is clean (no problems, no ops). When it is not -- someone changed the
estimate in BidSheet.ai meanwhile, and the next read would send the book's
old values back as edits -- only the identity cells are written, the old
baseline stays, the book is stamped stale
(``exchange.reader.book.STALE_PROPERTY``, which every read refuses until the
book is rebuilt), and the report says so. Other users' changes since the
read are found the way a refresh finds them (``refresh.merge.plan`` with the
apply's own rows set aside: they are the apply's, neither collisions nor
additions) and taken in the same verified write; a change the merge cannot
take (a collision, or a structural change such as an activity's crew) is
never written, since a copy could read back clean while its formulas price
the old structure: the book goes stale. When any cell outside the stamp sheet is written, the
book also asks Excel to recalculate on open. Nothing else is touched.

The reader never sends the ``v`` stored in a row's v cell: every op's ``v``
comes from the decoded baseline. So replacing the baseline is what keeps
the next push conflict-free, and verifying the patched book is what keeps
it from pushing anything the user did not type; the v cells are
informational, written only on the rows the ops came from.
"""
from __future__ import annotations

from pathlib import Path

from estimating_tools.exchange import model, writer
from estimating_tools.exchange.patch import verify
from estimating_tools.exchange.patch.cells import REBUILD, Cells
from estimating_tools.exchange.patch.crews import patch_crews
from estimating_tools.exchange.patch.rows import run_ops
from estimating_tools.exchange.reader.book import STALE_PROPERTY
from estimating_tools.exchange.types import ApplyResult, PatchReport
from estimating_tools.xlcalc import cache_or_warn

__all__ = ["patch"]


def _reread(path: Path, change_set, pack):
    """The reader's view of the book (``exchange.reader.run``): ``(book, scanned,
    changes)``. Refuses (``ValueError``) unless the read is clean and yields
    exactly ``change_set``'s ops and rows: otherwise the book changed since
    the read and its rows can't be trusted to be the ones the ops name."""
    from estimating_tools.exchange.reader import ReadRefused, run

    try:
        book, scanned, changes, again, problems = run(path, pack=pack)
    except ReadRefused as exc:
        raise ValueError(verify.CHANGED) from exc
    if (problems.items or again.ops != list(change_set.ops)
            or again.rows != list(change_set.rows)):
        book.wb.close()
        raise ValueError(verify.CHANGED)
    return book, scanned, changes


def _unclean_problem(why: list) -> str:
    return (f"the patched book would not read back clean ({verify.shown(why)}) -- the apply "
            f"is done; the book keeps its old baseline and is marked stale, so every read "
            f"refuses it; {REBUILD}")


def _absorbed(merge, rowmap) -> list:
    """The notes a patch that took other users' changes adds (rows as the
    book stands after the patch)."""
    return ([f"took {len(merge.written)} change(s) made in BidSheet.ai since this book was "
             "read:"] + [f"  {line.render(rowmap)}" for line in merge.written])


def patch(book: Path, change_set, result: ApplyResult, payload: dict, *,
          pack) -> PatchReport:
    """Patch ``book`` in place after a committed apply of ``change_set``.

    ``result`` is the server's plan (``created`` maps the change set's
    ``new:`` tokens -- and ``crew:<id>`` of a library crew the apply copied
    -- to the rows made); ``payload`` is the fresh read-model document,
    which becomes the book's baseline when the patched book reads back
    clean (see the module docstring); ``pack`` is the book's pack (the reads
    go through it, so an older stamp it wrote is upgraded and written back,
    and its ``refresh_extras`` adds its own cells).

    Other users' changes since the read are found the way a refresh finds
    them (``refresh.merge.plan`` with the apply's own rows set aside) and
    taken in the same verified write. When the merge finds a change the book
    cannot take (a collision, or a structural change such as an activity's
    crew), or the copy does not read back clean, the book keeps its old
    baseline and is stamped stale.

    Raises ``ValueError`` for a dry-run result, for a book that changed
    since the change set was read from it (also by a save made while the
    copy was being verified), and for any writer refusal -- nothing is
    written then. What could not be written otherwise is in the
    report's ``problems``, each ending in what to do.
    """
    from estimating_tools.exchange import rowops
    from estimating_tools.exchange.refresh import layout as layout_mod
    from estimating_tools.exchange.refresh import merge as merge_mod

    if result.dry_run:
        raise ValueError("a dry run changes nothing on the server; nothing to patch")
    book = Path(book)
    fresh = model.parse(payload)
    seen = verify.fingerprint(book)
    opened, scanned, changes = _reread(book, change_set, pack)
    try:
        cells = Cells(opened, result, payload)
        pending = run_ops(cells, scanned, change_set, result, fresh)
        patch_crews(cells, scanned, changes, result, fresh, pending)
        exported_at = verify.now()
        stamp = verify.stamp_cells(opened, payload, exported_at)
        extras = verify.extras(pack, opened, payload, fresh, exported_at)
        merge = merge_mod.plan(opened, scanned, changes, change_set, fresh, applied=result)
        # Other users' changes since the read: taken in the same write.
        absorb = (layout_mod.layout(opened, merge)
                  if merge.clean and not merge.empty else None)
        lost_ok = verify.display_tabs(opened)
    finally:
        opened.wb.close()
    identity = {tab: dict(refs) for tab, refs in cells.cells.items()}
    recalc = any(identity.values()) or extras.recalc
    out = {tab: dict(refs) for tab, refs in identity.items()}
    for tab, refs in extras.cells.items():
        out.setdefault(tab, {}).update(refs)
    notes = list(extras.notes) + list(extras.structural)
    if not merge.clean:
        # Other users changed what this book cannot take in place (an
        # activity's crew, an item added): a copy can read back clean while
        # its formulas still price the old structure, so it is not tried.
        # The apply is done: the merge's own advice ("apply this book's
        # edits, then rebuild") would ask for it again; the stale problem
        # says to rebuild.
        hint = f" -- {merge_mod.REBUILD_HINT}"
        why = [str(c) for c in merge.collisions] + [
            s[:-len(hint)] if s.endswith(hint) else s for s in merge.structural]
    elif absorb is None:
        written, why, _lost = verify.verified_write(
            book, cells={**out, verify.STAMP_SHEET: stamp},
            properties={"exported_at": exported_at}, recalc=recalc, seen=seen,
            accept=lambda tmp: verify.unclean(tmp, pack))
        if not why:
            return PatchReport(cells_written=written, rows_tagged=len(cells.tagged),
                               baseline_replaced=True, problems=list(cells.problems),
                               notes=notes, recalc=recalc)
    else:
        rows, more = absorb
        moved = layout_mod.remap(out, rowops.RowMap(rows))
        for tab, refs in more.items():
            moved.setdefault(tab, {}).update(refs)
        moved.setdefault(verify.STAMP_SHEET, {}).update(stamp)
        written, again, lost = verify.verified_write(
            book, rows=rows, cells=moved, properties={"exported_at": exported_at},
            recalc=True, seen=seen, accept=lambda tmp: verify.unclean(tmp, pack),
            lost_ok=lost_ok)
        if not again:
            notes += _absorbed(merge, rowops.RowMap(rows))
            notes += [f"{tab}!{ref} pointed at a row BidSheet.ai deleted and reads #REF! until "
                      "the book is rebuilt" for tab, ref, _text in lost]
            # Row ops and other users' cells: the book asked for a full
            # calculation, and cells outside the stamp sheet changed.
            return PatchReport(cells_written=written, rows_tagged=len(cells.tagged),
                               baseline_replaced=True, problems=list(cells.problems),
                               notes=notes, recalc=True)
        why = again
    # The ids and versions the apply made are still the book's; the baseline
    # it would adopt is not. The stamp makes every read refuse the book.
    stale = f"applied {result.request_id or exported_at}; patch not verified"
    verify.still(book, seen)
    written = writer.write(book, cells=identity, properties={STALE_PROPERTY: stale},
                           full_calc_on_load=recalc)
    cache_or_warn(book)
    return PatchReport(cells_written=written, rows_tagged=len(cells.tagged),
                       baseline_replaced=False,
                       problems=list(cells.problems) + [_unclean_problem(why)],
                       recalc=recalc)
