"""A refresh's decision (``merge.Merge``) as writer input: the row ops,
bottom-up per sheet so each names the book's original rows, and every cell
-- the existing rows' and the inserted rows' tags, inputs, export values and
rate links -- addressed as the sheets stand after the ops."""
from __future__ import annotations

from estimating_tools.exchange import contract, rowops
from estimating_tools.exchange.patch.prototypes import prototype_rows, spelled
from estimating_tools.exchange.reader import fields as F
from estimating_tools.exchange.refresh.merge import cell_value

__all__ = ["layout", "new_row_cells", "remap"]


def _stored_tags(book, key, kind) -> tuple:
    """The columns of ``kind``'s tags that hold stored values (not derived
    formulas): the inserted row's own, never copied from the prototype."""
    sheet = book.decl.sheets[key]
    out = []
    for name, letter in book.kinds[key]["kinds"].get(kind, {}).items():
        tag = sheet.tags.get(name)
        if tag is not None and kind not in tag.derived:
            out.append(letter)
    return tuple(out)


def new_row_cells(book, key, kind, owner, obj) -> dict:
    """``{letter: value}`` an inserted row of ``kind`` takes beyond its
    prototype's cells: its stored tags (id, ``v``, a stored parent), its rate
    link, its bound inputs and its export values, as the build writes them."""
    sheet = book.decl.sheets[key]
    tags = book.kinds[key]["kinds"].get(kind, {})
    out = {}
    if "id" in tags:
        out[tags["id"]] = obj.id
    if "v" in tags and getattr(obj, "v", None) is not None:
        out[tags["v"]] = obj.v
    parent = sheet.tags.get("parent")
    if "parent" in tags and parent is not None and kind not in parent.derived:
        out[tags["parent"]] = owner
    attr, ref = contract.REF_ATTR.get(kind), sheet.tag("ref")
    if attr and ref and getattr(obj, attr) not in (None, ""):
        out[ref] = getattr(obj, attr)
    for inp in F.inputs_for(book, key, kind):
        value = cell_value(getattr(obj, inp.base_attr), inp)
        if value is not None:
            out[inp.letter] = value
    for letter, name in sheet.export_values.get(kind, {}).items():
        out[letter] = spelled(getattr(obj, name))
    return out


def layout(book, merge) -> tuple:
    """``(row ops, cells)`` for ``writer.edit``: ``cells`` is ``{tab: {ref:
    value}}`` after the ops."""
    entries = []
    for ins in merge.inserts:
        ws, first, last = prototype_rows(book, ins.kind)
        op = rowops.InsertRows(sheet=book.tab(ins.key), before=ins.before, source=ws.title,
                               first=first, last=last, times=len(ins.rows),
                               skip=_stored_tags(book, ins.key, ins.kind))
        entries.append((op, ins))
    for key, row in merge.deletes:
        entries.append((rowops.DeleteRows(sheet=book.tab(key), first=row), None))
    entries.sort(key=lambda e: (e[0].sheet, -(e[0].before if isinstance(e[0], rowops.InsertRows)
                                              else e[0].first)))
    ops = [op for op, _ins in entries]
    rowmap = rowops.RowMap(ops)
    cells = remap({book.tab(key): {f"{letter}{row}": value
                                   for (row, letter), value in refs.items()}
                   for key, refs in merge.cells.items()}, rowmap)
    for index, (op, ins) in enumerate(entries):
        if ins is None:
            continue
        rows = rowmap.inserted(index)
        for k, obj in enumerate(ins.rows):
            row = rows[k * op.width]
            target = cells.setdefault(op.sheet, {})
            for letter, value in new_row_cells(book, ins.key, ins.kind, ins.owner, obj).items():
                target[f"{letter}{row}"] = value
    return ops, cells


def remap(cells: dict, rowmap) -> dict:
    """``cells`` (``{tab: {ref: value}}``, addressed before the ops) moved to
    where ``rowmap`` says their rows went. A cell on a deleted row is an
    internal error: nothing writes into a row it removes."""
    out = {}
    for tab, refs in cells.items():
        target = out.setdefault(tab, {})
        for ref, value in refs.items():
            letters = ref.rstrip("0123456789")
            row = rowmap.row(tab, int(ref[len(letters):]))
            if row is None:
                raise ValueError(f"internal error: {tab}!{ref} is written and deleted")
            target[f"{letters}{row}"] = value
    return out
