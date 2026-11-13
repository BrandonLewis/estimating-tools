"""Write computed values into a saved book's formula cells (#370).

openpyxl saves formulas with no cached value, so Protected View, previews
and ``data_only`` readers show 0. ``cache_values`` evaluates the book and
writes each result as the cell's cached value; a cell it cannot evaluate,
and every cell that reads it, has its value removed. Excel still
recalculates on open (``fullCalcOnLoad`` is left as it is).
"""
from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl.utils import get_column_letter

from estimating_tools.exchange import writer
from estimating_tools.xlcalc.book import Book
from estimating_tools.xlcalc.evaluate import Failed, evaluate
from estimating_tools.xlcalc.values import Err


@dataclass
class Report:
    """How many formulas the book has, how many were cached, and why the
    rest were not (``{reason: count}``). ``hidden``: formulas on hidden
    sheets left uncached -- a template book's prototype rows, which read
    their own blank tags -- counted apart and never reported: a visible
    cell that reads one is itself uncached and reported."""
    formulas: int = 0
    cached: int = 0
    reasons: dict = field(default_factory=dict)
    hidden: int = 0

    def summary(self) -> str | None:
        """One line when a formula a visible sheet holds was left uncached;
        None when all were."""
        shown = self.formulas - self.hidden
        if self.cached == shown:
            return None
        why = ", ".join(f"{reason}: {n:,}" for reason, n in
                        sorted(self.reasons.items(), key=lambda kv: (-kv[1], kv[0])))
        return (f"cached {self.cached:,} of {shown:,} formulas; "
                f"{shown - self.cached:,} not evaluated ({why})")


def _cell_value(v):
    if isinstance(v, Err):
        return writer.CachedError(v.code)
    if isinstance(v, float) and v.is_integer() and abs(v) < 2 ** 53:
        return int(v)
    return v


def cache_values(path) -> Report:
    """Evaluate the book at ``path`` and write the cached values in place."""
    book = Book.load(path)
    results = evaluate(book)
    values, reasons, hidden = {}, Counter(), 0
    for (sheet, row, col), v in results.items():
        if isinstance(v, Failed):
            if sheet in book.hidden:
                hidden += 1
            else:
                reasons[v.reason] += 1
            continue
        values.setdefault(sheet, {})[f"{get_column_letter(col)}{row}"] = _cell_value(v)
    cached = writer.write_cached(path, values)
    return Report(formulas=len(results), cached=cached, reasons=dict(reasons), hidden=hidden)


def cache_or_warn(path, *, stream=None, label: str | None = None) -> Report | None:
    """``cache_values``, never raising: on a failure every formula's cached
    value is removed (a patched book may hold values Excel computed before
    the patch, now stale) and a warning is printed. Prints the report's
    summary when a formula was left uncached; nothing when every one was
    cached. ``label`` names the book in those lines (default: the file
    name), for a caller caching a temporary copy."""
    stream = stream if stream is not None else sys.stderr
    name = label or Path(path).name
    try:
        report = cache_values(path)
    except Exception as exc:  # noqa: BLE001 -- the book is already written; never fail it
        print(f"warning: {name}: formula values not cached ({type(exc).__name__}: {exc}); "
              "Excel computes them when the book is opened for editing", file=stream)
        try:
            writer.write_cached(path, {})
        except Exception as clear:  # noqa: BLE001
            print(f"warning: {name}: old formula values could not be removed either "
                  f"({type(clear).__name__}: {clear}); they may be stale", file=stream)
        return None
    line = report.summary()
    if line:
        print(f"{name}: {line}", file=stream)
    return report
