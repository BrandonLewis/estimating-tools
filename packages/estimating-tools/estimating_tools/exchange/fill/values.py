"""The values a template fill writes into the rows it placed (engine spec,
Fill step 2): per row, its stored identity tags (id, ``v``, key, rate link,
an activity's parent), its bound inputs, its export values and its labels,
as the read model holds them -- and, on a blocks sheet, the engine's
owner-row helper (Fill step 3), which ``prototype_cells`` also writes on
the prototype rows themselves. Everything else on the row (its kind tag,
its formulas, its derived tags, its written text, its styles) came with the
prototype. A Decimal goes in as the patch writes one (``spelled``: an int
when whole, else the float of its text), a flag input as ``Y``/``N``, a
date label as an Excel serial (``labels.resolve``); nothing (None, "")
leaves the cell as the prototype left it, blank."""
from __future__ import annotations

from estimating_tools.exchange import contract, labels, writer
from estimating_tools.exchange.fill.lint import needed, owner_row_formula
from estimating_tools.exchange.patch.prototypes import spelled
from estimating_tools.exchange.reader.blocks import Blocks
from estimating_tools.exchange.reader.fields import inputs_for_decl

__all__ = ["header_cells", "named_cells", "prototype_cells", "row_cells"]


def _identity(sheet, row) -> dict:
    """``{letter: value}`` for the row's stored identity tags."""
    out = {}
    cls = sheet.kinds().get(row.kind)
    names = contract.tags_for(row.kind, marker=cls in ("marker", "banner"))
    obj = row.obj
    for name in names:
        tag = sheet.tags.get(name)
        if tag is None or row.kind in tag.derived:
            continue
        if name == "id":
            value = obj.element_id if row.kind == "ELEMENT_QTY" else getattr(obj, "id", None)
        elif name == "v":
            value = getattr(obj, "v", None)
        elif name == "key":
            value = getattr(obj, "key", None)
        elif name == "parent":
            value = obj.parent_id if row.kind == "ACTIVITY" else row.owner_id
        else:
            value = None
        out[tag.column] = value
    ref = sheet.tags.get("ref")
    attr = contract.REF_ATTR.get(row.kind)
    if ref is not None and attr is not None and row.kind not in ref.derived:
        out[ref.column] = getattr(obj, attr)
    return out


def row_cells(decl, key, row, at: int, wb=None) -> dict:
    """``{ref: value}`` the fill writes on placed row ``row`` at sheet row
    ``at`` (``wb``: the parsed read model a label's relations walk). A
    display or rates row gets its labels and its id tag only."""
    sheet = decl.sheets[key]
    out = {}
    shown = sheet.role in ("display", "rates")       # laid out, never read: no identity
    if not shown and (row.obj is not None
                      or sheet.kinds().get(row.kind) in ("marker", "banner")):
        for letter, value in _identity(sheet, row).items():
            out[letter] = spelled(value)
    if row.obj is not None:
        if not shown:
            for inp in inputs_for_decl(decl, key, row.kind, stepped=row.stepped):
                out[inp.letter] = spelled(getattr(row.obj, inp.base_attr), inp)
            for letter, attr in sheet.export_values.get(row.kind, {}).items():
                out[letter] = spelled(getattr(row.obj, attr))
        for letter, label in sheet.labels.get(row.kind, {}).items():
            out[letter] = spelled(labels.resolve(label, row.obj, wb))
        # A display or rates row stores the id its source names it by, which
        # a refresh matches it on.
        if shown and sheet.tag("id") and row.ident is not None:
            out[sheet.tag("id")] = spelled(row.ident)
    owner_col = sheet.tag("owner_row")
    if sheet.role == "blocks" and owner_col is not None:
        out[owner_col] = writer.Formula(owner_row_formula(
            sheet.tag("kind"), Blocks(sheet).owner.kind, owner_col, sheet.header_row, at))
    return {f"{letter}{at}": value for letter, value in out.items()
            if value is not None and value != ""}


def prototype_cells(decl, protos) -> dict:
    """``{ref: value}`` on the prototype sheet: the engine's owner-row helper
    on every row of every blocks sheet's prototypes (``lint.needed``), each
    for its own row. The fill skips the prototype's cell when it places a
    row (``row_cells`` writes the helper there); a later patch or refresh
    inserts from the prototype rows themselves (``InsertRows``,
    ``type_row``) and copies every cell, translated, so the filled book's
    prototypes must carry it -- a row inserted without it would find no
    owner, and a formula that prices through it (a resource's activity
    multiplier) would price at 0."""
    out = {}
    for proto_key, (key, _kinds) in needed(decl).items():
        sheet = decl.sheets[key]
        owner_col = sheet.tag("owner_row")
        if sheet.role != "blocks" or owner_col is None:
            continue
        proto = protos[proto_key]
        for r in range(proto.first, proto.last + 1):
            out[f"{owner_col}{r}"] = writer.Formula(owner_row_formula(
                sheet.tag("kind"), Blocks(sheet).owner.kind, owner_col, sheet.header_row, r))
    return out


def header_cells(decl, key, wb, *, exported_at: str, host: str) -> dict:
    """``{ref: value}`` for sheet ``key``'s header cells."""
    scope = {"estimate": wb.estimate, "exported_at": exported_at, "host": host}
    out = {}
    for cell, label in decl.sheets[key].header.items():
        value = spelled(labels.resolve(label, scope, wb))
        if value is not None and value != "":
            out[cell] = value
    return out


def named_cells(decl, key, wb, at: dict) -> dict:
    """``{ref: value}`` for a flat sheet's named rows (``at``: name -> the
    template row holding it): an input's or an as-of-export figure's value
    from the estimate (a formula figure is the template's), and the ESTIMATE
    row's identity tags."""
    sheet = decl.sheets[key]
    out = {}
    for name, nr in (sheet.named_rows.rows.items() if sheet.named_rows else ()):
        row = at.get(name)
        if row is None:
            continue
        if not nr.formula:
            value = spelled(getattr(wb.estimate, name, None))
            if value is not None and value != "":
                out[f"{sheet.named_rows.value_column}{row}"] = value
        if nr.kind == "ESTIMATE":
            for tag, value in (("id", wb.estimate.id), ("v", wb.estimate.v)):
                if sheet.tag(tag):
                    out[f"{sheet.tag(tag)}{row}"] = spelled(value)
    return out
