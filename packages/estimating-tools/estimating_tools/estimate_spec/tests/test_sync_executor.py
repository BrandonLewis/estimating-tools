"""Tests for the BidSheet.ai sync executor (estimate_spec/sync_executor.py).

`run_sync(plan, edited_spec, client)` walks a SyncPlan, invokes the caller-
supplied client callables, applies estimate_item_id writebacks, and returns
an ExecReport. Pure w.r.t. externals; all I/O goes through `client`.
Design in docs/superpowers/specs/2026-07-10-bm-sync-executor-design.md.
"""
from __future__ import annotations

import pytest

from estimating_tools.estimate_spec.sync import (
    CrewOp,
    ItemOp,
    RateOp,
    SyncPlan,
    plan_sync,
)
from estimating_tools.estimate_spec.sync_executor import (
    CrewMemberDelta,
    ExecReport,
    apply_item_writeback,
    diff_crew_members,
    render_exec_report,
    run_sync,
)


# ---------- diff_crew_members ----------

def test_diff_crew_members_empty_base_all_adds():
    delta = diff_crew_members([], [{"trade": "FORE", "count": 1},
                                   {"trade": "LAB", "count": 3}])
    assert delta.add == [{"trade": "FORE", "count": 1},
                         {"trade": "LAB", "count": 3}]
    assert delta.remove == []
    assert delta.update == []


def test_diff_crew_members_empty_edited_all_removes():
    delta = diff_crew_members([{"trade": "FORE", "count": 1},
                               {"trade": "LAB", "count": 3}], [])
    assert delta.add == []
    assert delta.remove == [{"trade": "FORE", "count": 1},
                            {"trade": "LAB", "count": 3}]
    assert delta.update == []


def test_diff_crew_members_count_change_single_update():
    delta = diff_crew_members([{"trade": "LAB", "count": 3}],
                              [{"trade": "LAB", "count": 4}])
    assert delta.add == []
    assert delta.remove == []
    assert delta.update == [{"trade": "LAB", "old_count": 3, "new_count": 4}]


def test_diff_crew_members_mixed_add_remove_update():
    base = [{"trade": "FORE", "count": 1},
            {"trade": "LAB", "count": 3}]
    edited = [{"trade": "LAB", "count": 2},
              {"trade": "OPER", "count": 1}]
    delta = diff_crew_members(base, edited)
    assert delta.add == [{"trade": "OPER", "count": 1}]
    assert delta.remove == [{"trade": "FORE", "count": 1}]
    assert delta.update == [{"trade": "LAB", "old_count": 3, "new_count": 2}]


def test_diff_crew_members_identical_lists_empty_delta():
    members = [{"trade": "FORE", "count": 1}, {"trade": "LAB", "count": 3}]
    delta = diff_crew_members(members, list(members))
    assert delta == CrewMemberDelta()


def test_diff_crew_members_multi_entry_ordering():
    """update entries follow edited-side order; remove entries base-side order."""
    base = [{"trade": "A", "count": 1}, {"trade": "B", "count": 1},
            {"trade": "C", "count": 1}, {"trade": "D", "count": 1}]
    edited = [{"trade": "C", "count": 9}, {"trade": "A", "count": 9}]
    delta = diff_crew_members(base, edited)
    assert [m["trade"] for m in delta.update] == ["C", "A"]
    assert [m["trade"] for m in delta.remove] == ["B", "D"]


# ---------- apply_item_writeback ----------

def test_apply_item_writeback_sets_id_on_unsynced_match():
    spec = {"items": [{"item_no": "Item # 1", "description": "Mob"}]}
    apply_item_writeback(spec, "Item # 1", 100)
    assert spec["items"][0]["estimate_item_id"] == 100


def test_apply_item_writeback_no_match_raises():
    spec = {"items": [{"item_no": "Item # 1", "description": "Mob"}]}
    with pytest.raises(ValueError):
        apply_item_writeback(spec, "Item # 99", 100)


def test_apply_item_writeback_skips_already_synced_item():
    """An item that already carries a valid id is not overwritten; if it's
    the only candidate, the writeback has no home -> ValueError."""
    spec = {"items": [{"item_no": "Item # 1", "estimate_item_id": 50}]}
    with pytest.raises(ValueError):
        apply_item_writeback(spec, "Item # 1", 100)
    assert spec["items"][0]["estimate_item_id"] == 50


def test_apply_item_writeback_first_unsynced_duplicate_wins():
    spec = {"items": [
        {"item_no": "Item # 1", "estimate_item_id": 50},
        {"item_no": "Item # 1"},
        {"item_no": "Item # 1"},
    ]}
    apply_item_writeback(spec, "Item # 1", 100)
    assert spec["items"][1]["estimate_item_id"] == 100
    assert "estimate_item_id" not in spec["items"][2]


# ---------- ExecReport / render_exec_report ----------

def test_exec_report_defaults_are_empty():
    report = ExecReport()
    assert report.rate_creates == []
    assert report.crew_creates == []
    assert report.crew_updates == []
    assert report.item_creates == []
    assert report.item_updates == []
    assert report.item_deletes == []


def test_render_exec_report_empty():
    out = render_exec_report(ExecReport())
    assert out == "# Sync results\n\n0 ok · 0 errors."
    assert not out.endswith("\n")


def test_render_exec_report_mixed_sections_and_error_detail():
    report = ExecReport(
        rate_creates=[{"trade": "MASON", "rate": 105.0, "status": "ok"}],
        crew_creates=[{"crew_id": "crew_ne_5", "status": "ok"}],
        item_creates=[
            {"item_no": "Item # 99", "estimate_item_id": 100, "status": "ok"},
            {"item_no": "Item # 77", "status": "error",
             "detail": "formula qty; resolve before sync"},
        ],
        item_deletes=[{"estimate_item_id": 200, "item_no": "Item # 1",
                       "status": "ok"}],
    )
    out = render_exec_report(report)
    assert out.startswith("# Sync results\n\n4 ok · 1 error.")
    assert "## Rates" in out
    assert "| MASON | 105.00 | ok | - |" in out
    assert "## Crew creates" in out
    assert "## Crew updates" not in out       # empty list -> no section
    assert "## Item creates" in out
    assert "| Item # 99 | 100 | ok | - |" in out
    assert "| Item # 77 | - | error | formula qty; resolve before sync |" in out
    assert "## Item updates" not in out
    assert "## Item deletes" in out
    assert "| 200 | Item # 1 | ok | - |" in out
    assert not out.endswith("\n")


def test_render_exec_report_item_updates_show_changed_fields():
    report = ExecReport(
        item_updates=[{"estimate_item_id": 100,
                       "changed_fields": ["item_no", "qty"], "status": "ok"}],
    )
    out = render_exec_report(report)
    assert "## Item updates" in out
    assert "| 100 | item_no; qty | ok | - |" in out


def test_render_exec_report_multiline_detail_stays_one_row():
    report = ExecReport(crew_creates=[
        {"crew_id": "crew_x", "status": "error", "detail": "line1\nline2"}])
    out = render_exec_report(report)
    assert "| crew_x | error | line1 line2 |" in out


# ---------- run_sync (FakeClient) ----------

_CLIENT_TOOLS = (
    "list_labor_rates", "create_labor_rate",
    "list_equipment_rates", "create_equipment_rate",
    "list_assemblies", "create_assembly", "list_components",
    "create_component", "update_component", "delete_component",
    "create_estimate_item", "update_bid_item", "update_estimate_item",
    "delete_estimate_item",
)

_CLIENT_DEFAULTS = {
    "list_labor_rates": [],
    "list_equipment_rates": [],
    "list_assemblies": [],
    "list_components": [],
    "create_assembly": 1,
    "create_estimate_item": 100,
}


class FakeClient(dict):
    """A client dict whose callables record every call as (tool, kwargs).

    `responses` overrides a tool's return value; a callable response is
    invoked with the call kwargs (use to raise or to return sequential pks).
    """
    def __init__(self, responses=None):
        super().__init__()
        self.calls = []
        self._responses = responses or {}
        for tool in _CLIENT_TOOLS:
            self[tool] = self._make(tool)

    def _make(self, tool):
        def call(**kwargs):
            self.calls.append((tool, kwargs))
            resp = self._responses.get(tool, _CLIENT_DEFAULTS.get(tool))
            return resp(**kwargs) if callable(resp) else resp
        return call

    def tools_called(self):
        return [tool for tool, _ in self.calls]


def test_run_sync_empty_plan_no_calls_empty_report():
    client = FakeClient()
    report = run_sync(SyncPlan(), {"items": []}, client)
    assert report == ExecReport()
    assert client.calls == []


def test_run_sync_rate_already_exists_skips_create():
    client = FakeClient(responses={"list_labor_rates": [{"classification": "MASON"}]})
    plan = SyncPlan(rate_ops=[RateOp(kind="create", trade="MASON", rate=105.0)])
    report = run_sync(plan, {"items": []}, client)
    assert client.tools_called() == ["list_labor_rates"]
    assert client.calls[0][1] == {"classification": "MASON", "is_current": True}
    assert report.rate_creates == [
        {"trade": "MASON", "rate": 105.0, "status": "ok", "detail": "already exists"}]


def test_run_sync_rate_create_calls_create_labor_rate():
    client = FakeClient()
    plan = SyncPlan(rate_ops=[RateOp(kind="create", trade="MASON", rate=105.0)])
    report = run_sync(plan, {"items": []}, client)
    assert client.tools_called() == ["list_labor_rates", "create_labor_rate"]
    assert client.calls[1][1] == {"classification": "MASON", "base_hourly_rate": 105.0,
                                  "burden_percentage": 0.0, "fringe_hourly": 0.0,
                                  "rate_basis": "applied_bid"}
    assert report.rate_creates == [{"trade": "MASON", "rate": 105.0, "status": "ok"}]


def test_run_sync_labor_breakdown_is_sent_as_bidmanager_stores_it():
    client = FakeClient()
    plan = SyncPlan(rate_ops=[RateOp(kind="create", trade="Pipelayer", rate=81.89,
                                     base=48.10, burden_pct=0.32, fringe=18.40)])
    run_sync(plan, {"items": []}, client)
    assert client.calls[1] == ("create_labor_rate", {
        "classification": "Pipelayer", "base_hourly_rate": 48.10,
        "burden_percentage": 32.0, "fringe_hourly": 18.40, "rate_basis": "applied_bid"})


def test_run_sync_breakdown_without_fringe_sends_zero_fringe():
    client = FakeClient()
    plan = SyncPlan(rate_ops=[RateOp(kind="create", trade="Laborer", rate=80.52,
                                     base=61.0, burden_pct=0.32)])
    run_sync(plan, {"items": []}, client)
    assert client.calls[1][1]["fringe_hourly"] == 0.0
    assert client.calls[1][1]["burden_percentage"] == 32.0


@pytest.mark.parametrize("op", [
    # base*(1+burden)+fringe = 60.00, but the approved rate is 100.00
    RateOp(kind="create", trade="Mason", rate=100.0, base=50.0, burden_pct=0.2),
    # a burden or fringe without a base cannot be sent as a breakdown at all
    RateOp(kind="create", trade="Mason", rate=100.0, burden_pct=0.2),
    RateOp(kind="create", trade="Mason", rate=100.0, fringe=5.0),
])
def test_run_sync_refuses_a_breakdown_that_does_not_reproduce_the_rate(op):
    """bm-sync loads YAML without validate_cross_references, so the executor
    must not push a breakdown BidSheet.ai would turn into a different rate
    than the one the user approved."""
    client = FakeClient()
    report = run_sync(SyncPlan(rate_ops=[op]), {"items": []}, client)
    assert "create_labor_rate" not in client.tools_called()
    assert report.rate_creates[0]["status"] == "error"
    assert "100.00" in report.rate_creates[0]["detail"]


def test_run_sync_accepts_a_breakdown_within_a_cent():
    client = FakeClient()
    op = RateOp(kind="create", trade="Pipelayer", rate=81.89,
                base=48.10, burden_pct=0.32, fringe=18.40)            # 81.892
    report = run_sync(SyncPlan(rate_ops=[op]), {"items": []}, client)
    assert report.rate_creates[0]["status"] == "ok"
    assert "create_labor_rate" in client.tools_called()


def test_run_sync_burden_pct_to_percent_has_no_float_noise():
    """0.07 * 100 is 7.000000000000001 in raw float arithmetic; the
    round(..., 6) guard in _labor_rate_kwargs must send a clean 7.0."""
    client = FakeClient()
    plan = SyncPlan(rate_ops=[RateOp(kind="create", trade="Laborer", rate=65.27,
                                     base=61.0, burden_pct=0.07)])
    run_sync(plan, {"items": []}, client)
    assert client.calls[1][1]["burden_percentage"] == 7.0


def test_run_sync_rate_create_error_recorded_and_continues():
    def boom(**kwargs):
        raise RuntimeError("BM down")
    client = FakeClient(responses={"create_labor_rate": boom})
    plan = SyncPlan(rate_ops=[RateOp(kind="create", trade="MASON", rate=105.0),
                              RateOp(kind="create", trade="GRChkr", rate=82.0)])
    report = run_sync(plan, {"items": []}, client)
    assert report.rate_creates[0]["status"] == "error"
    assert "BM down" in report.rate_creates[0]["detail"]
    # second op still executed
    assert report.rate_creates[1]["trade"] == "GRChkr"
    assert report.rate_creates[1]["status"] == "error"


def test_run_sync_rate_list_call_error_still_appends_row():
    def boom(**kwargs):
        raise RuntimeError("list failed")
    client = FakeClient(responses={"list_labor_rates": boom})
    plan = SyncPlan(rate_ops=[RateOp(kind="create", trade="MASON", rate=105.0)])
    report = run_sync(plan, {"items": []}, client)
    assert report.rate_creates == [
        {"trade": "MASON", "rate": 105.0, "status": "error", "detail": "list failed"}]


def test_run_sync_rate_unknown_kind_raises():
    client = FakeClient()
    plan = SyncPlan(rate_ops=[RateOp(kind="update", trade="MASON", rate=105.0)])
    with pytest.raises(ValueError):
        run_sync(plan, {"items": []}, client)
    assert client.calls == []


def test_run_sync_rate_unknown_resource_kind_raises_before_any_client_call():
    client = FakeClient()
    plan = SyncPlan(rate_ops=[RateOp(kind="create", trade="MASON", rate=105.0,
                                     resource_kind="material")])
    with pytest.raises(ValueError):
        run_sync(plan, {"items": []}, client)
    assert client.calls == []


def _equipment_op(**kw):
    return RateOp(kind="create", trade="Excavator, 320 class", rate=145.0,
                  resource_kind="equipment", **kw)


def test_run_sync_equipment_rate_is_created_in_the_equipment_library():
    client = FakeClient()
    report = run_sync(SyncPlan(rate_ops=[_equipment_op(includes_operator=True)]),
                      {"items": []}, client)
    assert client.calls == [
        ("list_equipment_rates", {"equipment_type": "Excavator, 320 class", "is_current": True}),
        ("create_equipment_rate", {"equipment_type": "Excavator, 320 class",
                                   "hourly_rate": 145.0, "includes_operator": True}),
    ]
    assert report.rate_creates == [
        {"trade": "Excavator, 320 class", "rate": 145.0, "status": "ok"}]


def test_run_sync_existing_equipment_rate_is_not_recreated():
    client = FakeClient(responses={"list_equipment_rates": [{"equipment_type": "x"}]})
    report = run_sync(SyncPlan(rate_ops=[_equipment_op()]), {"items": []}, client)
    assert client.tools_called() == ["list_equipment_rates"]
    assert report.rate_creates[0]["detail"] == "already exists"


def test_run_sync_equipment_never_touches_the_labor_library():
    client = FakeClient()
    run_sync(SyncPlan(rate_ops=[_equipment_op()]), {"items": []}, client)
    assert not {"list_labor_rates", "create_labor_rate"} & set(client.tools_called())


def test_run_sync_crew_create_no_hit_creates_assembly_and_components():
    client = FakeClient(responses={"create_assembly": 7})
    plan = SyncPlan(crew_ops=[CrewOp(
        kind="create", crew_id="crew_ne_5", description="NE 5-person crew",
        members=[{"trade": "FORE", "count": 1}, {"trade": "LAB", "count": 3}])])
    report = run_sync(plan, {"items": []}, client)
    assert client.tools_called() == [
        "list_assemblies", "create_assembly", "create_component", "create_component"]
    assert client.calls[1][1] == {"assembly_type": "CREW", "name": "crew_ne_5",
                                  "description": "NE 5-person crew"}
    assert client.calls[2][1] == {"assembly_id": 7, "trade": "FORE", "count": 1, "kind": "labor"}
    assert client.calls[3][1] == {"assembly_id": 7, "trade": "LAB", "count": 3, "kind": "labor"}
    assert report.crew_creates == [{"crew_id": "crew_ne_5", "status": "ok"}]


def test_run_sync_crew_create_assembly_error_skips_components():
    def boom(**kwargs):
        raise RuntimeError("no perms")
    client = FakeClient(responses={"create_assembly": boom})
    plan = SyncPlan(crew_ops=[CrewOp(
        kind="create", crew_id="crew_ne_5", description="",
        members=[{"trade": "FORE", "count": 1}])])
    report = run_sync(plan, {"items": []}, client)
    assert "create_component" not in client.tools_called()
    assert report.crew_creates[0]["status"] == "error"
    assert "no perms" in report.crew_creates[0]["detail"]


def test_run_sync_crew_create_component_error_keeps_issuing_members():
    def flaky(**kwargs):
        if kwargs["trade"] == "FORE":
            raise RuntimeError("dup component")
    client = FakeClient(responses={"create_assembly": 7, "create_component": flaky})
    plan = SyncPlan(crew_ops=[CrewOp(
        kind="create", crew_id="crew_ne_5", description="",
        members=[{"trade": "FORE", "count": 1}, {"trade": "LAB", "count": 3}])])
    report = run_sync(plan, {"items": []}, client)
    # both members attempted despite the first failing
    assert client.tools_called().count("create_component") == 2
    assert report.crew_creates[0]["status"] == "error"
    assert "FORE" in report.crew_creates[0]["detail"]


def test_run_sync_crew_create_existing_assembly_falls_through_to_update():
    """Idempotent re-run: a half-finished create finds the assembly and
    reconciles members via the delta path instead of duplicating."""
    client = FakeClient(responses={
        "list_assemblies": [{"assembly_id": 7, "name": "crew_ne_5"}],
        "list_components": [{"component_id": 21, "trade": "FORE", "count": 1}],
    })
    plan = SyncPlan(crew_ops=[CrewOp(
        kind="create", crew_id="crew_ne_5", description="",
        members=[{"trade": "FORE", "count": 1}, {"trade": "LAB", "count": 3}])])
    report = run_sync(plan, {"items": []}, client)
    assert "create_assembly" not in client.tools_called()
    assert client.tools_called() == ["list_assemblies", "list_components",
                                     "create_component"]
    assert client.calls[2][1] == {"assembly_id": 7, "trade": "LAB", "count": 3, "kind": "labor"}
    assert report.crew_creates == [{"crew_id": "crew_ne_5", "status": "ok",
                                    "detail": "already existed; members reconciled"}]


def test_run_sync_crew_unknown_kind_raises():
    client = FakeClient()
    plan = SyncPlan(crew_ops=[CrewOp(
        kind="delete", crew_id="crew_x", description="", members=[])])
    with pytest.raises(ValueError):
        run_sync(plan, {"items": []}, client)
    assert client.calls == []


def test_run_sync_crew_update_duplicate_bm_trades_is_error():
    client = FakeClient(responses={
        "list_assemblies": [{"assembly_id": 7, "name": "crew_x"}],
        "list_components": [
            {"component_id": 21, "trade": "LAB", "count": 2},
            {"component_id": 22, "trade": "LAB", "count": 3},
        ],
    })
    plan = SyncPlan(crew_ops=[CrewOp(
        kind="update", crew_id="crew_x", description="",
        members=[{"trade": "LAB", "count": 4}])])
    report = run_sync(plan, {"items": []}, client)
    assert report.crew_updates[0]["status"] == "error"
    assert "duplicate trades" in report.crew_updates[0]["detail"]
    # no component mutations were attempted
    assert client.tools_called() == ["list_assemblies", "list_components"]


def test_run_sync_crew_ambiguous_assembly_match_is_error():
    client = FakeClient(responses={
        "list_assemblies": [{"assembly_id": 7, "name": "crew_x"},
                            {"assembly_id": 8, "name": "crew_x"}],
    })
    plan = SyncPlan(crew_ops=[CrewOp(
        kind="update", crew_id="crew_x", description="",
        members=[{"trade": "LAB", "count": 2}])])
    report = run_sync(plan, {"items": []}, client)
    assert report.crew_updates[0]["status"] == "error"
    assert "multiple assemblies" in report.crew_updates[0]["detail"]
    assert client.tools_called() == ["list_assemblies"]


def test_run_sync_crew_update_issues_delta_calls():
    client = FakeClient(responses={
        "list_assemblies": [{"assembly_id": 7, "name": "crew_ne_5"}],
        "list_components": [
            {"component_id": 21, "trade": "FORE", "count": 1},
            {"component_id": 22, "trade": "LAB", "count": 3},
        ],
    })
    plan = SyncPlan(crew_ops=[CrewOp(
        kind="update", crew_id="crew_ne_5", description="",
        members=[{"trade": "LAB", "count": 2}, {"trade": "OPER", "count": 1}])])
    report = run_sync(plan, {"items": []}, client)
    assert client.tools_called() == [
        "list_assemblies", "list_components",
        "create_component", "update_component", "delete_component"]
    assert client.calls[2][1] == {"assembly_id": 7, "trade": "OPER", "count": 1, "kind": "labor"}
    assert client.calls[3][1] == {"component_id": 22, "count": 2}
    assert client.calls[4][1] == {"component_id": 21}
    assert report.crew_updates == [{"crew_id": "crew_ne_5", "status": "ok"}]


def test_run_sync_crew_update_missing_assembly_is_error():
    client = FakeClient()   # list_assemblies -> []
    plan = SyncPlan(crew_ops=[CrewOp(
        kind="update", crew_id="crew_gone", description="",
        members=[{"trade": "LAB", "count": 2}])])
    report = run_sync(plan, {"items": []}, client)
    assert report.crew_updates[0]["status"] == "error"
    assert "not found" in report.crew_updates[0]["detail"]
    assert report.crew_creates == []


def test_run_sync_equipment_member_is_created_as_an_equipment_component():
    client = FakeClient(responses={"create_assembly": 7})
    plan = SyncPlan(crew_ops=[CrewOp(
        kind="create", crew_id="pipe", description="",
        members=[{"trade": "Pipelayer", "count": 2},
                 {"trade": "Excavator, 320 class", "count": 1}])])
    spec = {"items": [], "rate_table": [
        {"trade": "Pipelayer", "rate": 81.89},
        {"trade": "Excavator, 320 class", "rate": 145.0, "kind": "equipment"}]}
    run_sync(plan, spec, client)
    creates = [kw for tool, kw in client.calls if tool == "create_component"]
    assert [c["kind"] for c in creates] == ["labor", "equipment"]


def test_run_sync_crew_update_adds_equipment_members_with_their_kind():
    client = FakeClient(responses={
        "list_assemblies": [{"assembly_id": 9}],
        "list_components": [{"component_id": 1, "trade": "Pipelayer", "count": 2}]})
    plan = SyncPlan(crew_ops=[CrewOp(
        kind="update", crew_id="pipe", description="",
        members=[{"trade": "Pipelayer", "count": 2},
                 {"trade": "Loader, 950 class", "count": 1}])])
    spec = {"items": [], "rate_table": [
        {"trade": "Loader, 950 class", "rate": 110.0, "kind": "equipment"}]}
    run_sync(plan, spec, client)
    (add,) = [kw for tool, kw in client.calls if tool == "create_component"]
    assert add == {"assembly_id": 9, "trade": "Loader, 950 class", "count": 1, "kind": "equipment"}


# ---------- run_sync (item ops) ----------

def test_run_sync_item_create_calls_tool_and_writes_back_pk():
    client = FakeClient(responses={"create_estimate_item": 100})
    spec = {"items": [{"item_no": "Item # 99", "description": "Punchlist"}]}
    plan = SyncPlan(item_ops=[ItemOp(
        kind="create", estimate_item_id=None,
        item_no="Item # 99", description="Punchlist", qty=1, uom="LS")])
    report = run_sync(plan, spec, client)
    assert client.calls == [("create_estimate_item", {
        "item_number": "Item # 99", "description": "Punchlist",
        "estimated_quantity": 1, "unit": "LS",
        "wbs": "", "cost_code": "", "crew_assembly_id": 0})]
    assert spec["items"][0]["estimate_item_id"] == 100
    assert report.item_creates == [
        {"item_no": "Item # 99", "estimate_item_id": 100, "status": "ok"}]


def test_run_sync_item_create_formula_qty_errors_without_call():
    client = FakeClient()
    plan = SyncPlan(item_ops=[ItemOp(
        kind="create", estimate_item_id=None,
        item_no="Item # 77", description="Walls",
        qty="={ref:walls_cy}", uom="CY")])
    report = run_sync(plan, {"items": []}, client)
    assert client.calls == []
    assert report.item_creates == [
        {"item_no": "Item # 77", "status": "error",
         "detail": "formula qty; resolve before sync"}]


def test_run_sync_item_create_writeback_failure_reported():
    """BM record created but no un-synced local item to anchor it."""
    client = FakeClient(responses={"create_estimate_item": 100})
    plan = SyncPlan(item_ops=[ItemOp(
        kind="create", estimate_item_id=None,
        item_no="Item # 99", description="Punchlist", qty=1, uom="LS")])
    report = run_sync(plan, {"items": []}, client)   # spec has no such item
    assert report.item_creates[0]["status"] == "error"
    assert "re-fetch" in report.item_creates[0]["detail"]
    assert report.item_creates[0]["estimate_item_id"] == 100


def test_run_sync_item_create_passes_metadata_with_resolved_crew():
    client = FakeClient(responses={
        "list_assemblies": [{"assembly_id": 7, "name": "crew_lab_2"}],
        "create_estimate_item": 100})
    spec = {"items": [{"item_no": "Item # 99", "description": "Punchlist"}]}
    plan = SyncPlan(item_ops=[ItemOp(
        kind="create", estimate_item_id=None,
        item_no="Item # 99", description="Punchlist", qty=1, uom="LS",
        wbs="2.0", cost_code="05-100", crew_id="crew_lab_2")])
    report = run_sync(plan, spec, client)
    assert client.calls == [
        ("list_assemblies", {"assembly_type": "CREW", "name": "crew_lab_2"}),
        ("create_estimate_item", {
            "item_number": "Item # 99", "description": "Punchlist",
            "estimated_quantity": 1, "unit": "LS",
            "wbs": "2.0", "cost_code": "05-100", "crew_assembly_id": 7}),
    ]
    assert report.item_creates[0]["status"] == "ok"
    assert spec["items"][0]["estimate_item_id"] == 100


def test_run_sync_item_create_unset_metadata_no_lookup():
    client = FakeClient(responses={"create_estimate_item": 100})
    spec = {"items": [{"item_no": "Item # 99", "description": "Punchlist"}]}
    plan = SyncPlan(item_ops=[ItemOp(
        kind="create", estimate_item_id=None,
        item_no="Item # 99", description="Punchlist", qty=1, uom="LS")])
    run_sync(plan, spec, client)
    assert client.calls == [("create_estimate_item", {
        "item_number": "Item # 99", "description": "Punchlist",
        "estimated_quantity": 1, "unit": "LS",
        "wbs": "", "cost_code": "", "crew_assembly_id": 0})]


def test_run_sync_item_create_unresolvable_crew_fails_whole_op():
    """No BM write, no writeback: a partial create-without-crew would anchor
    an estimate_item_id whose crew leg the next plan_sync cannot re-emit."""
    client = FakeClient(responses={"create_estimate_item": 100})
    spec = {"items": [{"item_no": "Item # 99", "description": "Punchlist"}]}
    plan = SyncPlan(item_ops=[ItemOp(
        kind="create", estimate_item_id=None,
        item_no="Item # 99", description="Punchlist", qty=1, uom="LS",
        crew_id="crew_missing")])
    report = run_sync(plan, spec, client)
    assert client.tools_called() == ["list_assemblies"]   # no create call
    assert "estimate_item_id" not in spec["items"][0]     # no writeback
    assert report.item_creates[0]["status"] == "error"
    assert "crew_missing" in report.item_creates[0]["detail"]


def test_run_sync_item_update_bid_fields_only():
    client = FakeClient()
    plan = SyncPlan(item_ops=[ItemOp(
        kind="update", estimate_item_id=100,
        item_no="Item # 42A", description="Concrete Outfall",
        qty=240, uom="CY", changed_fields=["item_no", "description"])])
    report = run_sync(plan, {"items": []}, client)
    assert client.calls == [("update_bid_item", {
        "estimate_item_id": 100,
        "item_number": "Item # 42A", "description": "Concrete Outfall"})]
    assert report.item_updates == [
        {"estimate_item_id": 100, "changed_fields": ["item_no", "description"],
         "status": "ok"}]


def test_run_sync_recovered_anchor_update_writes_id_back_to_edited_spec():
    """When plan_sync recovers an anchor by item_no (the edited spec dropped
    its estimate_item_id but the base snapshot had one, #250), a successful
    update must persist that id back to edited_spec — so the NEXT sync matches
    by id instead of re-running the item_no heuristic (which could degrade to
    warn-and-skip on a later snapshot that also lacks the anchor)."""
    client = FakeClient()
    edited = {"items": [{"item_no": "Item # 1", "description": "Mob",
                         "qty": 240, "uom": "LS"}]}          # no estimate_item_id
    plan = SyncPlan(item_ops=[ItemOp(
        kind="update", estimate_item_id=100,
        item_no="Item # 1", description="Mob", qty=240, uom="LS",
        changed_fields=["qty"], recovered_anchor=True)])
    report = run_sync(plan, edited, client)
    assert report.item_updates[0]["status"] == "ok"
    assert edited["items"][0]["estimate_item_id"] == 100     # anchor persisted


def test_run_sync_non_recovered_update_does_not_touch_edited_spec():
    """A normal id-anchored update (not recovered) leaves edited_spec alone —
    the writeback is scoped to the recovery case."""
    client = FakeClient()
    edited = {"items": [{"item_no": "Item # 1", "description": "Mob",
                         "qty": 240, "uom": "LS", "estimate_item_id": 100}]}
    plan = SyncPlan(item_ops=[ItemOp(
        kind="update", estimate_item_id=100,
        item_no="Item # 1", description="Mob", qty=240, uom="LS",
        changed_fields=["qty"])])                            # recovered_anchor=False
    run_sync(plan, edited, client)
    assert edited["items"][0]["estimate_item_id"] == 100     # unchanged, no raise


def test_run_sync_item_update_qty_only():
    client = FakeClient()
    plan = SyncPlan(item_ops=[ItemOp(
        kind="update", estimate_item_id=100,
        item_no="Item # 42A", description="Concrete Outfall",
        qty=240, uom="CY", changed_fields=["qty"])])
    report = run_sync(plan, {"items": []}, client)
    assert client.calls == [("update_estimate_item", {
        "estimate_item_id": 100, "estimated_quantity": 240})]
    assert report.item_updates[0]["status"] == "ok"


def test_run_sync_item_update_both_categories_issues_both_calls():
    client = FakeClient()
    plan = SyncPlan(item_ops=[ItemOp(
        kind="update", estimate_item_id=100,
        item_no="Item # 42A", description="Concrete Outfall",
        qty=240, uom="CY", changed_fields=["uom", "qty"])])
    report = run_sync(plan, {"items": []}, client)
    assert client.calls == [
        ("update_bid_item", {"estimate_item_id": 100, "unit": "CY"}),
        ("update_estimate_item", {"estimate_item_id": 100,
                                  "estimated_quantity": 240}),
    ]
    assert report.item_updates[0]["status"] == "ok"


def test_run_sync_item_update_formula_qty_errors_but_bid_fields_still_pushed():
    client = FakeClient()
    plan = SyncPlan(item_ops=[ItemOp(
        kind="update", estimate_item_id=100,
        item_no="Item # 42A", description="Concrete Outfall",
        qty="={ref:walls_cy}", uom="CY", changed_fields=["item_no", "qty"])])
    report = run_sync(plan, {"items": []}, client)
    assert client.tools_called() == ["update_bid_item"]
    assert report.item_updates[0]["status"] == "error"
    assert "formula qty" in report.item_updates[0]["detail"]


def test_run_sync_item_update_partial_failure_concatenates_detail():
    def boom(**kwargs):
        raise RuntimeError("stale row")
    client = FakeClient(responses={"update_bid_item": boom})
    plan = SyncPlan(item_ops=[ItemOp(
        kind="update", estimate_item_id=100,
        item_no="Item # 42A", description="Concrete Outfall",
        qty=240, uom="CY", changed_fields=["item_no", "qty"])])
    report = run_sync(plan, {"items": []}, client)
    # qty call still attempted after the bid-item call failed
    assert client.tools_called() == ["update_bid_item", "update_estimate_item"]
    assert report.item_updates[0]["status"] == "error"
    assert "update_bid_item: stale row" in report.item_updates[0]["detail"]


def test_run_sync_item_update_wbs_and_cost_code_ride_update_bid_item():
    client = FakeClient()
    plan = SyncPlan(item_ops=[ItemOp(
        kind="update", estimate_item_id=100,
        item_no="Item # 1", description="Mob", qty=1, uom="LS",
        wbs="1.2", cost_code="02-110",
        changed_fields=["wbs", "cost_code"])])
    report = run_sync(plan, {"items": []}, client)
    assert client.calls == [("update_bid_item", {
        "estimate_item_id": 100, "wbs": "1.2", "cost_code": "02-110"})]
    assert report.item_updates[0]["status"] == "ok"


def test_run_sync_item_update_crew_resolves_name_to_assembly_id():
    client = FakeClient(responses={
        "list_assemblies": [{"assembly_id": 7, "name": "crew_lab_2"}]})
    plan = SyncPlan(item_ops=[ItemOp(
        kind="update", estimate_item_id=100,
        item_no="Item # 1", description="Mob", qty=1, uom="LS",
        crew_id="crew_lab_2", changed_fields=["crew_id"])])
    report = run_sync(plan, {"items": []}, client)
    assert client.calls == [
        ("list_assemblies", {"assembly_type": "CREW", "name": "crew_lab_2"}),
        ("update_bid_item", {"estimate_item_id": 100, "crew_assembly_id": 7}),
    ]
    assert report.item_updates[0]["status"] == "ok"


def test_run_sync_item_update_crew_cleared_pushes_zero_without_lookup():
    client = FakeClient()
    plan = SyncPlan(item_ops=[ItemOp(
        kind="update", estimate_item_id=100,
        item_no="Item # 1", description="Mob", qty=1, uom="LS",
        crew_id="", changed_fields=["crew_id"])])
    report = run_sync(plan, {"items": []}, client)
    assert client.calls == [("update_bid_item", {
        "estimate_item_id": 100, "crew_assembly_id": 0})]
    assert report.item_updates[0]["status"] == "ok"


def test_run_sync_item_update_crew_not_found_errors_other_legs_push():
    client = FakeClient()   # list_assemblies default: []
    plan = SyncPlan(item_ops=[ItemOp(
        kind="update", estimate_item_id=100,
        item_no="Item # 1", description="Mobilization", qty=1, uom="LS",
        crew_id="crew_missing", changed_fields=["description", "crew_id"])])
    report = run_sync(plan, {"items": []}, client)
    # description still pushed, without the crew kwarg
    assert ("update_bid_item", {"estimate_item_id": 100,
                                "description": "Mobilization"}) in client.calls
    assert report.item_updates[0]["status"] == "error"
    assert "crew_missing" in report.item_updates[0]["detail"]


def test_run_sync_item_update_crew_ambiguous_errors():
    client = FakeClient(responses={"list_assemblies": [
        {"assembly_id": 7, "name": "crew_lab_2"},
        {"assembly_id": 8, "name": "crew_lab_2"}]})
    plan = SyncPlan(item_ops=[ItemOp(
        kind="update", estimate_item_id=100,
        item_no="Item # 1", description="Mob", qty=1, uom="LS",
        crew_id="crew_lab_2", changed_fields=["crew_id"])])
    report = run_sync(plan, {"items": []}, client)
    assert report.item_updates[0]["status"] == "error"
    assert "multiple assemblies" in report.item_updates[0]["detail"]


def test_run_sync_crew_resolution_cached_per_run():
    client = FakeClient(responses={
        "list_assemblies": [{"assembly_id": 7, "name": "crew_lab_2"}]})
    op = dict(kind="update", item_no="Item # 1", description="Mob",
              qty=1, uom="LS", crew_id="crew_lab_2",
              changed_fields=["crew_id"])
    plan = SyncPlan(item_ops=[ItemOp(estimate_item_id=100, **op),
                              ItemOp(estimate_item_id=200, **op)])
    run_sync(plan, {"items": []}, client)
    assert client.tools_called().count("list_assemblies") == 1


def test_run_sync_crew_resolution_failure_not_cached_retries_per_item():
    """A failed resolution on one item must not suppress the lookup for
    later items — failures are not cached; each item retries."""
    client = FakeClient()   # list_assemblies default: [] -> not found
    op = dict(kind="update", item_no="Item # 1", description="Mob",
              qty=1, uom="LS", crew_id="crew_missing",
              changed_fields=["crew_id"])
    plan = SyncPlan(item_ops=[ItemOp(estimate_item_id=100, **op),
                              ItemOp(estimate_item_id=200, **op)])
    report = run_sync(plan, {"items": []}, client)
    assert client.tools_called().count("list_assemblies") == 2
    assert [r["status"] for r in report.item_updates] == ["error", "error"]


def test_run_sync_item_delete():
    client = FakeClient()
    plan = SyncPlan(item_ops=[ItemOp(
        kind="delete", estimate_item_id=200,
        item_no="Item # 1", description="Mobilization", qty=1, uom="LS")])
    report = run_sync(plan, {"items": []}, client)
    assert client.calls == [("delete_estimate_item", {"estimate_item_id": 200})]
    assert report.item_deletes == [
        {"estimate_item_id": 200, "item_no": "Item # 1", "status": "ok"}]


def test_run_sync_item_unknown_kind_raises():
    client = FakeClient()
    plan = SyncPlan(item_ops=[ItemOp(
        kind="upsert", estimate_item_id=None,
        item_no="Item # 1", description="Mob", qty=1, uom="LS")])
    with pytest.raises(ValueError):
        run_sync(plan, {"items": []}, client)
    assert client.calls == []


def test_run_sync_item_update_unsupported_changed_field_is_error():
    client = FakeClient()
    plan = SyncPlan(item_ops=[ItemOp(
        kind="update", estimate_item_id=100,
        item_no="Item # 1", description="Mob", qty=1, uom="LS",
        changed_fields=["color"])])
    report = run_sync(plan, {"items": []}, client)
    assert client.calls == []
    assert report.item_updates[0]["status"] == "error"
    assert "unsupported changed_fields: color" in report.item_updates[0]["detail"]


def test_run_sync_error_mid_plan_continues_to_later_ops():
    def boom(**kwargs):
        raise RuntimeError("BM down")
    client = FakeClient(responses={"delete_estimate_item": boom})
    plan = SyncPlan(item_ops=[
        ItemOp(kind="delete", estimate_item_id=200,
               item_no="Item # 1", description="Mob", qty=1, uom="LS"),
        ItemOp(kind="update", estimate_item_id=100,
               item_no="Item # 2", description="Clearing", qty=5, uom="AC",
               changed_fields=["qty"]),
    ])
    report = run_sync(plan, {"items": []}, client)
    assert report.item_deletes[0]["status"] == "error"
    assert report.item_updates[0]["status"] == "ok"


# ---------- integration: plan_sync -> run_sync ----------

def test_plan_sync_run_sync_end_to_end():
    """Diff hand-built specs, execute against a fake client with sequential
    pks, and verify both the report and the spec writeback."""
    base = {
        "project": "Sample", "markup": 100,
        "rate_table": [{"trade": "FORE", "rate": 150}],
        "crews": [{"id": "crew_lab_2", "description": "2-person lab crew",
                   "members": [{"trade": "LAB", "count": 2}]}],
        "items": [
            {"estimate_item_id": 100, "item_no": "Item # 1",
             "description": "Mobilization", "qty": 1, "uom": "LS",
             "cost_code": "01-000"},  # cleared in edited
            {"estimate_item_id": 200, "item_no": "Item # 2",
             "description": "Clearing", "qty": 5, "uom": "AC"},
        ],
    }
    edited = {
        "project": "Sample", "markup": 100,
        "rate_table": [{"trade": "FORE", "rate": 150},
                       {"trade": "MASON", "rate": 105}],   # new rate
        "crews": [{"id": "crew_lab_2", "description": "2-person lab crew",
                   "members": [{"trade": "LAB", "count": 3}]}],  # count edit
        "items": [
            {"estimate_item_id": 100, "item_no": "Item # 1",
             "description": "Mobilization", "qty": 2, "uom": "LS",
             "wbs": "4.5", "crew_id": "crew_lab_2"},                 # qty + metadata edit
            # Item # 2 deleted
            {"item_no": "Item # 99", "description": "Punchlist",
             "qty": 1, "uom": "LS", "wbs": "2.0"},                   # new item
        ],
    }
    pks = iter([501])
    client = FakeClient(responses={
        "list_assemblies": [{"assembly_id": 7, "name": "crew_lab_2"}],
        "list_components": [{"component_id": 21, "trade": "LAB", "count": 2}],
        "create_estimate_item": lambda **kwargs: next(pks),
    })

    plan = plan_sync(base, edited)
    report = run_sync(plan, edited, client)

    assert report.rate_creates == [
        {"trade": "MASON", "rate": 105, "status": "ok"}]
    assert report.crew_updates == [{"crew_id": "crew_lab_2", "status": "ok"}]
    assert ("update_component", {"component_id": 21, "count": 3}) in client.calls
    assert report.item_creates == [
        {"item_no": "Item # 99", "estimate_item_id": 501, "status": "ok"}]
    assert report.item_updates == [
        {"estimate_item_id": 100,
         "changed_fields": ["qty", "wbs", "cost_code", "crew_id"],
         "status": "ok"}]
    assert ("update_bid_item",
            {"estimate_item_id": 100, "wbs": "4.5", "cost_code": "",
             "crew_assembly_id": 7}) in client.calls
    assert ("create_estimate_item",
            {"item_number": "Item # 99", "description": "Punchlist",
             "estimated_quantity": 1, "unit": "LS",
             "wbs": "2.0", "cost_code": "", "crew_assembly_id": 0}) in client.calls
    assert report.item_deletes == [
        {"estimate_item_id": 200, "item_no": "Item # 2", "status": "ok"}]
    # writeback landed in the edited spec
    new_item = [it for it in edited["items"] if it["item_no"] == "Item # 99"][0]
    assert new_item["estimate_item_id"] == 501
    # and the report renders without error
    out = render_exec_report(report)
    assert out.startswith("# Sync results\n\n5 ok · 0 errors.")
