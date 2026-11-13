"""A template's label cells (a declaration's ``labels`` and ``header``):
read-model values a fill writes and the reader never reads -- an item's
description, an element's name, the figure a Checks row compares against,
the estimate's name in a sheet's title block.

A label is one bare path to one value: a scalar attribute
(``description``), a key of a dict attribute (``cost_split.labor``), or a
walk through the read model's own relations to one of those
(``activity.item.item_number``: ``NAV``) -- never a relation, a table or a
list itself, whose repr it would write. Its value goes in as the
read model holds it (a number stays a number; a date field, ``DATES``, goes
in as an Excel date serial). There is no text-slot syntax: text composed of
several values is a template formula over label cells. The loader checks a
blocks or flat sheet's label paths against its kinds' classes (``CLASSES``);
the lint checks a display sheet's, whose row kinds are its prototypes'."""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from datetime import date

from estimating_tools.exchange import model

__all__ = ["CLASSES", "DATES", "HEADER", "Label", "LabelError", "NAV", "attributes", "check",
           "check_path", "parse", "resolve", "serial"]

_PATH = re.compile(r"^[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*){0,3}$")

#: The read-model class of each contract kind's rows (blocks and flat sheets).
CLASSES = {"ITEM": model.Item, "ELEMENT_QTY": model.Quantity, "ACTIVITY": model.Activity,
           "STEP": model.Step, "RESOURCE": model.Resource, "CREW": model.Crew,
           "MEMBER": model.Member, "SECTION": model.Section, "ITEM_BID": model.Item,
           "BID_TOTAL": model.BidTotal, "SHARE": model.Share}
#: The read model's relations a path may walk: (class, name) -> (class it
#: reaches, how). None when the row has none (an activity without a crew).
NAV = {
    (model.Activity, "item"): (model.Item, lambda wb, a: wb.item(a.item_id)),
    (model.Activity, "crew"): (model.Crew,
                               lambda wb, a: None if a.crew_id is None else wb.crew(a.crew_id)),
    (model.Resource, "activity"): (model.Activity, lambda wb, r: wb.activity(r.activity_id)),
    (model.Quantity, "element"): (model.Element, lambda wb, q: wb.element(q.element_id)),
    (model.Share, "activity"): (model.Activity, lambda wb, s: wb.activity(s.activity_id)),
    (model.Share, "item"): (model.Item, lambda wb, s: wb.item(s.item_id)),
}
#: What a sheet's ``header`` cells may name.
HEADER = {"estimate": model.Estimate, "exported_at": None, "host": None}
#: Fields the read model holds as ISO date text: written as Excel serials.
DATES = frozenset({"start_date", "finish_date", "end_date", "day"})
_EPOCH = date(1899, 12, 30)


class LabelError(ValueError):
    """A label the loader or the lint refuses; the message names the path."""


@dataclass(frozen=True)
class Label:
    path: str

    @property
    def paths(self) -> tuple:
        return (self.path,)


def parse(text) -> Label:
    """A ``Label`` from its declaration text, or ``LabelError``."""
    if isinstance(text, str) and _PATH.match(text):
        return Label(text)
    if isinstance(text, str) and ("{" in text or "}" in text):
        raise LabelError(f"{text!r}: a label is one path -- compose text with a template "
                         "formula over label cells")
    raise LabelError(f"{text!r} is not a path (lower-case names joined by dots, at most four)")


def attributes(cls) -> dict:
    """``{name: is a dict}`` for a dataclass's fields and its properties."""
    out = {f.name: str(f.type).startswith("dict") for f in dataclasses.fields(cls)}
    out.update({name: False for name, value in vars(cls).items() if isinstance(value, property)})
    return out


def _lists(cls) -> set:
    """The names of a dataclass's tuple and list fields (a row's steps, an
    estimate's sections): no one value a label could write."""
    return {f.name for f in dataclasses.fields(cls)
            if str(f.type).split("[")[0].split(" ")[0] in ("tuple", "list")}


def _value(cls, part: str, path: str) -> None:
    """``part`` of ``cls`` is one value, or ``LabelError``: a label ends on a
    scalar field or a key of a table, never a table, a list or a relation
    (whose repr it would write)."""
    if (cls, part) in NAV:
        raise LabelError(f"{path}: {part} is a relation -- name one of its fields")
    if part in _lists(cls):
        raise LabelError(f"{path}: {part} is a list -- a label names one value")
    if attributes(cls).get(part):
        raise LabelError(f"{path}: {part} is a table -- name one of its keys")


def check_path(cls, path: str) -> None:
    """``path`` names one value a ``cls`` object has (a scalar field, or a
    key of a table attribute), or ``LabelError``."""
    parts = path.split(".")
    node = cls
    for n, part in enumerate(parts):
        if node is dict:
            if n < len(parts) - 1:
                raise LabelError(f"{path}: a key of a table ends the path")
            return
        nav = NAV.get((node, part))
        if nav is None and part not in attributes(node):
            raise LabelError(f"{path}: {node.__name__} has no {part}")
        if n == len(parts) - 1:
            _value(node, part, path)
        elif nav is not None:
            node = nav[0]
        elif part in _lists(node):
            _value(node, part, path)
        elif attributes(node)[part]:
            node = dict
        else:
            raise LabelError(f"{path}: {part} is not a table or a relation")


def check(kind: str, label: Label) -> None:
    """``label`` names something a ``kind`` row has (``kind`` ``"header"``
    for a header cell), or ``LabelError``."""
    if kind == "header":
        head, _sep, tail = label.path.partition(".")
        if head not in HEADER:
            raise LabelError(f"{label.path}: a header names estimate.<field>, exported_at or host")
        if (HEADER[head] is None) != (not tail):
            raise LabelError(f"{label.path}: {head} " + ("has no fields" if HEADER[head] is None
                                                         else "needs a field"))
        if tail and tail not in attributes(HEADER[head]):
            raise LabelError(f"{label.path}: the estimate has no {tail}")
        if tail:
            _value(HEADER[head], tail, label.path)
        return
    cls = CLASSES.get(kind)
    if cls is None:
        raise LabelError(f"{kind} rows have no labels")
    check_path(cls, label.path)


def serial(value) -> int:
    """An ISO date (text or ``date``) as an Excel date serial."""
    day = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return (day - _EPOCH).days


def resolve(label: Label, obj, wb=None):
    """The value ``label`` writes for ``obj`` (``wb``: the parsed read model,
    for a relation). None when a step finds nothing. A ``dict`` ``obj`` is a
    namespace (a header cell's: ``estimate``, ``exported_at``, ``host``)."""
    value = obj
    parts = label.path.split(".")
    for part in parts:
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get(part)
            continue
        nav = NAV.get((type(value), part))
        value = nav[1](wb, value) if nav is not None else getattr(value, part)
    if value not in (None, "") and parts[-1] in DATES:
        return serial(value)
    return value
