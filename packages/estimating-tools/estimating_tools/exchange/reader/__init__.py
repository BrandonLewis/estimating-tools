"""The generic reader (engine spec, Read): an edited book becomes a change
set from its stamp, its declaration and its baseline. The declaration is the
only source of the book's tabs, first and header rows and row kinds; the
stamp's ``extra`` is not read, and no pack is imported.

``read_book(path, pack=None) -> ChangeSet`` or ``ReadRefused`` (every
problem listed, nothing sent). The pipeline, one module each:

- ``book``: open the book, load its declaration, decode the embedded baseline;
- ``scan``: walk the sheets into rows, blocks and markers;
- ``rates``: the Rates sheet must still match the baseline;
- ``fields``: inputs read into BidSheet.ai's spelling; formula cells kept;
- ``classify``: existing, new, copied, pasted, typed, moved and deleted rows;
- ``ops``: the ordered ops, with ``new:`` tokens and per-row ``v``;
- ``report``: the summary, and the ``rows`` map from op to book row;
- ``errors``: ``Problem`` (sheet, row, column, message), the ``Problems``
  collector every stage adds to, and ``ReadRefused``.

A pack's ``read`` calls ``read_book``; the pack's own job is detection,
build, patch and its declaration. ``pack`` is the detected pack: the
loader asks it to upgrade any older stamp it wrote (``upgrade_stamp``,
which returns a current one unchanged).

See docs/superpowers/specs/2026-10-24-heavycivil-workbook-readback-design.md.
"""
from __future__ import annotations

from estimating_tools.exchange.reader.errors import Problems, ReadRefused
from estimating_tools.exchange.reader.report import ChangeSet

__all__ = ["ChangeSet", "Problems", "ReadRefused", "read_book", "run"]


def run(path, pack=None):
    """The whole read-back pipeline, without the refusal: ``(book, scanned,
    changes, change_set, problems)``. ``problems`` holds every problem any
    stage found (an empty one means ``change_set`` is what ``read_book``
    returns). Only a book that cannot be opened as a stamped book raises
    (``ReadRefused``, from ``book.load``). A pack's patch uses it to find
    the rows a change set came from."""
    from estimating_tools.exchange.reader import book as book_mod, classify, fields, ops, rates, scan

    book = book_mod.load(path, pack=pack)
    problems = Problems()
    scanned = scan.scan(book, problems)
    rates.check(book, problems)
    fields.check_formulas(book, scanned, problems)
    changes = classify.classify(book, scanned, problems)
    change_set = ops.build(book, changes, problems)
    # Every unreadable input cell any stage read (``fields.diff`` skips a
    # bad field rather than report it): the read is refused, never silently
    # short of an edit.
    for line in scanned.all_lines():
        for read in (line.read or {}).values():
            for p in read.problems:
                problems.add(p.sheet, p.row, p.column, p.message)
    return book, scanned, changes, change_set, problems


def read_book(path, pack=None) -> ChangeSet:
    """An edited book's change set, or ``ReadRefused`` with every problem."""
    _book, _scanned, _changes, change_set, problems = run(path, pack=pack)
    problems.raise_if_any()
    return change_set
