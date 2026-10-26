"""HeavyCivil read-back (#1486 sub-project 3): an edited HeavyCivil book
becomes a change set for BidSheet.ai's ``apply_estimate_workbook_changes``.

``read_book(path) -> ChangeSet`` or ``ReadRefused`` (every problem listed,
nothing sent). The pipeline, one module each:

- ``baseline``: open the book, check the layout, decode the embedded baseline;
- ``scan``: walk the sheets into rows, blocks and markers;
- ``rates``: the Rates sheet must still match the baseline;
- ``fields``: inputs read into BidSheet.ai's spelling; formula cells kept;
- ``classify``: existing, copied, pasted, typed, moved and deleted rows;
- ``ops``: the ordered ops, with ``new:`` tokens and per-row ``v``;
- ``report``: the summary, and the ``rows`` map from op to book row;
- ``errors``: ``Problem`` (sheet, row, column, message), the ``Problems``
  collector every stage adds to, and ``ReadRefused``.

See docs/superpowers/specs/2026-10-24-heavycivil-workbook-readback-design.md.
"""
from __future__ import annotations

from estimating_tools.heavycivil.readback.errors import Problems, ReadRefused
from estimating_tools.heavycivil.readback.report import ChangeSet

__all__ = ["ChangeSet", "ReadRefused", "read_book"]


def read_book(path) -> ChangeSet:
    from estimating_tools.heavycivil.readback import baseline, classify, fields, ops, rates, scan

    book = baseline.load(path)
    problems = Problems()
    scanned = scan.scan(book, problems)
    rates.check(book, problems)
    fields.check_formulas(book, scanned, problems)
    changes = classify.classify(book, scanned, problems)
    change_set = ops.build(book, changes, problems)
    # Every unreadable input cell any stage read (``fields.diff`` skips a
    # bad field rather than report it): the read is refused, never silently
    # short of an edit.
    for line in scanned.cost_report + scanned.crew_lines + scanned.bid_form:
        for read in (line.read or {}).values():
            for p in read.problems:
                problems.add(p.sheet, p.row, p.column, p.message)
    problems.raise_if_any()
    return change_set
