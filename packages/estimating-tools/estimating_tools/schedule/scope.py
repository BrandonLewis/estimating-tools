"""Sub-scope schedule filter (R8) — a sub's slice of the GC's full schedule.

A sub bidding a GC's project receives the FULL schedule (MSPDI/XER) and needs
just their scope — with the logic ties to everyone else's work preserved,
because a missed external predecessor misrepresents true float and prices the
wrong general conditions. Port of the Work tools' per-bid filters
(`mspdi_to_xlsx.py` resource filter, `xer_to_xlsx.py` activity-code filter)
onto the format-agnostic CanonicalSchedule: match on the task-level
`resources` / `activity_codes` lists the importers now carry, keep ancestor
summaries by dotted-WBS prefix, and split each kept task's predecessors into
internal (stay in `dependencies`) vs external (move to
`external_dependencies` — the float/GC-delay exposure, never dropped).

`write_task_table` emits the Work tools' 9-column Task Table xlsx for human
review, byte-deterministic (double-build equal).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from bimforge.bim.schedule_model import CanonicalSchedule, Dependency


@dataclass
class ScopeReport:
    resolved: str            # the key actually filtered on (human display)
    matched: int             # non-summary tasks in scope
    summaries_kept: int      # ancestor summary rows preserved
    internal_preds: int      # predecessors kept in `dependencies`
    external_preds: int      # moved to `external_dependencies`
    dropped_tasks: int       # everything else (nothing silently vanishes)


# ---------------------------------------------------------------------------
# listing (the --list-resources / --list-codes surfaces)
# ---------------------------------------------------------------------------

def list_resources(sched: CanonicalSchedule) -> list[tuple[str, int]]:
    """Assigned resource names with task counts, sorted by name."""
    return _counts(sched, "resources")


def list_activity_codes(sched: CanonicalSchedule) -> list[tuple[str, int]]:
    """Activity-code displays ("<type>: <name>") with counts, sorted."""
    return _counts(sched, "activity_codes")


def _counts(sched: CanonicalSchedule, attr: str) -> list[tuple[str, int]]:
    # leaves only, so the listing counts exactly what the filter can match
    # (a resource carried on a summary row would otherwise list but never
    # match anything).
    summaries = sched.summary_ids()
    counts: dict[str, int] = {}
    for t in sched.tasks:
        if t.id in summaries:
            continue
        for key in getattr(t, attr):
            counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items())


# ---------------------------------------------------------------------------
# the filter
# ---------------------------------------------------------------------------

def filter_to_scope(sched: CanonicalSchedule, *,
                    resource: str | None = None,
                    activity_code: str | None = None,
                    ) -> tuple[CanonicalSchedule, ScopeReport]:
    """Filter to the tasks matching ONE selector; never mutates the input.

    Both selectors are case-insensitive substrings against the task-level
    lists (the Work UX). A `resource` needle may span multiple resource
    NAMES ("crew" unions "Pile Crew" + "Concrete Crew" — how "the org"
    matches its several crews); an `activity_code` needle must resolve to
    exactly ONE distinct code display, else it would silently union two
    scopes — ambiguity raises listing the candidates. Zero matches raises
    naming the needle (never an empty schedule).

    Matched = non-summary tasks (per `summary_ids()`) whose list matches;
    every dotted-WBS ancestor summary of a matched task is kept; document
    order preserved. Each kept task's predecessors are split: those whose
    predecessor is also kept stay in `dependencies`, the rest move to
    `external_dependencies` (same Dependency shape).
    """
    if (resource is None) == (activity_code is None):
        raise ValueError(
            "exactly one of resource / activity_code must be given")

    summaries = sched.summary_ids()
    leaves = [t for t in sched.tasks if t.id not in summaries]

    if activity_code is not None:
        needle = activity_code.lower()
        displays = list(dict.fromkeys(  # order-preserving distinct
            c for t in leaves for c in t.activity_codes))
        hits = [d for d in displays if needle in d.lower()]
        if not hits:
            raise ValueError(
                f"no activity code matches {activity_code!r} "
                f"(try --list-codes)")
        if len(hits) > 1:
            raise ValueError(
                f"activity code {activity_code!r} matches "
                f"{len(hits)} codes: " + "; ".join(hits) +
                " — be more specific")
        target = hits[0]
        matched = [t for t in leaves if target in t.activity_codes]
        resolved = f"activity code {target!r}"
    else:
        needle = resource.lower()
        matched = [t for t in leaves
                   if any(needle in r.lower() for r in t.resources)]
        if not matched:
            raise ValueError(
                f"no tasks have a resource matching {resource!r} "
                f"(try --list-resources)")
        resolved = f"resource ~ {resource!r}"

    # ancestor summaries via dotted-WBS prefix (the plugin-native form of
    # the Work outline stack / pruned WBS tree)
    ancestor_wbs: set[str] = set()
    for t in matched:
        parts = t.wbs.split(".") if t.wbs else []
        for i in range(1, len(parts)):
            ancestor_wbs.add(".".join(parts[:i]))
    matched_ids = {t.id for t in matched}
    kept_summaries = {t.id for t in sched.tasks
                      if t.id in summaries and t.wbs in ancestor_wbs}
    kept_ids = matched_ids | kept_summaries

    tasks = []
    n_int = n_ext = 0
    for t in sched.tasks:
        if t.id not in kept_ids:
            continue
        internal = [dataclasses.replace(d) for d in t.dependencies
                    if d.predecessor in kept_ids]
        external = [dataclasses.replace(d) for d in t.dependencies
                    if d.predecessor not in kept_ids]
        # an input that was ALREADY filtered carries external deps of its
        # own — re-filtering must keep them (they are the GC ties this
        # module exists to preserve), not rebuild the list from scratch.
        # De-dupe on (predecessor, type, lag): a hand-merged input carrying
        # the same tie in BOTH lists must not inflate the report or the
        # External Preds column. Order preserved, existing-first.
        merged, seen = [], set()
        for d in ([dataclasses.replace(x)
                   for x in t.external_dependencies] + external):
            key = (d.predecessor, d.type, d.lag_days)
            if key not in seen:
                seen.add(key)
                merged.append(d)
        external = merged
        # count every moved/kept dep, summaries included, so the report
        # and the data can never disagree.
        n_int += len(internal)
        n_ext += len(external)
        tasks.append(dataclasses.replace(
            t, dependencies=internal, external_dependencies=external,
            bid_item_codes=list(t.bid_item_codes),
            resources=list(t.resources),
            activity_codes=list(t.activity_codes)))

    filtered = CanonicalSchedule(
        name=sched.name, start_date=sched.start_date,
        work_weekdays=list(sched.work_weekdays),
        holidays=list(sched.holidays), tasks=tasks,
        # the named calendars the kept tasks still work to (#335)
        calendars={k: dataclasses.replace(
                       c, work_weekdays=list(c.work_weekdays),
                       holidays=list(c.holidays),
                       blackouts=[dict(b) for b in c.blackouts])
                   for k, c in sched.calendars.items()
                   if any(t.calendar == k for t in tasks)})
    report = ScopeReport(
        resolved=resolved, matched=len(matched),
        summaries_kept=len(kept_summaries),
        internal_preds=n_int, external_preds=n_ext,
        dropped_tasks=len(sched.tasks) - len(tasks))
    return filtered, report


# ---------------------------------------------------------------------------
# Task Table xlsx — the Work tools' 9-column human-review artifact
# ---------------------------------------------------------------------------

def _pred_str(dep: Dependency) -> str:
    """`<pred id><SS|FF|SF suffix if not FS><+Nd lag>` (Work rendering)."""
    s = dep.predecessor
    if dep.type != "FS":
        s += dep.type
    if dep.lag_days:
        s += f"{'+' if dep.lag_days > 0 else ''}{dep.lag_days:g}d"
    return s


def write_task_table(sched: CanonicalSchedule, path: str) -> str:
    """Write the 9-column Task Table workbook; byte-deterministic."""
    from openpyxl import Workbook

    from estimating_tools.xlsx_determinism import BUILD_STAMP, normalize_xlsx

    summaries = sched.summary_ids()
    wb = Workbook()
    wb.properties.created = wb.properties.modified = BUILD_STAMP
    ws = wb.active
    ws.title = "Task Table"
    ws.append(["ID", "Outline Level", "Task Name", "Type", "Duration",
               "Start", "Finish", "Predecessors", "External Preds"])
    for t in sched.tasks:
        level = len(t.wbs.split(".")) if t.wbs else 1
        typ = ("Summary" if t.id in summaries
               else "Milestone" if t.is_milestone else "Task")
        dur = (f"{t.duration_days:g} days"
               if t.duration_days is not None else None)
        ws.append([t.id, level, "    " * (level - 1) + t.name, typ, dur,
                   t.start, t.finish,
                   ",".join(_pred_str(d) for d in t.dependencies) or None,
                   ",".join(_pred_str(d)
                            for d in t.external_dependencies) or None])
    wb.save(path)
    normalize_xlsx(path)  # pin docProps + zip-member timestamps
    return path
