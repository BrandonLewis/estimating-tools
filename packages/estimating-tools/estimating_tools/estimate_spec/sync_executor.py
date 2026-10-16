"""BidSheet.ai sync executor.

`run_sync(plan, edited_spec, client) -> ExecReport` walks a SyncPlan (from
`estimate_spec.sync.plan_sync`) in fixed order (rates -> crews -> items),
invokes the caller-supplied `client` callables (MCP tools bound by the
bm-sync skill), applies `estimate_item_id` writebacks to `edited_spec`, and
returns a per-op ExecReport. Pure w.r.t. externals: all I/O goes through
`client`. Best-effort per op — client-call failures are report rows, never aborts;
unknown op kinds are structural plan bugs and raise ValueError instead.

The client contract is LOGICAL (keys are operation names, not 1:1 MCP tool
names); it is documented in
`docs/superpowers/specs/2026-07-10-bm-sync-executor-design.md` (extended by
`docs/superpowers/specs/2026-07-11-bm-sync-extension-design.md` — item
metadata legs + description/uom pushes), and the verified mapping to the
live BM MCP surface lives in
`plugins/estimating-core/skills/bm-sync/SKILL.md`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from estimating_tools.estimate_spec._shared import _is_valid_id
from estimating_tools.estimate_spec.sync import SyncPlan
from estimating_tools.artifacts import format_money, md_table


@dataclass
class CrewMemberDelta:
    """Member-level diff for a crew update, matched by `trade`."""
    add: list[dict] = field(default_factory=list)     # {trade, count}
    remove: list[dict] = field(default_factory=list)  # {trade, count}
    update: list[dict] = field(default_factory=list)  # {trade, old_count, new_count}


def diff_crew_members(base_members: list[dict], edited_members: list[dict]) -> CrewMemberDelta:
    """Diff two member lists by `trade`.

    - trade only in edited -> add
    - trade only in base -> remove
    - trade in both with differing count -> update
    Preserves edited-side order for add/update, base-side order for remove.

    Assumes trades are unique within each list (the estimate-spec schema's
    crew members are keyed by trade).
    """
    base_by_trade = {m["trade"]: m for m in base_members}
    edited_trades = {m["trade"] for m in edited_members}
    delta = CrewMemberDelta()
    for m in edited_members:
        base = base_by_trade.get(m["trade"])
        if base is None:
            delta.add.append({"trade": m["trade"], "count": m["count"]})
        elif base["count"] != m["count"]:
            delta.update.append({"trade": m["trade"],
                                 "old_count": base["count"],
                                 "new_count": m["count"]})
    for m in base_members:
        if m["trade"] not in edited_trades:
            delta.remove.append({"trade": m["trade"], "count": m["count"]})
    return delta


def apply_item_writeback(edited_spec: dict, item_no: str, estimate_item_id: int) -> None:
    """Set `estimate_item_id` on the first item whose item_no matches and
    whose current estimate_item_id is missing/invalid. Mutates edited_spec.

    Raises ValueError if no such item exists: a writeback with no home means
    the spec and the plan drifted, and silently dropping the pk would orphan
    the BM record. Items already carrying a valid id are never overwritten.
    """
    for it in edited_spec.get("items", []):
        if it.get("item_no") == item_no and not _is_valid_id(it.get("estimate_item_id")):
            it["estimate_item_id"] = estimate_item_id
            return
    raise ValueError(
        f"no un-synced item with item_no {item_no!r} to receive "
        f"estimate_item_id {estimate_item_id}; re-fetch and reconcile"
    )


@dataclass
class ExecReport:
    """Per-op execution results. Every row carries status: "ok"|"error";
    error rows also carry a `detail` message.
    """
    rate_creates: list[dict] = field(default_factory=list)   # {trade, rate, status, detail?}
    crew_creates: list[dict] = field(default_factory=list)   # {crew_id, status, detail?}
    crew_updates: list[dict] = field(default_factory=list)   # {crew_id, status, detail?}
    item_creates: list[dict] = field(default_factory=list)   # {item_no, estimate_item_id?, status, detail?}
    item_updates: list[dict] = field(default_factory=list)   # {estimate_item_id, changed_fields, status, detail?}
    item_deletes: list[dict] = field(default_factory=list)   # {estimate_item_id, item_no, status, detail?}


def _detail_cell(row: dict) -> str:
    """Single-line `detail` for a table cell (md_table rows must not contain
    newlines); "-" when absent."""
    return (row.get("detail") or "-").replace("\n", " ")


def _summary_line(report: ExecReport) -> str:
    """`N ok · M error(s).`"""
    all_rows = (report.rate_creates + report.crew_creates + report.crew_updates
                + report.item_creates + report.item_updates + report.item_deletes)
    n_ok = sum(1 for r in all_rows if r["status"] == "ok")
    n_err = sum(1 for r in all_rows if r["status"] == "error")
    return f"{n_ok} ok · {n_err} error{'s' if n_err != 1 else ''}."


def render_exec_report(report: ExecReport) -> str:
    """Markdown summary of what actually happened. Heading + ok/error counts
    + one section per non-empty op list (empty lists render no section —
    unlike render_sync_plan, which shows all sections of the *proposed* plan,
    the results artifact only reports work that was attempted).
    No trailing newline."""
    parts = ["# Sync results", _summary_line(report)]
    if report.rate_creates:
        rows = [[r["trade"], format_money(r["rate"]), r["status"], _detail_cell(r)]
                for r in report.rate_creates]
        parts.append("## Rates\n\n" + md_table(["trade", "rate", "status", "detail"], rows))
    if report.crew_creates:
        rows = [[r["crew_id"], r["status"], _detail_cell(r)]
                for r in report.crew_creates]
        parts.append("## Crew creates\n\n" + md_table(["crew_id", "status", "detail"], rows))
    if report.crew_updates:
        rows = [[r["crew_id"], r["status"], _detail_cell(r)]
                for r in report.crew_updates]
        parts.append("## Crew updates\n\n" + md_table(["crew_id", "status", "detail"], rows))
    if report.item_creates:
        rows = [[r["item_no"], str(r.get("estimate_item_id", "-")),
                 r["status"], _detail_cell(r)]
                for r in report.item_creates]
        parts.append("## Item creates\n\n" + md_table(
            ["item_no", "estimate_item_id", "status", "detail"], rows))
    if report.item_updates:
        rows = [[str(r["estimate_item_id"]), "; ".join(r["changed_fields"]),
                 r["status"], _detail_cell(r)]
                for r in report.item_updates]
        parts.append("## Item updates\n\n" + md_table(
            ["estimate_item_id", "changed", "status", "detail"], rows))
    if report.item_deletes:
        rows = [[str(r["estimate_item_id"]), r["item_no"],
                 r["status"], _detail_cell(r)]
                for r in report.item_deletes]
        parts.append("## Item deletes\n\n" + md_table(
            ["estimate_item_id", "item_no", "status", "detail"], rows))
    return "\n\n".join(parts)


def _exec_rates(plan: SyncPlan, client: dict, report: ExecReport) -> None:
    for op in plan.rate_ops:
        if op.kind != "create":
            # Structural bug in plan construction (RateOp is create-only).
            raise ValueError(f"unknown RateOp kind: {op.kind!r}")
        row = {"trade": op.trade, "rate": op.rate}
        try:
            existing = client["list_labor_rates"](classification=op.trade,
                                                  is_current=True)
            if existing:
                row["status"] = "ok"
                row["detail"] = "already exists"
            else:
                client["create_labor_rate"](classification=op.trade,
                                            burdened_hourly_rate=op.rate)
                row["status"] = "ok"
        except Exception as exc:
            row["status"] = "error"
            row["detail"] = str(exc)
        report.rate_creates.append(row)


def _sync_crew_members(client: dict, assembly_id: int, edited_members: list[dict]) -> None:
    """Reconcile BM components against the edited member list via
    diff_crew_members. Raises on the first failing call - the enclosing
    _exec_crews try records it; a re-run picks up where this left off
    because the delta is recomputed from live components.
    """
    existing = client["list_components"](assembly_id=assembly_id)
    base_members = [{"trade": c["trade"], "count": c["count"]} for c in existing]
    ids_by_trade = {c["trade"]: c["component_id"] for c in existing}
    if len(ids_by_trade) != len(existing):
        # Live BM data can contain manually duplicated trades; a last-wins
        # reconcile would silently update/delete the wrong component.
        raise ValueError(
            f"duplicate trades in BM components for assembly {assembly_id}; "
            "reconcile in BM before syncing"
        )
    delta = diff_crew_members(base_members, edited_members)
    for m in delta.add:
        client["create_component"](assembly_id=assembly_id,
                                   trade=m["trade"], count=m["count"])
    for m in delta.update:
        client["update_component"](component_id=ids_by_trade[m["trade"]],
                                   count=m["new_count"])
    for m in delta.remove:
        client["delete_component"](component_id=ids_by_trade[m["trade"]])


def _exec_crews(plan: SyncPlan, client: dict, report: ExecReport) -> None:
    for op in plan.crew_ops:
        if op.kind not in ("create", "update"):
            # Structural bug in plan construction — loud beats silently
            # reconciling members under the wrong intent.
            raise ValueError(f"unknown CrewOp kind: {op.kind!r}")
        rows = report.crew_creates if op.kind == "create" else report.crew_updates
        row = {"crew_id": op.crew_id}
        try:
            existing = client["list_assemblies"](assembly_type="CREW",
                                                 name=op.crew_id)
            if len(existing) > 1:
                # Reconciling members against an arbitrary duplicate could
                # rewrite the wrong assembly.
                raise LookupError(
                    f"multiple assemblies named {op.crew_id!r} in BM; "
                    "reconcile before syncing"
                )
            if op.kind == "create" and not existing:
                assembly_id = client["create_assembly"](
                    assembly_type="CREW", name=op.crew_id,
                    description=op.description)
                member_errors = []
                for m in op.members:
                    try:
                        client["create_component"](assembly_id=assembly_id,
                                                   trade=m["trade"],
                                                   count=m["count"])
                    except Exception as exc:
                        member_errors.append(f"{m['trade']}: {exc}")
                if member_errors:
                    row["status"] = "error"
                    row["detail"] = "; ".join(member_errors)
                else:
                    row["status"] = "ok"
            else:
                # update op, or a create whose assembly already exists
                # (half-finished prior run): reconcile members via delta.
                if not existing:
                    raise LookupError(f"assembly {op.crew_id!r} not found in BM")
                assembly_id = existing[0]["assembly_id"]
                _sync_crew_members(client, assembly_id, op.members)
                row["status"] = "ok"
                if op.kind == "create":
                    row["detail"] = "already existed; members reconciled"
        except Exception as exc:
            row["status"] = "error"
            row["detail"] = str(exc)
        rows.append(row)


def _is_formula(value: object) -> bool:
    return isinstance(value, str) and value.startswith("=")


_FORMULA_DETAIL = "formula qty; resolve before sync"

# ItemOp field name -> update_bid_item kwarg
_BID_FIELD_KWARGS = {"item_no": "item_number",
                     "description": "description",
                     "uom": "unit",
                     "wbs": "wbs",
                     "cost_code": "cost_code"}


def _make_crew_resolver(client: dict) -> Callable[[str], int]:
    """Per-run cached `crew_id` (crew name = BM Assembly.name) -> assembly pk.

    "" resolves to 0 (BM's clear-the-assignment sentinel) without a client
    call. Raises LookupError on no match or multiple matches — same guards
    as _exec_crews. Cache is scoped to one run_sync call: the same plan's
    crew ops ran moments earlier, so staleness within a run is not a
    concern, and N items sharing a crew make one lookup. Failed resolutions
    are not cached — a transient error on one item must not poison later
    items — so they retry per item.
    """
    cache: dict[str, int] = {"": 0}

    def resolve(crew_id: str) -> int:
        if crew_id not in cache:
            matches = client["list_assemblies"](assembly_type="CREW",
                                                name=crew_id)
            if not matches:
                raise LookupError(f"crew {crew_id!r} not found in BM")
            if len(matches) > 1:
                raise LookupError(
                    f"multiple assemblies named {crew_id!r} in BM; "
                    "reconcile before syncing")
            cache[crew_id] = matches[0]["assembly_id"]
        return cache[crew_id]

    return resolve


def _exec_items(plan: SyncPlan, client: dict, edited_spec: dict,
                report: ExecReport) -> None:
    resolve_crew = _make_crew_resolver(client)
    for op in plan.item_ops:
        if op.kind == "create":
            row = {"item_no": op.item_no}
            try:
                if _is_formula(op.qty):
                    row["status"] = "error"
                    row["detail"] = _FORMULA_DETAIL
                else:
                    # Crew resolution failure fails the WHOLE create (no BM
                    # write): a partial create-without-crew would writeback
                    # an id whose crew leg the next plan_sync can't re-emit.
                    crew_assembly_id = resolve_crew(op.crew_id)
                    pk = client["create_estimate_item"](
                        item_number=op.item_no, description=op.description,
                        estimated_quantity=op.qty, unit=op.uom,
                        wbs=op.wbs, cost_code=op.cost_code,
                        crew_assembly_id=crew_assembly_id)
                    row["estimate_item_id"] = pk
                    apply_item_writeback(edited_spec, op.item_no, pk)
                    row["status"] = "ok"
            except Exception as exc:
                row["status"] = "error"
                row["detail"] = str(exc)
            report.item_creates.append(row)
        elif op.kind == "update":
            row = {"estimate_item_id": op.estimate_item_id,
                   "changed_fields": list(op.changed_fields)}
            errors = []
            bid_kwargs = {_BID_FIELD_KWARGS[f]: getattr(op, f)
                          for f in op.changed_fields if f in _BID_FIELD_KWARGS}
            if "crew_id" in op.changed_fields:
                try:
                    bid_kwargs["crew_assembly_id"] = resolve_crew(op.crew_id)
                except Exception as exc:
                    # Crew leg fails alone; the other changed bid fields
                    # (and qty) still push.
                    errors.append(f"crew_id: {exc}")
            unknown = [f for f in op.changed_fields
                       if f not in _BID_FIELD_KWARGS
                       and f not in ("qty", "crew_id")]
            if unknown:
                errors.append(f"unsupported changed_fields: {', '.join(unknown)}")
            if bid_kwargs:
                try:
                    client["update_bid_item"](
                        estimate_item_id=op.estimate_item_id, **bid_kwargs)
                except Exception as exc:
                    errors.append(f"update_bid_item: {exc}")
            if "qty" in op.changed_fields:
                if _is_formula(op.qty):
                    errors.append(_FORMULA_DETAIL)
                else:
                    try:
                        client["update_estimate_item"](
                            estimate_item_id=op.estimate_item_id,
                            estimated_quantity=op.qty)
                    except Exception as exc:
                        errors.append(f"update_estimate_item: {exc}")
            if errors:
                row["status"] = "error"
                row["detail"] = "; ".join(errors)
            else:
                row["status"] = "ok"
                # Anchor recovered by item_no this run: persist it to edited_spec
                # so later syncs match by id, not by re-running the heuristic
                # (which could degrade to warn-and-skip on a later snapshot that
                # also lacks anchors). Best-effort — a spec already carrying the
                # id has no un-synced item and apply_item_writeback would raise. (#250)
                if getattr(op, "recovered_anchor", False):
                    try:
                        apply_item_writeback(edited_spec, op.item_no,
                                             op.estimate_item_id)
                    except ValueError:
                        pass
            report.item_updates.append(row)
        elif op.kind == "delete":
            row = {"estimate_item_id": op.estimate_item_id,
                   "item_no": op.item_no}
            try:
                client["delete_estimate_item"](
                    estimate_item_id=op.estimate_item_id)
                row["status"] = "ok"
            except Exception as exc:
                row["status"] = "error"
                row["detail"] = str(exc)
            report.item_deletes.append(row)
        else:
            # An unknown kind is a structural bug in plan construction, not
            # an MCP failure — loud beats a destructive default.
            raise ValueError(f"unknown ItemOp kind: {op.kind!r}")


def run_sync(plan: SyncPlan, edited_spec: dict, client: dict) -> ExecReport:
    """Walk the plan in fixed order (rates -> crews -> items), invoke
    client[tool](**kwargs) per op, apply item writebacks to edited_spec,
    and return an ExecReport.

    Best-effort per op: an exception from a client callable (including a
    KeyError for a missing tool binding) is recorded as status="error" with
    str(exc) as detail; execution continues with the next op.

    Structural plan bugs are NOT absorbed: an unknown op kind raises
    ValueError before any client call for that op.
    """
    report = ExecReport()
    _exec_rates(plan, client, report)
    _exec_crews(plan, client, report)
    _exec_items(plan, client, edited_spec, report)
    return report
