"""What patch and refresh share: noticing a save made behind their back,
writing the whole change to a copy beside the book and reading the copy back
before the book takes it, the stamp cells a new baseline needs, and the
pack's optional extra cells (``Pack.refresh_extras``)."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from estimating_tools.exchange import baseline, writer
from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange.patch.cells import REBUILD
from estimating_tools.exchange.types import RefreshExtras
from estimating_tools.xlcalc import cache_or_warn

__all__ = ["CHANGED", "STAMP_SHEET", "display_tabs", "extras", "fingerprint", "now", "shown",
           "stamp_cells", "still", "unclean", "verified_write"]

#: The sheet that holds the stamp and the baseline chunks.
STAMP_SHEET = exchange_stamp.SHEET
#: A patch's refusal when the book changed under it.
CHANGED = ("the book has changed since the change set was read from it -- the apply is "
           f"done; {REBUILD}")


def now() -> str:
    """The export time a patch or refresh stamps: UTC, to the second."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fingerprint(path: Path) -> str:
    """The book's content, to notice a save made behind the writer's back."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def still(book: Path, seen: str, message: str = CHANGED) -> None:
    """Refuse (``ValueError(message)``) when ``book`` no longer has the content
    ``seen``: a save during the verification read would otherwise be
    overwritten by the copy, or written at stale row numbers."""
    if fingerprint(book) != seen:
        raise ValueError(message)


def shown(why: list) -> str:
    """The first three reasons, and how many more."""
    return "; ".join(why[:3]) + (f"; and {len(why) - 3} more" if len(why) > 3 else "")


def unclean(path: Path, pack) -> list:
    """Why ``path``'s next read would send something the user did not type:
    the read's problems, else its change-set summary lines; empty when the
    read is clean (no problems, no ops)."""
    from estimating_tools.exchange.reader import ReadRefused, run

    try:
        opened, _scanned, _changes, again, problems = run(path, pack=pack)
    except ReadRefused as exc:
        return [str(p) for p in exc.problems] or ["the book could not be read"]
    opened.wb.close()
    if problems.items:
        return [str(p) for p in problems.items]
    if again.ops:
        return list(again.summary) or [f"{len(again.ops)} op(s)"]
    return []


def stamp_cells(opened, payload: dict, exported_at: str) -> dict:
    """``{ref: value}`` on the stamp sheet that make ``payload`` the book's
    baseline: the stamp (the opened book's, upgraded in memory when it was
    older, with the new baseline, estimate ``v`` and export time) and the
    baseline chunks, clearing the old chunks past the new last one."""
    chunks, meta = baseline.encode(payload)
    stamp = exchange_stamp.with_baseline(
        dict(opened.stamp.raw), meta,
        estimate_v=(payload.get("estimate") or {}).get("v", opened.stamp.estimate_v),
        exported_at=exported_at)
    out = {exchange_stamp.CELL: exchange_stamp.dumps(stamp)}
    for n, chunk in enumerate(chunks, start=1):
        out[f"B{n}"] = chunk
    old = int(opened.stamp.baseline.get("chunks") or 0)
    for n in range(len(chunks) + 1, old + 1):
        out[f"B{n}"] = None
    return out


def extras(pack, opened, payload: dict, fresh, exported_at: str) -> RefreshExtras:
    """The pack's own cells for a new baseline (``Pack.refresh_extras``,
    optional): none when the pack has no such method."""
    hook = getattr(pack, "refresh_extras", None)
    if hook is None:
        return RefreshExtras()
    return hook(opened, payload, fresh, exported_at=exported_at)


def display_tabs(opened) -> set:
    """The book's sheets the declaration does not bind (summaries, checks,
    helpers): a row deleted from a bound sheet may leave their formulas
    reading ``#REF!``, as Excel's own delete does, without blocking a read."""
    bound = {s.tab for s in opened.decl.sheets.values()} | {STAMP_SHEET}
    return set(opened.wb.sheetnames) - bound


def verified_write(book: Path, *, cells: dict, properties: dict, recalc: bool, seen: str,
                   accept, rows=(), lost_ok=(), keep: bool = True,
                   changed: str = CHANGED) -> tuple:
    """Write ``rows`` and ``cells`` to a copy of ``book`` beside it, cache
    its formulas' values (``xlcalc.cache_or_warn``: no total computed before
    the write survives it, #370; a failed pass removes every cached value),
    and ask ``accept(copy)`` why the copy is not fit (a list; empty when it
    is).
    Fit and ``keep``: the copy replaces the book, provided the book still
    has the content ``seen`` (else ``ValueError(changed)``). Returns
    ``(cells written, why, lost)``: ``why`` empty when accepted, ``lost``
    the writer's ``#REF!`` cells on ``lost_ok`` sheets. The copy is removed
    in every case, on any exception too."""
    book = Path(book)
    fd, name = tempfile.mkstemp(dir=book.parent, prefix=book.stem + ".",
                                suffix=".patching.xlsx")
    os.close(fd)
    tmp = Path(name)
    try:
        shutil.copy2(book, tmp)       # the book's mode, not mkstemp's 0600
        done = writer.edit(tmp, rows=rows, cells=cells, properties=properties,
                           full_calc_on_load=recalc, lost_ok=lost_ok)
        cache_or_warn(tmp, label=book.name)       # no value left stale by the write (#370)
        why = accept(tmp)
        if why:
            return 0, list(why), list(done.lost)
        if keep:
            still(book, seen, changed)
            os.replace(tmp, book)
        return done.cells_written, [], list(done.lost)
    finally:
        tmp.unlink(missing_ok=True)
