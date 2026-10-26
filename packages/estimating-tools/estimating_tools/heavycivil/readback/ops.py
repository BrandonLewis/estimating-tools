"""Turn classified rows into ``apply_estimate_workbook_changes`` ops.

Op shape (BidSheet.ai ``estimate_workbook_ops``): ``{op, ref, v?, fields}``.
``ref`` is a row id, or a ``new:<token>`` a creating op defines for later ops
in the same set (``new:aN`` activities, ``new:sN`` steps, ``new:rN``
resources). ``v`` is carried only on ops against existing rows -- the
baseline's ``v``, which the built book's hidden ``v`` equals -- so a conflict
can only be raised on a row the estimator touched. Decimals are sent as
plain-text numbers; ``includes_burden`` as a strict boolean.

Order (spec §3): estimate, items, element quantities; activity moves
(topmost first -- a copy whose parent was cut to another item is created
under it once it sits there), creates (parent before child), updates; step adds, updates;
resource creates, updates; crew rosters, then each copied activity's crew
(after the rosters, so a library crew this set copies maps to its copy);
then deletes -- resources, steps, activities (deepest first).
"""
from __future__ import annotations

from decimal import Decimal

from estimating_tools.heavycivil.columns import BF, CR, CW
from estimating_tools.heavycivil.readback import fields as F
from estimating_tools.heavycivil.readback.classify import LINK_FIELDS, MANAGED
from estimating_tools.heavycivil.readback.report import ChangeSet, change, dec_str, event, fmt
from estimating_tools.heavycivil.readback.scan import norm_id

GROUPS = ("estimate.update", "item.update", "element.set_quantity", "activity.move",
          "activity.create", "activity.update", "step.add", "step.update",
          "resource.create", "resource.update", "crew.update_members", "activity.set_crew",
          "resource.delete", "step.delete", "activity.delete")

NOT_LIVE = "not priced live in this book: {what} -- it shows after the apply and a rebuild"


def _json(value):
    if isinstance(value, Decimal):
        return dec_str(value)
    return value


class _Builder:
    def __init__(self, book, problems):
        self.book, self.problems = book, problems
        self.groups = {g: [] for g in GROUPS}
        self.notes = []
        self.tokens = {"s": 0, "r": 0}

    def token(self, prefix):
        self.tokens[prefix] += 1
        return f"new:{prefix}{self.tokens[prefix]}"

    def tab(self, sheet):
        return self.book.tab(sheet)

    def add(self, op, ref, fields, *, v=None, rows=(), summary=()):
        entry = {"op": op, "ref": ref}
        if v is not None:
            entry["v"] = v
        entry["fields"] = {k: _json(x) for k, x in fields.items()}
        self.groups[op].append((entry, list(rows), list(summary)))

    def problem(self, line, message, column=None):
        self.problems.add(self.tab(line.sheet), line.row, column, message)

    def finish(self, cs):
        for group in GROUPS:
            for entry, rows, summary in self.groups[group]:
                index = len(cs.ops)
                cs.ops.append(entry)
                cs.rows += [{"op_index": index, "sheet": tab, "row": row} for tab, row in rows]
                cs.summary += summary
        cs.notes += self.notes


def _changes_summary(b, line, label, changes):
    return [change(b.tab(line.sheet), line.row, label, name, before, after)
            for name, (before, after) in changes.items()]


# -- estimate, items, quantities -------------------------------------------------

def _estimate(b, ch):
    est, fields, rows, summary = b.book.model.estimate, {}, [], []
    for line in ch.estimate:
        read = F.read_estimate_input(b.book, line)
        if read.problems:
            for p in read.problems:
                b.problems.add(p.sheet, p.row, p.column, p.message)
            continue
        after, before = read.values[line.name], getattr(est, line.name)
        if F.number_equal(after, before):
            continue
        if after is None:
            b.problem(line, f"{line.name} can't be cleared -- type a value", BF.VALUE)
            continue
        fields[line.name] = after
        rows.append((b.tab("bid_form"), line.row))
        summary.append(change(b.tab("bid_form"), line.row, "estimate", line.name, before, after))
    if fields:
        b.add("estimate.update", est.id, fields, v=est.v, rows=rows, summary=summary)


def _items(b, ch):
    for item in b.book.model.items:
        lines = ch.items.get(item.id) or {}
        fields, rows, summary = {}, [], []
        for key, kind in (("cost", "ITEM"), ("bid", "ITEM_BID")):
            line = lines.get(key)
            if line is None:
                continue
            changes = F.diff(b.book, line, kind, item, b.problems)
            if changes:
                rows.append((b.tab(line.sheet), line.row))
                summary += _changes_summary(b, line, f"item {item.item_number}", changes)
                fields.update({k: after for k, (_before, after) in changes.items()})
        if fields:
            b.add("item.update", item.id, fields, v=item.v, rows=rows, summary=summary)


def _quantities(b, ch):
    for line, element, q in ch.quantities:
        changes = F.diff(b.book, line, "ELEMENT_QTY", q, b.problems)
        if changes:
            b.add("element.set_quantity", element.id,
                  {"key": q.key, "override_value": changes["override_value"][1]}, v=q.v,
                  rows=[(b.tab("cost_report"), line.row)],
                  summary=_changes_summary(b, line, f"{element.name} {q.key}", changes))


# -- activities ------------------------------------------------------------------

_CREATE_FIELDS = ("production_rate", "production_unit", "hours_per_shift", "crew_factor",
                  "count")


#: Fields a copy or cut carries from its source's payload row: they have no
#: cell in the book, so the estimator cannot have changed them.
UNPRICED_ACTIVITY = ("description",)
UNPRICED_RESOURCE = ("description", "trade", "pieces", "activity_code_id")


def _unpriced(raw, keys) -> dict:
    return {k: raw[k] for k in keys if raw.get(k) not in (None, "")}


def _inherited_count(model, activity):
    """``(multiplier, nearest parent)``: the product of ``activity``'s
    ancestors' counts in the baseline (the Cost Report's multiplier, bar its
    own count), and its parent; ``(1, None)`` for a root."""
    product, node = 1, activity
    while node.parent_id is not None:
        node = model.activity(node.parent_id)
        product *= node.count or 1
    return product, model.activity(activity.parent_id) if activity.parent_id else None


def _multiplier_note(b, tab, row, name, source):
    """A child activity that becomes a root (moved, cut away from its parent,
    or copied out from under it) loses its ancestors' count multiplier."""
    product, parent = _inherited_count(b.book.model, source)
    if product > 1:
        b.notes.append(event(tab, row, f"activity {name!r} is no longer under "
                             f"{parent.name!r}: its cost stops being multiplied by "
                             f"{product} (its parent activities' count)"))


def _activities(b, ch):
    tab = b.tab("cost_report")
    for new in ch.new_activities:
        occ, line = new.occ, new.occ.line
        if occ.item_id is None:
            continue
        stepped = occ.has_steps_marker
        values = F.read_line(b.book, line, "ACTIVITY", stepped=stepped).values
        if values.get("name") is None:
            b.problem(line, "a copied activity needs a name", CR.DESC)
            continue
        fields = {"estimate_item_id": occ.item_id, "name": values["name"],
                  "assembly_type": new.source.assembly_type}
        if new.parent is not None:
            fields["parent_id"] = new.parent
        fields.update({k: values[k] for k in _CREATE_FIELDS if values.get(k) is not None})
        fields.update(_unpriced(b.book.index.raw_activities.get(new.source.id, {}),
                                UNPRICED_ACTIVITY))
        code_id = b.book.index.activity_code.get(new.source.id)
        if code_id is not None:
            fields["activity_code_id"] = code_id
        b.add("activity.create", occ.token, fields, rows=[(tab, line.row)],
              summary=[event(tab, line.row, f"new activity {values['name']!r} "
                                            f"(a copy of activity {new.source.id})")])
        if not stepped and values.get("duration_shifts") is not None:
            b.add("activity.update", occ.token, {"duration_shifts": values["duration_shifts"]},
                  rows=[(tab, line.row)])
        if new.source.crew_id is not None:
            b.add("activity.set_crew", occ.token, {"crew_id": new.source.crew_id},
                  rows=[(tab, line.row)],
                  summary=[event(tab, line.row, f"new activity {values['name']!r} keeps "
                                                f"crew {new.source.crew_id}")])
        b.notes.append(event(tab, line.row, NOT_LIVE.format(
            what=f"the new activity {values['name']!r} in its item's total; it keeps its "
                 "source's crew and cost code, but not its element links or spread")))
        if new.parent is None:
            _multiplier_note(b, tab, line.row, values["name"], new.source)
    for move in sorted(ch.moves, key=lambda m: m.depth):
        line = move.occ.line
        item = b.book.model.item(move.item_id)
        if item is None:
            continue   # classify refused the row it sits under
        if "parent_id" in move.fields:
            text = (f"activity {move.base.name!r} becomes a root activity of item "
                    f"{item.item_number} (its parent was deleted)")
        else:
            text = (f"activity {move.base.name!r} moves to item {item.item_number} as a "
                    "root activity, with its child activities, steps and resources")
        b.add("activity.move", move.base.id, dict(move.fields), v=move.base.v,
              rows=[(tab, line.row)], summary=[event(tab, line.row, text)])
        _multiplier_note(b, tab, line.row, move.base.name, move.base)
    for occ in ch.activities:
        base = b.book.model.activity(occ.id)
        changes = F.diff(b.book, occ.line, "ACTIVITY", base, b.problems,
                         stepped=bool(base.steps))
        if changes:
            b.add("activity.update", base.id, {k: a for k, (_x, a) in changes.items()},
                  v=base.v, rows=[(tab, occ.line.row)],
                  summary=_changes_summary(b, occ.line, f"activity {base.name!r}", changes))


# -- steps -----------------------------------------------------------------------

def _step_code(b, new, fields, name, tab):
    """A copied or cut step keeps its own cost code only where the server
    offers it: a step's code must sit under its activity's code
    (``activity_edit.step_code_choices``), so only when the destination's
    code is the code of the activity the step came from."""
    ix = b.book.index
    code = ix.raw_steps.get(new.source.id, {}).get("activity_code_id")
    if code in (None, ""):
        return
    owner = ix.step_owner[new.source.id]
    dest = ix.activity_code.get(new.occ.id)   # a copy's id is its source's
    if dest is not None and dest == ix.activity_code.get(owner.id):
        fields["activity_code_id"] = code
    else:
        b.notes.append(event(tab, new.line.row, f"step {name!r} loses its cost code "
                             f"({code}): it is not offered under its new activity's code "
                             "-- set it in BidSheet.ai after the apply"))


def _steps(b, ch):
    tab = b.tab("cost_report")
    for new in ch.new_steps:
        line = new.line
        read = F.read_line(b.book, line, "STEP")
        values = read.values
        if read.bad:
            continue
        missing = [h for k, h in (("name", "a name"), ("duration", "a duration"))
                   if values.get(k) is None]
        if missing:
            b.problem(line, f"a new step needs {' and '.join(missing)}")
            continue
        fields = {"activity_id": new.occ.ref, "name": values["name"],
                  "duration": values["duration"], "duration_unit": values["duration_unit"]}
        if new.source is not None:
            _step_code(b, new, fields, values["name"], tab)
        if new.how == "cut":
            owner = b.book.index.step_owner[new.source.id]
            what = f"step {values['name']!r} moves here from activity {owner.id}"
        elif new.how == "copy":
            what = f"new step {values['name']!r} (a copy of step {new.source.id})"
        else:
            what = f"new step {values['name']!r}"
        b.add("step.add", b.token("s"), fields, rows=[(tab, line.row)],
              summary=[event(tab, line.row, what)])
    for line, step in ch.steps:
        changes = F.diff(b.book, line, "STEP", step, b.problems)
        if changes:
            b.add("step.update", step.id, {k: a for k, (_x, a) in changes.items()}, v=step.v,
                  rows=[(tab, line.row)],
                  summary=_changes_summary(b, line, f"step {step.name!r}", changes))


# -- resources -------------------------------------------------------------------

#: The four fields a same-book copy must keep to keep its source's rate link.
SAME_RESOURCE = ("name", "component_type", "unit", "unit_cost")
_RES_INPUTS = {i.field: i for i in F.INPUTS[("cost_report", "RESOURCE")]}


def source_link(res) -> dict:
    """The resource's rate link (``model.Resource.rate_link``: labour first,
    then equipment, then material, as the AE cell carries it) as the
    ``resource.create`` field that sends it."""
    link = res.rate_link
    if link is None:
        return {}
    kind, rid = link.split(":")
    return {LINK_FIELDS[kind]: int(rid)}


def _resource_create(b, new):
    tab, line = b.tab("cost_report"), new.line
    read = F.read_line(b.book, line, "RESOURCE")
    values = read.values
    if read.bad:
        return
    missing = [h for k, h in (("name", "a name"), ("component_type", "a Type"))
               if values.get(k) is None]
    if missing:
        b.problem(line, f"a new resource line needs {' and '.join(missing)}")
        return
    fields = {"activity_id": new.occ.ref}
    fields.update({k: v for k, v in values.items() if v is not None and v != ""})
    name = values["name"]
    if new.how in ("copy", "cut"):
        fields.update(_unpriced(b.book.index.raw_resources.get(new.source.id, {}),
                                UNPRICED_RESOURCE))
    if new.how == "copy":
        if all(F.same(_RES_INPUTS[k], values[k], getattr(new.source, k)) for k in SAME_RESOURCE):
            link = source_link(new.source)
            fields.update(link)
            what = (f"new line {name!r} (a copy of resource {new.source.id}"
                    + (", its rate link kept)" if link else ")"))
        else:
            what = f"new line {name!r} (an edited copy of resource {new.source.id}, unlinked)"
    elif new.how == "cut":
        fields.update(source_link(new.source))
        what = f"line {name!r} moves here from activity {new.source.activity_id}"
    elif new.how == "paste" and new.link:
        fields.pop("unit_cost", None)
        fields.update(new.link)
        what = f"new line {name!r} pasted from another workbook"
        b.notes.append(event(tab, line.row, f"{name!r} is priced at today's library rate "
                             f"({', '.join(f'{k} {v}' for k, v in new.link.items())}), not the "
                             f"unit cost the book shows ({fmt(values.get('unit_cost'))}); the "
                             "dry run shows the rate BidSheet.ai will use"))
    else:
        what = (f"new line {name!r} pasted from another workbook" if new.how == "paste"
                else f"new line {name!r}")
    if new.how == "typed":
        b.notes.append(event(tab, line.row, NOT_LIVE.format(
            what=f"the typed line {name!r} (its cost, and on the Flat sheet and the Checks "
                 "rows)")))
    else:
        b.notes.append(event(tab, line.row, f"the new line {name!r} prices live here, but "
                             "reaches the Flat sheet and the Checks rows only after the "
                             "apply and a rebuild"))
    b.add("resource.create", b.token("r"), fields, rows=[(tab, line.row)],
          summary=[event(tab, line.row, what)])


def _resources(b, ch):
    tab = b.tab("cost_report")
    for new in ch.new_resources:
        _resource_create(b, new)
    for line, res in ch.resources:
        changes = F.diff(b.book, line, "RESOURCE", res, b.problems)
        if not changes:
            continue
        if res.managed_by:
            b.problem(line, MANAGED)
            continue
        b.add("resource.update", res.id, {k: a for k, (_x, a) in changes.items()}, v=res.v,
              rows=[(tab, line.row)],
              summary=_changes_summary(b, line, f"{res.name!r}", changes))


# -- crews -----------------------------------------------------------------------

def labor_rate_for(book, classification):
    """``(labor_rate_id, error)``: the baseline labour rate whose name (or
    code, when the payload carries one) is ``classification``, ignoring case."""
    key = classification.strip().casefold()
    raw = {norm_id(r.get("id")): r for r in ((book.doc.get("rates") or {}).get("labor") or ())}
    hits = sorted({rate.id for rate in book.model.rates_by_kind("labor")
                   if key in {(rate.name or "").casefold(),
                              str(raw.get(rate.id, {}).get("code") or "").casefold()} - {""}})
    if len(hits) == 1:
        return hits[0], None
    return None, "unknown" if not hits else "ambiguous"


def _member(b, row, sort_order, *, reported=False):
    """One roster entry for ``crew.update_members``, or None (a problem).
    ``reported``: ``fields.diff`` already named this row's problem (a cleared
    count), so a missing value is not reported twice."""
    line = row.line
    read = F.read_line(b.book, line, "MEMBER")
    values = read.values
    if read.bad:
        return None, False
    classification, count = values.get("classification"), values.get("count")
    if classification is None or count is None:
        if reported:
            return None, False
        b.problem(line, "a crew member needs a classification and a count")
        return None, False
    override = values.get("hourly_rate_override")
    keep = row.base or row.source
    if keep is not None and classification == keep.classification:
        rate_id = keep.labor_rate_id
    else:
        rate_id, error = labor_rate_for(b.book, classification)
        if error == "ambiguous":
            b.problem(line, f"classification {classification!r} matches more than one "
                            "labour rate -- type its code", CW.CODE)
            return None, False
        if error and override is None:
            b.problem(line, f"classification {classification!r} matches no labour rate on "
                            "this estimate -- type a listed classification, or give the "
                            "member a Rate override", CW.CODE)
            return None, False
    entry = {"classification": classification, "count": dec_str(count),
             "labor_rate_id": rate_id,
             "hourly_rate_override": None if override is None else dec_str(override),
             "sort_order": sort_order}
    return entry, keep is None or row.base is None


def _crews(b, ch):
    tab = b.tab("crews")
    for edit in ch.crews:
        crew = edit.base
        roster, summary, rows, touched = [], [], [(tab, edit.line.row)], bool(edit.removed)
        next_order = max([m.sort_order for m in crew.members], default=-1) + 1
        for row in edit.roster:
            reported = False
            if row.base is not None:
                before = len(b.problems.items)
                changes = F.diff(b.book, row.line, "MEMBER", row.base, b.problems)
                reported = len(b.problems.items) > before
                if changes:
                    touched = True
                    summary += _changes_summary(b, row.line, f"{crew.name} member "
                                                f"{row.base.classification!r}", changes)
                order = row.base.sort_order
            else:
                order, next_order = next_order, next_order + 1
            entry, is_new = _member(b, row, order, reported=reported)
            if entry is None:
                continue
            roster.append(entry)
            if is_new:
                touched = True
                summary.append(event(tab, row.line.row,
                                     f"new {crew.name} member {entry['classification']!r}"))
                if row.source is None:
                    b.notes.append(event(tab, row.line.row, NOT_LIVE.format(
                        what=f"the typed member's rate in {crew.name}'s crew rate")))
        for gone in edit.removed:
            summary.append(event(tab, None, f"{crew.name} member {gone.classification!r} "
                                            "removed"))
        if not touched:
            continue
        if crew.scope == "library":
            b.notes.append(event(tab, edit.line.row, f"library crew {crew.name!r}: BidSheet.ai "
                                 "copies it into this estimate and edits the copy; the "
                                 "library crew and other estimates are not changed"))
        b.add("crew.update_members", crew.id, {"members": roster}, v=crew.v, rows=rows,
              summary=summary)


# -- deletes ---------------------------------------------------------------------

def _deletes(b, ch):
    m, tab = b.book.model, b.tab("cost_report")
    for res in ch.deleted_resources:
        b.add("resource.delete", res.id, {}, v=res.v, rows=[(tab, None)],
              summary=[event(tab, None, f"line {res.name!r} (resource {res.id}) deleted")])
    for step, act in ch.deleted_steps:
        b.add("step.delete", step.id, {}, v=step.v, rows=[(tab, None)],
              summary=[event(tab, None, f"step {step.name!r} of activity {act.name!r} "
                                        "deleted")])
    depth = {a.id: 0 for a in m.activities}
    for a in m.activities:
        node = a
        while node.parent_id is not None:
            depth[a.id] += 1
            node = m.activity(node.parent_id)
    for a in sorted(ch.deleted_activities, key=lambda a: -depth[a.id]):
        b.add("activity.delete", a.id, {}, v=a.v, rows=[(tab, None)],
              summary=[event(tab, None, f"activity {a.name!r} (activity {a.id}) deleted, "
                                        "with its child activities, steps and lines")])


def build(book, ch, problems) -> ChangeSet:
    b = _Builder(book, problems)
    _estimate(b, ch)
    _items(b, ch)
    _quantities(b, ch)
    _activities(b, ch)
    _steps(b, ch)
    _resources(b, ch)
    _crews(b, ch)
    _deletes(b, ch)
    for line in ch.ignored:
        b.notes.append(event(b.tab(line.sheet), line.row, "this row was ignored -- it has "
                             "no kind; add bid items in BidSheet.ai"))
    cs = ChangeSet(estimate_id=book.model.estimate.id, estimate_v=book.model.estimate.v)
    b.finish(cs)
    return cs
