from estimating_tools.estimate_spec.bm_sync.ops import Entry, Op, Plan, next_id, render_plan, reset_ids


def ops_for(package, n, start=1):
    return [Op(f"p{start + i}", "create_line", "create_quote_line", {"quote_id": 1, "item": i}, package) for i in range(n)]


def plan_with(*parts):
    ops, entries = [], []
    for part in parts:
        (entries.append(part) if isinstance(part, Entry) else ops.extend(part))
    for i, op in enumerate(ops):
        op.id = f"p{i + 1}"
    return Plan("push", "bid.estimate.yaml", ops, entries)


def test_plan_json_round_trip():
    op = Op("p1", "create_quote", "create_work_package_quote", {"work_package_id": 273, "vendor_name": "Acme Rebar", "amount": 1650.0}, "Reinforcing steel", sidecar={"packages.Reinforcing steel.quotes.acme-rebar--reinforcing-steel.json.quote_id": "$.id"})
    ref = Op("p2", "create_line", "create_quote_line", {"quote_id": {"$ref": "p1", "path": "$.id"}}, "Reinforcing steel", after="p1")
    plan = Plan("push", "bid.estimate.yaml", [op, ref], [Entry("notice", "Reinforcing steel", "x")],
                meta={"project_id": 1, "estimate_id": 2, "spec_choice": {"Reinforcing steel": {"a": 1}}, "file_sha": {"f.json": "abc"}})
    back = Plan.from_json(plan.to_json())
    assert back == plan
    assert back.ops[1].args["quote_id"] == {"$ref": "p1", "path": "$.id"}


def test_render_groups_by_package_and_lists_entries():
    text = render_plan(plan_with(ops_for("Reinforcing steel", 2), ops_for("Ready-mix concrete", 1), Entry("conflict", "Ready-mix concrete", "spec says Acme, BidSheet.ai pinned Bolt")))
    assert text.startswith("Push plan: 3 op(s), 1 entr(ies)")
    assert text.index("## Reinforcing steel") < text.index("## Ready-mix concrete")
    assert "| # | op | tool | detail |" in text
    assert "- conflict Ready-mix concrete: spec says Acme, BidSheet.ai pinned Bolt" in text


def test_render_note_ref_and_reconcile():
    ops = [Op("p1", "create_line", "t", {"quote_id": {"$ref": "p0", "path": "$.id"}, "n": 2}, "P"),
           Op("p2", "carry", "t", {"a": 1}, "P", note="carry it")]
    text = render_plan(Plan("pull", "s", ops, [Entry("reconcile", "P", "r")]))
    assert text.startswith("Pull plan: 2 op(s), 1 entr(ies)")
    assert "quote_id=p0.id n=2" in text
    assert "carry it" in text
    assert "- reconcile P: r" in text


def test_is_empty_ignores_notices():
    assert Plan("pull", "s", [], [Entry("notice", "P", "n")]).is_empty
    assert not Plan("pull", "s", [], [Entry("refused", "P", "n")]).is_empty
    assert not Plan("pull", "s", ops_for("P", 1), []).is_empty


def test_next_id():
    reset_ids()
    assert next_id("p") == "p1"
    assert next_id("p") == "p2"


def test_render_keeps_every_table_row_on_one_line():
    from estimating_tools.estimate_spec.bm_sync.export import BmExport
    from estimating_tools.estimate_spec.bm_sync.plan_push import plan_push
    from estimating_tools.estimate_spec.bm_sync.sidecar import Sidecar
    from estimating_tools.estimate_spec.tests._bm_fixture import acme_rebar, export_builder, spec_two_packages
    ex = BmExport.from_dict(export_builder().package("Reinforcing steel", 273, {"61": 7001})
                            .package("Ready-mix concrete", 274, {"62": 7002}).build())
    plan = plan_push(spec_two_packages(), [("acme.json", acme_rebar(), "sha")], ex, Sidecar(),
                     spec_name="s", now="2026-10-29T15:10:00")
    plan.ops.append(Op("p99", "create_revision", "t", {"notes": "a\nb|c"}, "Reinforcing steel"))
    text = render_plan(plan)
    table = text.split("## Reinforcing steel", 1)[1].split("\n\n")[1]
    rows = table.splitlines()
    assert len(rows) == len(plan.ops) + 2
    assert all(r.startswith("|") and r.endswith("|") for r in rows)
    assert "notes=a⏎b\\|c" in text
