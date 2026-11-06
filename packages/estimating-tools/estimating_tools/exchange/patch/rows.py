"""Tag the rows each op came from: the estimate, items, element quantities,
activities (with a created activity's whole block), steps and resources.
Crew rosters are collected for ``crews``. Which op names which row is the
contract's (``contract.OP_KINDS``, ``contract.CREATES``); where the rows sit
is the declaration's and the scan's."""
from __future__ import annotations

from estimating_tools.exchange import contract
from estimating_tools.exchange.patch.cells import KEEP, REBUILD
from estimating_tools.exchange.patch.prototypes import fill_inputs, type_row

__all__ = ["run_ops"]


def _resolve(cells, op):
    """``(kind, id, created)`` of the row an op names."""
    ref = op.get("ref")
    if isinstance(ref, str) and ref.startswith("new:"):
        made = cells.result.created.get(ref)
        if made is None:
            raise ValueError(f"the plan did not say what {ref} became")
        return made[0], made[1], True
    return contract.OP_KINDS[op["op"].split(".", 1)[0]], int(ref), False


def _missing(cells, kind, ident):
    cells.problem(f"{kind} {ident} is not in the fresh estimate, so its row keeps only its "
                  f"id -- {REBUILD}")


def _estimate(cells, scanned, op):
    """``estimate.update``: the ``v`` goes on the ESTIMATE row, whichever
    estimate rows were edited (an estimate input row declares no ``v``)."""
    line = next((x for x in scanned.all_lines() if x.kind == "ESTIMATE"), None)
    if line is not None:
        cells.tag(line.sheet, line.row, "ESTIMATE", v=cells.v_of("estimate", int(op["ref"])))


def _markers(scanned, key, occ):
    """The marker rows of ``occ``'s block (its child blocks' open and close
    markers, as the declaration names them)."""
    return [line for line in scanned.lines.get(key, ())
            if line.occ is occ and line.kind is not None and occ.blocks.is_marker(line.kind)]


def _activity(cells, scanned, fresh, key, row, kind, ident, created):
    a = fresh.activity(ident)
    if a is None:
        _missing(cells, "activity", ident)
    cells.tag(key, row, kind, ident, v=cells.v_of("activity", ident),
              parent=a.parent_id if a is not None else KEEP)
    if not created:
        return
    occ = next((o for o in scanned.activities if o.line.row == row), None)
    if occ is None:
        return
    fill_inputs(cells, key, row, "ACTIVITY", a, stepped=occ.has_steps_marker)
    # The block: its markers and its step and resource rows name it.
    for line in _markers(scanned, key, occ):
        cells.tag(key, line.row, line.kind, parent=ident)
    for line in occ.steps + occ.resources:
        cells.tag(key, line.row, line.kind, parent=ident)


def _child(cells, key, row, kind, typed, ident, parent, obj, created):
    """A STEP or RESOURCE row: typed ones become rows of ``kind`` first."""
    if obj is None:
        _missing(cells, kind.lower(), ident)
    if typed:
        type_row(cells, key, row, kind)
    cells.tag(key, row, kind, ident, v=cells.v_of(kind.lower(), ident), parent=parent)
    if created:
        fill_inputs(cells, key, row, kind, obj)


def _row(cells, scanned, fresh, steps, op, key, row):
    # Crew rosters are ``crews``' (one op per crew, every member row).
    if key is None or key == scanned.sheet_of("CREW"):
        return
    kind_col = cells.book.kinds[key]["kind_cell"]
    stored = cells.ws(key)[f"{kind_col}{row}"].value
    typed = stored in (None, "")
    kind = contract.CREATES.get(op["op"]) if typed else str(stored).strip()
    what, ident, created = _resolve(cells, op)
    if what == "element":
        v = cells.result.versions.get(("element", ident))
        if v is None:
            v = cells.versions.get(("quantity", ident, op["fields"].get("key")))
        cells.tag(key, row, kind, v=v)
    elif what == "item":
        cells.tag(key, row, kind, ident, v=cells.v_of("item", ident))
    elif what == "activity":
        _activity(cells, scanned, fresh, key, row, kind, ident, created)
    elif what == "step":
        found = steps.get(ident)
        _child(cells, key, row, "STEP", typed, ident, found[1].id if found else KEEP,
               found[0] if found else None, created)
    elif what == "resource":
        res = next((r for r in fresh.resources if r.id == ident), None)
        _child(cells, key, row, "RESOURCE", typed, ident, res.activity_id if res else KEEP,
               res, created)


def run_ops(cells, scanned, change_set, result, fresh) -> dict:
    """Tag the rows of every op in ``change_set`` but the crew rosters and
    the deletes (a deleted row is gone). Returns the crews still to patch:
    ``{crew id: (op index, op)}`` for each ``crew.update_members``, plus
    ``(None, None)`` for each crew the plan says was copied
    (``created["crew:<id>"]``) without one. ``fresh`` is the parsed fresh
    payload."""
    tab_keys = {s.tab: k for k, s in cells.book.decl.sheets.items()}
    steps = {st.id: (st, a) for a in fresh.activities for st in a.steps}
    crews = {}
    for index, op in enumerate(change_set.ops):
        name = op["op"]
        if name.endswith(".delete"):
            continue
        if name == "estimate.update":
            _estimate(cells, scanned, op)
            continue
        if name == "crew.update_members":
            crews[int(op["ref"])] = (index, op)
            continue
        for where in change_set.rows:
            if where["op_index"] == index and where.get("row") is not None:
                _row(cells, scanned, fresh, steps, op, tab_keys.get(where["sheet"]), where["row"])
    for key in result.created:
        kind, sep, old = key.partition(":")
        if kind == "crew" and sep and old.isdigit():
            crews.setdefault(int(old), (None, None))
    return crews
