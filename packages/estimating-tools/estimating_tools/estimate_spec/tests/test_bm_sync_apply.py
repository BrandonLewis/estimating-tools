from estimating_tools.estimate_spec.bm_sync.apply import apply_results, resolve_path
from estimating_tools.estimate_spec.bm_sync.ops import Op, Plan
from estimating_tools.estimate_spec.bm_sync.sidecar import QuoteSync, Sidecar

NOW = "2026-10-29T10:00:00"
SHA = "abc123"
PKG = "Reinforcing steel"
FILE = "acme-rebar--reinforcing-steel.json"
CHOICE = {"selected": "Acme", "pinned": True, "picks": {}}


def _key(field):
    return f"packages.{PKG}.quotes.{FILE}.{field}"


def _plan(ops, meta=None):
    base = {"project_id": 7, "estimate_id": 9, "spec_choice": {PKG: CHOICE}, "file_sha": {FILE: SHA}}
    return Plan("push", "spec.yaml", ops, [], meta={**base, **(meta or {})})


def _basic_ops():
    return [
        Op("p3", "create_quote", "create_work_package_quote", {"vendor_id": 4722}, PKG,
           sidecar={_key("quote_id"): "$.id", _key("revision"): "$.revision"}),
        Op("p4", "create_line", "create_line", {}, PKG, sidecar={_key("lines.61"): "$.id"}, after="p3"),
        Op("p5", "carry", "carry", {}, PKG, sidecar={f"packages.{PKG}.bm_choice": "$"}, after="p3"),
    ]


def test_resolve_path_forms():
    r = {"id": 1, "created": [{"id": 5}], "line_items": [{"item_number": "61", "id": 9}]}
    assert resolve_path(r, "$.id") == 1
    assert resolve_path(r, "$.created[0].id") == 5
    assert resolve_path(r, "$") is r
    assert resolve_path(r, "$.line_items[?item_number=='61'].id") == 9


def test_applies_ids_revisions_lines_and_choice():
    snap = {"carry_mode": "pinned", "selected_quote_id": {"$ref": "p3", "path": "$.id"}, "hand_items": []}
    plan = _plan(_basic_ops(), {"bm_choice": {PKG: snap}})
    sc = Sidecar()
    rep = apply_results(plan, {"results": {"p3": {"id": 55, "revision": 1}, "p4": {"id": 901},
                                           "p5": {"ok": True}}}, sc, now=NOW)
    assert rep.applied == ["p3", "p4", "p5"] and not rep.errors
    p = sc.package(PKG)
    assert p.quotes[FILE] == QuoteSync(55, 1, 4722, SHA, {"61": 901})
    assert p.bm_choice == {"carry_mode": "pinned", "selected_quote_id": 55, "hand_items": []}
    assert p.synced_at == NOW and p.spec_choice == CHOICE
    assert (sc.project_id, sc.estimate_id) == (7, 9)


def test_vendor_id_from_result_wins():
    sc = Sidecar()
    apply_results(_plan(_basic_ops()[:1]), {"results": {"p3": {"id": 55, "revision": 1, "vendor_id": 12}}},
                  sc, now=NOW)
    assert sc.package(PKG).quotes[FILE].vendor_id == 12


def test_error_result_skips_dependents_and_writes_nothing_for_them():
    plan = _plan(_basic_ops())
    sc = Sidecar()
    rep = apply_results(plan, {"results": {"p3": {"error": "vendor_id 4722 not found"}, "p4": {"id": 1}}},
                        sc, now=NOW)
    assert rep.errors == [("p3", "vendor_id 4722 not found")]
    assert ("p4", "depends on p3 which failed") in rep.skipped
    assert ("p5", "depends on p3 which failed") in rep.skipped
    assert FILE not in sc.package(PKG).quotes
    assert sc.package(PKG).synced_at is None and sc.package(PKG).spec_choice is None


def test_no_result_is_skipped():
    rep = apply_results(_plan(_basic_ops()[:1]), {"results": {}}, Sidecar(), now=NOW)
    assert rep.skipped == [("p3", "no result")]


def test_plug_entry_dict_is_appended_to_plugs_removed():
    """#428: a remove_plug op's sidecar value is the entry itself (assembly id, component
    id, name), appended as recorded; a legacy "+<a>:<c>" string still appends, nameless."""
    entry = {"assembly_id": 3617, "component_id": 9001, "name": "01 Rebar furnished and placed"}
    ops = [Op("p1", "remove_plug", "t", {}, PKG, sidecar={f"packages.{PKG}.plugs_removed.61": entry}),
           Op("p2", "remove_plug", "t", {}, PKG, sidecar={f"packages.{PKG}.plugs_removed.61": "+3617:9002"})]
    sc = Sidecar()
    apply_results(_plan(ops), {"results": {"p1": {"ok": 1}, "p2": {"ok": 1}}}, sc, now=NOW)
    assert sc.package(PKG).plugs_removed["61"] == [
        entry, {"assembly_id": 3617, "component_id": 9002, "name": None}]


def test_stale_plug_entries_are_pruned_from_plan_meta():
    """#428: entries the planner found stale (their assembly was replaced by a re-push) are
    dropped by apply, even with no op applied, and reported."""
    live = {"assembly_id": 3617, "component_id": 9001, "name": "01 Rebar furnished and placed"}
    stale = {"assembly_id": 3000, "component_id": 8001, "name": "02 Couplers"}
    sc = Sidecar()
    sc.package(PKG).plugs_removed = {"61": [stale, live]}
    rep = apply_results(_plan([], {"stale_plugs": {PKG: {"61": [stale]}}}), {"results": {}}, sc, now=NOW)
    assert sc.package(PKG).plugs_removed == {"61": [live]}
    assert rep.pruned == [f"{PKG} item 61: 3000:8001 02 Couplers"]


def test_carry_warnings_are_collected():
    rep = apply_results(_plan(_basic_ops()[:1]),
                        {"results": {"p3": {"id": 55, "revision": 1, "carry_warning": "no linked estimate"}}},
                        Sidecar(), now=NOW)
    assert rep.warnings == ["p3 create_quote Reinforcing steel: no linked estimate"]
    rep = apply_results(_plan(_basic_ops()[:1]),
                        {"results": {"p3": {"id": 55, "revision": 1, "carry_warnings": ["a", "b"]}}},
                        Sidecar(), now=NOW)
    assert rep.warnings == ["p3 create_quote Reinforcing steel: a", "p3 create_quote Reinforcing steel: b"]


def test_dotted_package_and_file_names():
    pkg, file = "Div 3.1 steel", "a.b-co.json"
    ops = [Op("p1", "create_quote", "t", {}, pkg,
              sidecar={f"packages.{pkg}.quotes.{file}.quote_id": "$.id",
                       f"packages.{pkg}.quotes.{file}.revision": "$.revision",
                       f"packages.{pkg}.quotes.{file}.lines.61": "$.created[0].id"})]
    sc = Sidecar()
    plan = Plan("push", "s", ops, [], meta={"file_sha": {file: "s1"}})
    apply_results(plan, {"results": {"p1": {"id": 3, "revision": 2, "created": [{"id": 8}]}}}, sc, now=NOW)
    assert sc.packages[pkg].quotes[file] == QuoteSync(3, 2, None, "s1", {"61": 8})


def test_revision_rebuilds_lines_but_other_quotes_merge():
    sc = Sidecar()
    sc.package(PKG).quotes[FILE] = QuoteSync(55, 1, 4722, "old", {"61": 901, "62": 902})
    ops = [Op("p1", "create_revision", "t", {}, PKG,
              sidecar={_key("quote_id"): "$.id", _key("revision"): "$.revision",
                       _key("lines.61"): "$.line_items[?item_number=='61'].id"}),
           Op("p2", "delete_line", "t", {}, PKG, after="p1")]
    apply_results(_plan(ops), {"results": {"p1": {"id": 56, "revision": 2,
                                                  "line_items": [{"item_number": "61", "id": 951}]},
                                           "p2": {"ok": True}}}, sc, now=NOW)
    assert sc.package(PKG).quotes[FILE] == QuoteSync(56, 2, 4722, SHA, {"61": 951})


def test_lines_merge_when_quote_not_revised():
    sc = Sidecar()
    sc.package(PKG).quotes[FILE] = QuoteSync(55, 1, 4722, "old", {"61": 901})
    ops = [Op("p1", "create_line", "t", {}, PKG, sidecar={_key("lines.62"): "$.id"})]
    apply_results(_plan(ops), {"results": {"p1": {"id": 902}}}, sc, now=NOW)
    assert sc.package(PKG).quotes[FILE] == QuoteSync(55, 1, 4722, SHA, {"61": 901, "62": 902})


def test_bm_choice_with_failed_ref_is_left_unwritten():
    snap = {"carry_mode": "pinned", "selected_quote_id": {"$ref": "p3", "path": "$.id"}, "hand_items": []}
    ops = [Op("p3", "create_quote", "t", {}, PKG, sidecar={_key("quote_id"): "$.id"}),
           Op("p5", "carry", "t", {}, PKG, sidecar={f"packages.{PKG}.bm_choice": "$"})]
    sc = Sidecar()
    rep = apply_results(_plan(ops, {"bm_choice": {PKG: snap}}),
                        {"results": {"p3": {"error": "boom"}, "p5": {"ok": True}}}, sc, now=NOW)
    assert sc.package(PKG).bm_choice is None
    assert any(r == f"bm_choice for {PKG} depends on p3 which failed" for _id, r in rep.skipped)


def test_work_package_ids_from_ensure_op():
    ops = [Op("p1", "ensure_package", "t", {}, PKG,
              sidecar={f"packages.{PKG}.work_package_id": "$.id",
                       f"packages.{PKG}.estimate_package_id": "$.estimate_package_id"})]
    sc = Sidecar()
    apply_results(_plan(ops), {"results": {"p1": {"id": 4, "estimate_package_id": 6}}}, sc, now=NOW)
    p = sc.package(PKG)
    assert (p.work_package_id, p.estimate_package_id) == (4, 6)


def test_existing_package_ids_come_from_plan_meta():
    """#421: a touched package with no ensure op records the export's ids from plan.meta."""
    ops = _basic_ops()[:2]
    ids = {PKG: {"work_package_id": 273, "estimate_package_id": 176}}
    sc = Sidecar()
    apply_results(_plan(ops, {"package_ids": ids}),
                  {"results": {"p3": {"id": 55, "revision": 1}, "p4": {"id": 901}}}, sc, now=NOW)
    p = sc.package(PKG)
    assert (p.work_package_id, p.estimate_package_id) == (273, 176)


def test_meta_ids_do_not_touch_a_package_with_no_applied_op():
    ids = {PKG: {"work_package_id": 273, "estimate_package_id": 176}}
    sc = Sidecar()
    apply_results(_plan(_basic_ops()[:1], {"package_ids": ids}), {"results": {}}, sc, now=NOW)
    assert PKG not in sc.packages


def test_a_recorded_package_with_null_ids_is_healed_from_plan_meta():
    """#421: a sidecar written before the fix has null ids; the next apply fills them even
    when the plan has no op for that package."""
    ids = {PKG: {"work_package_id": 273, "estimate_package_id": 176}}
    sc = Sidecar()
    sc.package(PKG).synced_at = "2026-11-01T21:26:31"
    rep = apply_results(_plan([], {"package_ids": ids}), {"results": {}}, sc, now=NOW)
    p = sc.package(PKG)
    assert (p.work_package_id, p.estimate_package_id) == (273, 176)
    assert p.synced_at == "2026-11-01T21:26:31" and rep.applied == []


def test_id_healing_leaves_an_untouched_package_baselines_alone():
    """#422 review: a recorded package whose op got no result keeps its spec_choice and
    bm_choice, so the next push still sees the spec movement and retries."""
    old_spec = {"selected": "Acme", "pinned": True, "picks": {}}
    old_bm = {"carry_mode": "pinned", "selected_quote_id": 55, "hand_items": []}
    sc = Sidecar()
    ps = sc.package(PKG)
    ps.spec_choice, ps.bm_choice = dict(old_spec), dict(old_bm)
    carry = Op("p5", "carry", "carry", {}, PKG, sidecar={f"packages.{PKG}.bm_choice": "$"})
    observed = {"carry_mode": "automatic", "selected_quote_id": None, "hand_items": []}
    plan = _plan([carry], {"spec_choice": {PKG: {"selected": "ARR", "pinned": False, "picks": {}}},
                           "bm_choice": {PKG: observed},
                           "package_ids": {PKG: {"work_package_id": 273, "estimate_package_id": 176}}})
    rep = apply_results(plan, {"results": {}}, sc, now=NOW)
    assert rep.applied == [] and rep.skipped == [("p5", "no result")]
    assert (ps.work_package_id, ps.estimate_package_id) == (273, 176)
    assert ps.spec_choice == old_spec and ps.bm_choice == old_bm


def test_no_result_parent_skips_dependents():
    sc = Sidecar()
    rep = apply_results(_plan(_basic_ops()), {"results": {"p4": {"id": 901}, "p5": {"ok": True}}}, sc, now=NOW)
    assert ("p3", "no result") in rep.skipped
    assert ("p4", "depends on p3 which has no result") in rep.skipped
    assert ("p5", "depends on p3 which has no result") in rep.skipped
    assert rep.applied == [] and FILE not in sc.package(PKG).quotes


def test_transitive_error_chain_skips_all_dependents():
    ops = [Op("p3", "create_quote", "t", {}, PKG, sidecar={_key("quote_id"): "$.id"}),
           Op("p4", "create_line", "t", {}, PKG, sidecar={_key("lines.61"): "$.id"}, after="p3"),
           Op("p5", "create_line", "t", {}, PKG, sidecar={_key("lines.62"): "$.id"}, after="p4")]
    sc = Sidecar()
    rep = apply_results(_plan(ops), {"results": {"p3": {"error": "x"}, "p4": {"id": 1}, "p5": {"id": 2}}},
                        sc, now=NOW)
    assert ("p4", "depends on p3 which failed") in rep.skipped
    assert ("p5", "depends on p3 which failed") in rep.skipped
    assert FILE not in sc.package(PKG).quotes and rep.applied == []


def test_bm_choice_without_snapshot_is_an_error():
    ops = [Op("p5", "carry", "t", {}, PKG, sidecar={f"packages.{PKG}.bm_choice": "$"})]
    sc = Sidecar()
    rep = apply_results(_plan(ops), {"results": {"p5": {"ok": True}}}, sc, now=NOW)
    assert rep.errors == [("p5", f"bm_choice for {PKG}: plan carries no snapshot")]
    assert sc.package(PKG).bm_choice is None


def test_missing_result_path_is_an_error_entry():
    ops = [Op("p1", "create_quote", "t", {}, PKG, sidecar={_key("quote_id"): "$.id"})]
    sc = Sidecar()
    rep = apply_results(_plan(ops), {"results": {"p1": {"nope": 1}}}, sc, now=NOW)
    assert rep.errors == [("p1", f"p1 create_quote {PKG}: result has no $.id")]
    assert FILE not in sc.package(PKG).quotes


def test_bm_choice_ref_path_missing_is_an_error_entry():
    snap = {"carry_mode": "pinned", "selected_quote_id": {"$ref": "p3", "path": "$.id"}, "hand_items": []}
    ops = [Op("p3", "create_quote", "t", {}, PKG),
           Op("p5", "carry", "t", {}, PKG, sidecar={f"packages.{PKG}.bm_choice": "$"})]
    sc = Sidecar()
    rep = apply_results(_plan(ops, {"bm_choice": {PKG: snap}}),
                        {"results": {"p3": {"other": 1}, "p5": {"ok": True}}}, sc, now=NOW)
    assert rep.errors == [("p5", f"p5 carry {PKG}: result has no $.id (from p3)")]
    assert sc.package(PKG).bm_choice is None


def test_error_result_still_collects_carry_warning():
    rep = apply_results(_plan(_basic_ops()[:1]),
                        {"results": {"p3": {"error": "bad", "carry_warning": "w"}}}, Sidecar(), now=NOW)
    assert rep.errors == [("p3", "bad")]
    assert rep.warnings == ["p3 create_quote Reinforcing steel: w"]


def test_baseline_bm_choice_is_written_for_a_package_with_no_choice_op():
    """Ruling 41: a package the plan touches records BidSheet.ai's observed choice."""
    ops = _basic_ops()[:2]
    observed = {"carry_mode": "automatic", "selected_quote_id": None, "hand_items": []}
    sc = Sidecar()
    apply_results(_plan(ops, {"bm_choice": {PKG: observed}}),
                  {"results": {"p3": {"id": 55, "revision": 1}, "p4": {"id": 901}}}, sc, now=NOW)
    assert sc.package(PKG).bm_choice == observed


def test_baseline_bm_choice_resolves_a_revision_reference():
    rev = Op("p3", "create_revision", "create_quote_revision", {}, PKG,
             sidecar={_key("quote_id"): "$.id", _key("revision"): "$.revision"})
    snap = {"carry_mode": "pinned", "selected_quote_id": {"$ref": "p3", "path": "$.id"}, "hand_items": []}
    sc = Sidecar()
    apply_results(_plan([rev], {"bm_choice": {PKG: snap}}), {"results": {"p3": {"id": 77, "revision": 2}}},
                  sc, now=NOW)
    assert sc.package(PKG).bm_choice == {"carry_mode": "pinned", "selected_quote_id": 77, "hand_items": []}


def test_a_failed_choice_op_writes_no_baseline():
    target = {"carry_mode": "pinned", "selected_quote_id": 55, "hand_items": []}
    sc = Sidecar()
    ops = [Op("p1", "update_line", "u", {}, PKG), Op("p2", "carry", "c", {}, PKG,
                                                     sidecar={f"packages.{PKG}.bm_choice": "$"})]
    apply_results(_plan(ops, {"bm_choice": {PKG: target}}),
                  {"results": {"p1": {"ok": True}, "p2": {"error": "locked"}}}, sc, now=NOW)
    assert sc.package(PKG).bm_choice is None


def test_adopted_quotes_are_written_with_no_op_applied():
    """Ruling 44: an unchanged unsynced file matched in BidSheet.ai is recorded on apply."""
    adopt = {PKG: {FILE: {"quote_id": 55, "revision": 1, "vendor_id": 4722, "lines": {"61": 901}}}}
    sc = Sidecar()
    apply_results(_plan([], {"adopt": adopt}), {"results": {}}, sc, now=NOW)
    assert sc.package(PKG).quotes[FILE] == QuoteSync(55, 1, 4722, SHA, {"61": 901})
