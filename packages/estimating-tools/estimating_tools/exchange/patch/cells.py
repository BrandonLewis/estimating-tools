"""The cells a patch queues for the writer, and the row tagging every other
patch module goes through."""
from __future__ import annotations

from estimating_tools.exchange import writer
from estimating_tools.exchange.reader.errors import REBUILD

__all__ = ["KEEP", "PARENT_FIELDS", "REBUILD", "Cells"]

#: A ``tag`` argument left as it is in the book.
KEEP = object()
#: The tag (``Declaration.row_kinds()``) that names a row's parent.
PARENT_FIELDS = ("parent",)


def _versions_from(payload: dict) -> dict:
    """``(kind, id) -> v`` from a fresh read-model payload; element quantities
    are ``("quantity", element id, key)``."""
    out = {}
    for section, kind in (("items", "item"), ("elements", "element"),
                          ("activities", "activity"), ("resources", "resource"),
                          ("crews", "crew")):
        for row in payload.get(section) or []:
            if "id" in row and "v" in row:
                out[(kind, int(row["id"]))] = row["v"]
            for step in row.get("steps") or []:
                out[("step", int(step["id"]))] = step["v"]
            for q in row.get("quantities") or []:
                if kind == "element" and "v" in q:
                    out[("quantity", int(row["id"]), q.get("key"))] = q["v"]
    estimate = payload.get("estimate") or {}
    if "id" in estimate and "v" in estimate:
        out[("estimate", int(estimate["id"]))] = estimate["v"]
    return out


class Cells:
    """What one patch will write. ``book`` is the reader's opened book (its
    cells are the book as read); ``cells`` is ``{tab title: {ref: value}}``
    for :func:`writer.write`; ``tagged`` the ``(tab, row)`` pairs written;
    ``problems`` what could not be written, each ending in what to do."""

    def __init__(self, book, result, payload: dict):
        self.book, self.result = book, result
        self.versions = _versions_from(payload)
        self.cells: dict = {}
        self.tagged: set = set()
        self.problems: list = []

    def ws(self, key):
        """The worksheet of a layout tab key (``cost_report``, ``crews``, ...)."""
        return self.book.ws(key)

    def put(self, key, row, letter, value):
        """Queue one cell. A value cell that already holds ``value`` is left
        alone; a :class:`writer.Formula` is always queued."""
        current = self.ws(key)[f"{letter}{row}"].value
        if not isinstance(value, writer.Formula):
            if value is None and current in (None, ""):
                return
            if current == value and type(current) is type(value):
                return
        tab = self.book.tab(key)
        self.cells.setdefault(tab, {})[f"{letter}{row}"] = value
        self.tagged.add((tab, row))

    def problem(self, text):
        """Record what could not be written (once)."""
        if text not in self.problems:
            self.problems.append(text)

    def v_of(self, kind, ident):
        """A row's ``v`` after the apply: the plan's ``versions`` first, else
        the fresh payload's; None when neither has it."""
        if (kind, ident) in self.result.versions:
            return self.result.versions[(kind, ident)]
        return self.versions.get((kind, ident))

    def derived(self, key, kind, name) -> bool:
        """Tag ``name`` of ``kind`` on sheet ``key`` is derived: its cell
        holds a formula (the chain names the block the row sits in), which
        the writer would refuse to overwrite and nothing need write."""
        tag = self.book.decl.sheets[key].tags.get(name)
        return tag is not None and kind in tag.derived

    def tag(self, key, row, kind, ident=KEEP, *, v=KEEP, parent=KEEP):
        """Write the tags ``kind`` carries in the declaration (the book's
        ``kinds``): ``id`` (``ident``), ``v`` (skipped when None or the kind
        declares none) and ``parent`` (skipped when derived for ``kind``).
        ``KEEP`` leaves a field alone."""
        declared = self.book.kinds[key]["kinds"].get(kind, {})
        for name, letter in declared.items():
            if name == "id" and ident is not KEEP:
                self.put(key, row, letter, ident)
            elif name == "v" and v is not KEEP and v is not None:
                self.put(key, row, letter, v)
            elif name in PARENT_FIELDS and parent is not KEEP and not self.derived(key, kind, name):
                self.put(key, row, letter, parent)
