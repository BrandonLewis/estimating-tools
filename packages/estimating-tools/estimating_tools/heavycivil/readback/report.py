"""The change set as the estimator reads it: one line per change, each
naming the book row it came from, then what the book does not price live."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

ARROW = "\u2192"


def dec_str(value: Decimal) -> str:
    """A Decimal as plain text: scale-free, never exponent notation."""
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def fmt(value) -> str:
    if value is None or value == "":
        return "(blank)"
    if isinstance(value, bool):
        return "Y" if value else "N"
    if isinstance(value, Decimal):
        return dec_str(value)
    return str(value)


def where(tab, row) -> str:
    return f"{tab} row {row}" if row is not None else tab


def change(tab, row, label, field_name, before, after) -> str:
    return f"{where(tab, row)}: {label} {field_name} {fmt(before)} {ARROW} {fmt(after)}"


def event(tab, row, text) -> str:
    return f"{where(tab, row)}: {text}"


@dataclass
class ChangeSet:
    """``ops`` for ``apply_estimate_workbook_changes``; ``rows`` maps each op
    back to its book row(s) (``row`` None for a deleted row); ``summary`` is
    one line per change; ``notes`` name what the book does not price live
    and what BidSheet.ai will do beyond the edit (a library crew copied)."""
    estimate_id: object
    estimate_v: str
    ops: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    summary: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def as_json(self) -> dict:
        return {"estimate_id": self.estimate_id, "estimate_v": self.estimate_v,
                "ops": self.ops, "rows": self.rows, "summary": self.summary,
                "notes": self.notes}

    def text(self) -> str:
        """The CLI's printout: the summary (or "no changes"), then any notes."""
        lines = list(self.summary) if self.ops else ["no changes"]
        if self.notes:
            lines += ["", "Notes:"] + [f"  {n}" for n in self.notes]
        if self.ops:
            lines += ["", f"{len(self.ops)} op(s) for estimate {self.estimate_id}"]
        return "\n".join(lines)
