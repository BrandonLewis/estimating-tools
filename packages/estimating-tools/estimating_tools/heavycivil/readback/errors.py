"""Read-back refusals: every problem is collected, then refused together."""
from __future__ import annotations

from dataclasses import dataclass

#: The cure for anything wrong with the book's own machinery.
REBUILD = "rebuild the book from BidSheet.ai"


@dataclass(frozen=True)
class Problem:
    """One reason the book cannot be read back. ``sheet`` is the tab title
    the estimator sees; ``row``/``column`` are None when the problem is not
    tied to one cell."""
    sheet: str | None
    row: int | None
    column: str | None
    message: str

    def __str__(self):
        where = []
        if self.sheet:
            where.append(self.sheet)
        if self.row is not None:
            where.append(f"row {self.row}")
        if self.column:
            where.append(f"column {self.column}")
        return (" ".join(where) + ": " if where else "") + self.message


class ReadRefused(ValueError):
    """The book cannot be turned into a change set; ``problems`` lists why.
    Nothing is sent and nothing is written."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(str(p) for p in self.problems))


def refuse(message, *, sheet=None, row=None, column=None):
    raise ReadRefused([Problem(sheet, row, column, message)])


class Problems:
    """Collects problems across the read so the estimator sees all of them."""

    def __init__(self):
        self.items: list[Problem] = []

    def add(self, sheet, row, column, message):
        problem = Problem(sheet, row, column, message)
        if problem not in self.items:
            self.items.append(problem)

    def raise_if_any(self):
        if self.items:
            raise ReadRefused(self.items)
