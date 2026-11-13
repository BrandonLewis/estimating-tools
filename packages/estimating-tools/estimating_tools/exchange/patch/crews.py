"""Crews whose roster the apply replaced or that it copied out of the
library: new member ids (and a copy's new crew id) on their rows.

BidSheet.ai deletes and recreates every member on ``crew.update_members``,
so every member row takes a new id. Until the plan returns member ids
(BidSheet.ai #1704 -- this is the only module that change should touch)
they are inferred: ids are assigned in creation order, which is the roster
order sent, so the fresh crew's members sorted by id pair with the roster
rows in sheet order. Each pair must agree on classification, count, rate
override and (when sent) labour rate, else nothing is written for that
crew and the report names its rows; the next read then refuses, it never
pushes a duplicate. A crew copied into the estimate takes its new id on its
owner row and markers and loses the library banner row (a built estimate
crew has none: the row is left blank). When the payload still lists the
library crew beside its copy, the book cannot hold both blocks: a problem,
nothing written for that crew.

Where things sit is the declaration's: the crew sheet is the one whose owner
block is CREW (``Scan.sheet_of``), a member's labour rate id is the sheet's
``ref`` tag, its export values are the MEMBER ``export_values``, and the
banner and close marker are the block's (``Blocks.banners``,
``Blocks.last.close``)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from estimating_tools.exchange.patch.cells import REBUILD
from estimating_tools.exchange.patch.prototypes import fill_inputs, spelled, type_row
from estimating_tools.exchange.reader import fields as F
from estimating_tools.exchange.reader.blocks import Blocks
from estimating_tools.exchange.reader.scan import norm_id

__all__ = ["patch_crews"]


def _plan_member_ids(result, op_index):
    """Member ids the plan returns for op ``op_index``, in roster order: the
    entry of ``result.raw["ops"]`` whose ``index`` is ``op_index``, its
    ``after.members[].id``. None when the plan carries none."""
    if op_index is None:
        return None
    for entry in result.raw.get("ops") or []:
        if not isinstance(entry, dict) or entry.get("index") != op_index:
            continue
        after = entry.get("after")
        members = after.get("members") if isinstance(after, dict) else None
        if isinstance(members, list) and all(isinstance(m, dict) and "id" in m
                                             for m in members):
            try:
                return [int(m["id"]) for m in members]
            except (TypeError, ValueError):
                return None
    return None


def _sent(cells, key, edit, op):
    """Per roster row, what it became on the server: ``{classification,
    count, hourly_rate_override, labor_rate_id}`` as the op sent it, else (a
    library copy with no roster op) as the row holds it."""
    if op is not None:
        return list(op["fields"].get("members") or [])
    out, ws = [], cells.ws(key)
    ref = cells.book.decl.sheets[key].tag("ref")
    for rr in edit.roster:
        values = F.read_line(cells.book, rr.line, "MEMBER").values
        keep = rr.base or rr.source      # a field the sheet does not bind is the member's
        kept = lambda name: F.bound_or_kept(values, keep, "MEMBER", name)  # noqa: E731
        out.append({"classification": kept("classification"),
                    "count": kept("count"),
                    "hourly_rate_override": kept("hourly_rate_override"),
                    "labor_rate_id": norm_id(ws[f"{ref}{rr.line.row}"].value) if ref else None})
    return out


def _number(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False


def _same_member(member, sent) -> bool:
    """The fresh ``member`` is the one ``sent`` asked for: classification
    (ignoring case), count and rate override (as numbers; blank matches
    None), and the labour rate when one was sent."""
    if member is None:
        return False
    classification, count = sent.get("classification"), sent.get("count")
    if classification is None or count is None:
        return False
    if (str(classification).strip().casefold()
            != str(member.classification).strip().casefold()):
        return False
    if _number(count) != _number(member.count):
        return False
    if _number(sent.get("hourly_rate_override")) != _number(member.hourly_rate_override):
        return False
    rate = sent.get("labor_rate_id")
    return rate is None or norm_id(rate) == member.labor_rate_id


def _markers(scanned, key, edit, blocks):
    """The crew block's banner and close-marker rows, in sheet order."""
    out, inside, close = [], False, blocks.last.close
    for line in scanned.lines.get(key, ()):
        if line is edit.line:
            inside = True
            continue
        if not inside:
            continue
        if line.kind == blocks.owner.kind:
            break
        if line.kind in blocks.banners or line.kind == close:
            out.append(line)
            if line.kind == close:
                break
    return out


def _rows_label(tab, rows):
    rows = sorted(rows)
    if not rows:
        return tab
    if len(rows) == 1:
        return f"{tab} row {rows[0]}"
    return f"{tab} rows {rows[0]}-{rows[-1]}"


def _crew(cells, scanned, changes, result, fresh, crew_id, op_index, op):
    key = scanned.sheet_of("CREW")
    edit = next((e for e in changes.crews if e.base.id == crew_id), None)
    if edit is None or key is None:
        return
    sheet = cells.book.decl.sheets[key]
    blocks = Blocks(sheet)
    tab, name = cells.book.tab(key), edit.base.name
    copied = result.created.get(f"crew:{crew_id}")
    new_id = copied[1] if copied is not None else crew_id
    crew = fresh.crew(new_id)
    if crew is None:
        cells.problem(f"{tab} row {edit.line.row}: crew {name} (crew {new_id}) is not in the "
                      f"fresh estimate -- {REBUILD}")
        return
    if new_id != crew_id and fresh.crew(crew_id) is not None:
        cells.problem(f"{tab} row {edit.line.row}: BidSheet.ai copied crew {name} into this "
                      f"estimate as crew {new_id} and kept the library crew; the book holds "
                      f"one block for both -- {REBUILD}")
        return
    rows = [rr.line for rr in edit.roster]
    sent = _sent(cells, key, edit, op)
    by_id = {m.id: m for m in crew.members}
    ids = _plan_member_ids(result, op_index) or sorted(by_id)
    if not (len(rows) == len(sent) == len(ids)
            and all(_same_member(by_id.get(mid), x) for mid, x in zip(ids, sent))):
        where = _rows_label(tab, [line.row for line in rows] or [edit.line.row])
        cells.problem(f"{where}: crew {name}'s member rows could not be matched to "
                      f"BidSheet.ai's -- {REBUILD}")
        return
    cells.tag(key, edit.line.row, blocks.owner.kind, new_id, v=cells.v_of("crew", new_id))
    ws = cells.ws(key)
    ref = sheet.tag("ref")
    exports = sheet.export_values.get("MEMBER", {})
    for line, mid in zip(rows, ids):
        member = by_id[mid]
        if line.kind is None:
            type_row(cells, key, line.row, "MEMBER")
        cells.tag(key, line.row, "MEMBER", mid, parent=new_id)
        fill_inputs(cells, key, line.row, "MEMBER", member)
        if ref and ws[f"{ref}{line.row}"].value in (None, "") and member.labor_rate_id:
            cells.put(key, line.row, ref, member.labor_rate_id)
        for letter, attr in exports.items():
            if ws[f"{letter}{line.row}"].value in (None, ""):
                cells.put(key, line.row, letter, spelled(getattr(member, attr)))
    for line in _markers(scanned, key, edit, blocks):
        if line.kind in blocks.banners and crew.scope != "library":
            # A built estimate crew has no banner row: left blank. A derived
            # parent tag is a formula, kept (the writer refuses to overwrite
            # a formula; hidden, it makes no typed row).
            marker = sheet.markers.get(line.kind)
            letters = [sheet.tag("kind")]
            if marker is not None and marker.cue:
                letters.append(marker.cue[0])
            if sheet.tag("parent") and not cells.derived(key, line.kind, "parent"):
                letters.append(sheet.tag("parent"))
            for letter in letters:
                cells.put(key, line.row, letter, None)
        else:
            cells.tag(key, line.row, line.kind, parent=new_id)


def patch_crews(cells, scanned, changes, result, fresh, pending: dict):
    """Patch each crew ``pending`` names (``rows.run_ops``' return:
    ``{crew id: (op index, op)}``, ``(None, None)`` for a copy without a
    roster op): new member ids, a copy's crew id, the owner row's ``v``;
    or a problem naming the crew's rows when its members cannot be matched."""
    for crew_id, (op_index, op) in sorted(pending.items()):
        _crew(cells, scanned, changes, result, fresh, crew_id, op_index, op)
