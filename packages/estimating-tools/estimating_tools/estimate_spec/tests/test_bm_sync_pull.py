"""The pull planner: BidSheet.ai quotes into quote files (spec §1.4)."""
from __future__ import annotations

from dataclasses import replace

import yaml

from estimating_tools.estimate_spec.bm_sync.export import BmExport
from estimating_tools.estimate_spec.bm_sync.plan_pull import plan_pull, write_pull
from estimating_tools.estimate_spec.bm_sync.sidecar import QuoteSync, Sidecar, file_sha
from estimating_tools.estimate_spec.tests._bm_fixture import acme_rebar, export_builder, spec_two_packages
from estimating_tools.quotes.files import load_quote_file, write_quote_file

NOW = "2026-10-29T15:10:00"
ACME_FILE = "acme-rebar--reinforcing-steel.json"
ZED_FILE = "zed-rebar--reinforcing-steel.json"


def one(items, **attrs):
    found = [i for i in items if all(getattr(i, k) == v for k, v in attrs.items())]
    assert len(found) == 1, f"{len(found)} matches for {attrs}: {items}"
    return found[0]


def builder():
    return (export_builder().package("Reinforcing steel", 273, {"61": 7001})
            .package("Ready-mix concrete", 274, {"62": 7002}))


def acme_export(revision=2, unit_price=1.60):
    return BmExport.from_dict(builder().quote(
        "Reinforcing steel", 55, "Acme Rebar", 4722, revision=revision, amount=1600.0,
        lines=[{"item_number": "61", "line_id": 901, "unit_price": unit_price, "quantity": 1000}]).build())


def acme_sidecar(sha="sha-acme", revision=1) -> Sidecar:
    sc = Sidecar(1234, 100)
    sc.package("Reinforcing steel").quotes[ACME_FILE] = QuoteSync(55, revision, 4722, sha, {"61": 900})
    return sc


def pull(ex, sc=None, quotes=(), **kw):
    return plan_pull(spec_two_packages(), list(quotes), ex, sc or Sidecar(), spec_name="s", now=NOW, **kw)


def test_new_bm_quote_becomes_a_file_with_per_item_price_on_first_package_line():
    ex = BmExport.from_dict(builder().quote(
        "Reinforcing steel", 57, "Zed Rebar", 4730, amount=1700.0,
        lines=[{"item_number": "61", "line_id": 950, "unit_price": 1.70, "quantity": 1000}]).build())
    plan = pull(ex)
    f = plan.files[ZED_FILE]
    assert f.vendor_name == "Zed Rebar" and f.vendor_id == 4730 and f.work_package_name == "Reinforcing steel"
    assert [(l.item_number, l.line_name, l.unit_price, l.folded_into) for l in f.lines] == [
        ("61", "Rebar furnished and placed", 1.70, None), ("61", "Couplers", None, "Rebar furnished and placed")]
    assert f.notes.endswith("review: BidSheet.ai prices item 61 as one line; split by hand if the vendor's document does")
    assert one(plan.ops, kind="write_file").note == f"new quote file {ZED_FILE} (BidSheet.ai quote 57 rev 1)"
    assert f.amount == 1700.0 and f.quote_date is None and f.quote_ref is None
    assert f.lines[0].schedule_name == "Base" and f.lines[0].quantity == 1000
    assert plan.ops[0].id == "u1" and plan.direction == "pull" and plan.backups == []
    assert plan.spec_changes == {}
    ups = dict(plan.sidecar_updates)
    assert ups[f"packages.Reinforcing steel.quotes.{ZED_FILE}.quote_id"] == 57
    assert ups[f"packages.Reinforcing steel.quotes.{ZED_FILE}.lines.61"] == 950


def test_revised_bm_quote_rewrites_the_file_and_keeps_a_backup():
    plan = pull(acme_export(), acme_sidecar(), [(ACME_FILE, acme_rebar(), "sha-acme")])
    assert plan.files[ACME_FILE].lines[0].unit_price == 1.60
    assert plan.backups == [ACME_FILE]
    assert one(plan.ops, kind="write_file").note == (
        f"rewrite quote file {ACME_FILE} (BidSheet.ai quote 55 rev 1 -> rev 2)")


def test_rewrite_keeps_the_files_local_fields():
    local = replace(acme_rebar(), notes="Price good 30 days", surcharge=0.03, is_dbe=True,
                    contact_info="Sam, 555-0100")
    raw = builder().quote(
        "Reinforcing steel", 55, "Acme Rebar", 4722, revision=2, amount=1600.0,
        lines=[{"item_number": "61", "line_id": 901, "unit_price": 1.60, "quantity": 1000}]).build()
    raw["packages"][0]["quotes"][0]["notes"] = "BidSheet.ai notes"
    ex = BmExport.from_dict(raw)
    f = pull(ex, acme_sidecar(), [(ACME_FILE, local, "sha-acme")]).files[ACME_FILE]
    assert (f.conditions, f.quote_ref, f.quote_date, f.surcharge) == (
        {"Couplers included": "yes"}, "Q-100", "2026-10-27", 0.03)
    assert (f.is_dbe, f.contact_info) == (True, "Sam, 555-0100")
    assert f.notes == ("Price good 30 days\nreview: BidSheet.ai prices item 61 as one line; "
                       "split by hand if the vendor's document does")
    assert f.lines[0].unit_price == 1.60 and f.amount == 1600.0 and f.vendor_id == 4722
    again = pull(ex, acme_sidecar(), [(ACME_FILE, replace(local, notes=f.notes), "sha-acme")]).files[ACME_FILE]
    assert again.notes == f.notes                     # the review note is not added twice


def test_unchanged_bm_quote_writes_nothing():
    plan = pull(acme_export(revision=1), acme_sidecar(), [(ACME_FILE, acme_rebar(), "sha-acme")])
    assert plan.files == {} and plan.ops == [] and plan.sidecar_updates == []


def test_missing_bm_quote_is_a_notice_and_the_file_stays():
    ex = BmExport.from_dict(builder().build())
    plan = pull(ex, acme_sidecar(), [(ACME_FILE, acme_rebar(), "sha-acme")])
    assert plan.files == {}
    one(plan.entries, kind="notice",
        text=f"{ACME_FILE}: BidSheet.ai quote 55 no longer exists; the file stays")


def test_file_and_bm_both_moved_is_a_conflict():
    files = [(ACME_FILE, acme_rebar(), "sha-edited")]
    plan = pull(acme_export(), acme_sidecar(), files)
    one(plan.entries, kind="conflict")
    assert ACME_FILE not in plan.files
    forced = pull(acme_export(), acme_sidecar(), files, force="bm")
    assert ACME_FILE in forced.files and forced.backups == [ACME_FILE]


def test_unsynced_file_matching_by_vendor_is_left_unless_forced():
    files = [(ACME_FILE, acme_rebar(), "sha-acme")]
    plan = pull(acme_export(), Sidecar(), files)
    assert plan.files == {}
    one(plan.entries, kind="notice", text=f"{ACME_FILE}: no sidecar record; matches BidSheet.ai quote 55 "
                                          "(revision 2) by vendor name; not pulled (force bm pulls it)")
    forced = pull(acme_export(), Sidecar(), files, force="bm")
    assert list(forced.files) == [ACME_FILE] and forced.backups == [ACME_FILE]


def test_write_pull_writes_files_backup_and_sidecar(tmp_path):
    qdir = tmp_path / "quotes"
    qdir.mkdir()
    write_quote_file(qdir / ACME_FILE, acme_rebar())
    spec_path = tmp_path / "s.estimate.yaml"
    spec_path.write_text(yaml.safe_dump(spec_two_packages(), sort_keys=False))
    spec_before = spec_path.read_text()
    sidecar_path = tmp_path / "s.bm-sync.json"
    acme_sidecar(sha=file_sha(qdir / ACME_FILE)).save(sidecar_path)
    plan = pull(acme_export(), Sidecar.load(sidecar_path),
                [(ACME_FILE, load_quote_file(qdir / ACME_FILE), file_sha(qdir / ACME_FILE))])
    wrote = write_pull(plan, spec_path, qdir, sidecar_path)
    baks = list(qdir.glob(f"{ACME_FILE}.bak-*"))
    assert [b.name for b in baks] == [f"{ACME_FILE}.bak-20261029-151000"]
    assert load_quote_file(baks[0]) == acme_rebar()
    assert load_quote_file(qdir / ACME_FILE) == plan.files[ACME_FILE]
    sc = Sidecar.load(sidecar_path)
    qs = sc.packages["Reinforcing steel"].quotes[ACME_FILE]
    assert (qs.quote_id, qs.revision, qs.vendor_id, qs.lines) == (55, 2, 4722, {"61": 901})
    assert qs.file_sha == file_sha(qdir / ACME_FILE)
    assert sc.packages["Reinforcing steel"].synced_at == NOW
    assert spec_path.read_text() == spec_before            # no spec changes, spec untouched
    assert set(wrote) == {str(baks[0]), str(qdir / ACME_FILE), str(sidecar_path)}


def test_write_pull_applies_spec_changes_to_the_package(tmp_path):
    spec_path = tmp_path / "s.estimate.yaml"
    spec_path.write_text(yaml.safe_dump(spec_two_packages(), sort_keys=False))
    plan = pull(BmExport.from_dict(builder().build()))
    plan.spec_changes = {"Reinforcing steel": {"selected": "Acme Rebar", "pinned": True, "picks": {}}}
    wrote = write_pull(plan, spec_path, tmp_path / "quotes", tmp_path / "s.bm-sync.json")
    pkg = yaml.safe_load(spec_path.read_text())["work_packages"][0]
    assert (pkg["selected"], pkg["pinned"]) == ("Acme Rebar", True) and "picks" not in pkg
    assert yaml.safe_load(spec_path.read_text())["work_packages"][1]["selected"] == "ARR"
    assert wrote == [str(spec_path)]


# ---------- the choice (task 9) ----------

RS = "Reinforcing steel"
ACME_LINES = [{"item_number": "61", "line_id": 901, "unit_price": 1.60, "quantity": 1000},
              {"item_number": "62", "line_id": 902, "unit_price": 50.0, "quantity": 1}]
BOLT_LINES = [{"item_number": "61", "line_id": 911, "unit_price": 1.70, "quantity": 1000},
              {"item_number": "62", "line_id": 912, "unit_price": 55.0, "quantity": 1}]


def spec_rs_two_items(**choice) -> dict:
    """The fixture spec with items 61 and 62 both in the reinforcing steel package."""
    spec = spec_two_packages()
    spec["items"][1]["labor"][0]["lines"].append(
        {"cost_type": "subcontract", "name": "Dowels", "qty": 1, "uom": "LS", "unit_price": 60,
         "source": "quote", "package": RS})
    spec["work_packages"][0].update({"items": ["61", "62"], **choice})
    return spec


def choice_export(carry_mode="pinned", selected_quote=None, acme_allocs=(), bolt_allocs=(), bolt=True):
    b = (export_builder().package(RS, 273, {"61": 7001, "62": 7003}, carry_mode=carry_mode,
                                  selected_quote=selected_quote)
         .package("Ready-mix concrete", 274, {"62": 7002}))
    b.quote(RS, 55, "Acme Rebar", 4722, amount=1650.0, lines=ACME_LINES, allocations=acme_allocs)
    if bolt:
        b.quote(RS, 56, "Bolt Rebar", 4723, amount=1755.0, lines=BOLT_LINES, allocations=bolt_allocs)
    return BmExport.from_dict(b.build())


def alloc(allocation_id, line_id, **kw):
    return {"allocation_id": allocation_id, "quote_line_item_id": line_id, "allocation_type": "full", **kw}


def pull_choice(ex, spec=None, sc=None, **kw):
    return plan_pull(spec or spec_rs_two_items(), [], ex, sc or Sidecar(), spec_name="s", now=NOW, **kw)


ACME_SQ = {"id": 55, "vendor_name": "Acme Rebar", "vendor_id": 4722, "revision": 1, "value": "1650.00"}


def test_automatic_carry_writes_nothing_and_reports():
    plan = pull_choice(choice_export("automatic", ACME_SQ))
    assert plan.spec_changes == {}
    one(plan.entries, kind="notice", text="Reinforcing steel: BidSheet.ai carries Acme Rebar automatically "
                                          "(lowest, $1,650.00); the workbook carries ARR")
    assert not [o for o in plan.ops if o.kind == "write_spec"]
    none = pull_choice(choice_export("automatic"))
    assert none.spec_changes == {} and not [e for e in none.entries if "automatically" in e.text]


def test_pinned_vendor_writes_selected_and_pinned():
    plan = pull_choice(choice_export(selected_quote=ACME_SQ))
    assert plan.spec_changes[RS] == {"selected": "Acme Rebar", "pinned": True, "picks": {}}
    op = one(plan.ops, kind="write_spec")
    assert op.tool == "" and op.package == RS and "Acme Rebar" in op.note and RS in op.note
    ups = dict(plan.sidecar_updates)
    assert ups[f"packages.{RS}.spec_choice"] == {"selected": "Acme Rebar", "pinned": True, "picks": {}}
    assert ups[f"packages.{RS}.bm_choice"] == {"carry_mode": "pinned", "selected_quote_id": 55,
                                               "hand_items": []}
    assert ups[f"packages.{RS}.synced_at"] == NOW


def test_pinned_self_perform():
    plan = pull_choice(choice_export(), sc=None)
    assert plan.spec_changes[RS] == {"selected": "ARR", "pinned": True, "picks": {}}


def test_hand_allocations_whole_vendor_becomes_selected():
    ex = choice_export(acme_allocs=[alloc(1, 901), alloc(2, 902)])
    assert pull_choice(ex).spec_changes[RS] == {"selected": "Acme Rebar", "pinned": True, "picks": {}}


def test_hand_allocations_subset_becomes_picks():
    ex = choice_export(acme_allocs=[alloc(1, 901)])
    assert pull_choice(ex).spec_changes[RS] == {"selected": "ARR", "pinned": True,
                                                "picks": {"61": "Acme Rebar"}}
    ex = choice_export(acme_allocs=[alloc(1, 901)], bolt_allocs=[alloc(2, 912)])
    assert pull_choice(ex).spec_changes[RS] == {"selected": "ARR", "pinned": True,
                                                "picks": {"61": "Acme Rebar", "62": "Bolt Rebar"}}


def test_round_trip_is_a_no_op():
    spec = spec_rs_two_items(selected="ARR", pinned=True, picks={"61": "Acme Rebar"})
    plan = pull_choice(choice_export(acme_allocs=[alloc(1, 901)]), spec)
    assert plan.spec_changes == {} and not [o for o in plan.ops if o.kind == "write_spec"]
    # the same effective sources spelled another way: every item to Acme by picks
    spec = spec_rs_two_items(selected="ARR", pinned=True, picks={"61": "Acme Rebar", "62": "Acme Rebar"})
    assert pull_choice(choice_export(acme_allocs=[alloc(1, 901), alloc(2, 902)]), spec).spec_changes == {}
    # not pinned yet: the pin is written
    spec = spec_rs_two_items(selected="Acme Rebar")
    assert pull_choice(choice_export(selected_quote=ACME_SQ), spec).spec_changes[RS]["pinned"] is True


def test_accepted_alternate_is_a_notice():
    ex = choice_export(acme_allocs=[alloc(1, 901), alloc(2, 902, accept_alternate=True)])
    plan = pull_choice(ex)
    one(plan.entries, kind="notice",
        text="Reinforcing steel: an alternate allocation on item 62 has no spec form; nothing written")
    assert plan.spec_changes[RS] == {"selected": "ARR", "pinned": True, "picks": {"61": "Acme Rebar"}}


def test_allocation_on_a_superseded_quote_line_is_a_notice():
    b = export_builder().package(RS, 273, {"61": 7001, "62": 7003}, carry_mode="pinned")
    b.quote(RS, 54, "Acme Rebar", 4722, lines=[{"item_number": "61", "line_id": 801, "unit_price": 1.7}],
            allocations=[alloc(9, 801)], is_current=False)
    b.quote(RS, 55, "Acme Rebar", 4722, revision=2, lines=ACME_LINES, allocations=[alloc(1, 902)])
    plan = pull_choice(BmExport.from_dict(b.build()))
    one(plan.entries, kind="notice",
        text="Reinforcing steel: allocation 9 points at a superseded quote line; nothing written for it")
    assert plan.spec_changes[RS] == {"selected": "ARR", "pinned": True, "picks": {"62": "Acme Rebar"}}


def conflict_sidecar() -> Sidecar:
    sc = Sidecar(1234, 100)
    ps = sc.package(RS)
    ps.spec_choice = {"selected": "ARR", "pinned": False, "picks": {}}
    ps.bm_choice = {"carry_mode": "automatic", "selected_quote_id": None, "hand_items": []}
    return sc


def test_conflict_when_both_moved_and_force_bm():
    spec = spec_rs_two_items(selected="Bolt Rebar", pinned=True)
    ex = choice_export(selected_quote=ACME_SQ)
    plan = pull_choice(ex, spec, conflict_sidecar())
    c = one(plan.entries, kind="conflict")
    assert c.package == RS and "spec: Bolt Rebar" in c.text and "BidSheet.ai: Acme Rebar (pinned)" in c.text
    assert plan.spec_changes == {} and not [o for o in plan.ops if o.kind == "write_spec"]
    forced = pull_choice(ex, spec, conflict_sidecar(), force="bm")
    assert forced.spec_changes[RS] == {"selected": "Acme Rebar", "pinned": True, "picks": {}}
    assert not [e for e in forced.entries if e.kind == "conflict"]
    # only BidSheet.ai moved: no conflict, the choice is pulled
    moved = pull_choice(ex, spec_rs_two_items(), conflict_sidecar())
    assert moved.spec_changes[RS]["selected"] == "Acme Rebar"
    # no baseline: no conflict
    assert pull_choice(ex, spec).spec_changes[RS]["selected"] == "Acme Rebar"


def test_unmoved_bm_choice_does_not_overwrite_a_spec_edit():
    sc = conflict_sidecar()
    sc.packages[RS].bm_choice = {"carry_mode": "pinned", "selected_quote_id": 55, "hand_items": []}
    plan = pull_choice(choice_export(selected_quote=ACME_SQ), spec_rs_two_items(selected="Bolt Rebar"), sc)
    assert plan.spec_changes == {} and not [e for e in plan.entries if e.kind == "conflict"]


def test_write_pull_rewrites_spec_keeping_comments(tmp_path):
    spec_path = tmp_path / "s.estimate.yaml"
    spec_path.write_text("# keep me\n" + yaml.safe_dump(spec_rs_two_items(), sort_keys=False))
    sidecar_path = tmp_path / "s.bm-sync.json"
    plan = pull_choice(choice_export(acme_allocs=[alloc(1, 901)], bolt=False))
    wrote = write_pull(plan, spec_path, tmp_path / "quotes", sidecar_path)
    text = spec_path.read_text()
    assert "# keep me" in text and str(spec_path) in wrote
    pkg = yaml.safe_load(text)["work_packages"][0]
    assert pkg["pinned"] is True and pkg["selected"] == "ARR" and pkg["picks"] == {"61": "Acme Rebar"}
    ps = Sidecar.load(sidecar_path).packages[RS]
    assert ps.spec_choice == {"selected": "ARR", "pinned": True, "picks": {"61": "Acme Rebar"}}
    assert ps.bm_choice == {"carry_mode": "pinned", "selected_quote_id": None, "hand_items": ["61"]}


def test_no_op_pull_refreshes_a_stale_baseline():
    spec = spec_rs_two_items(selected="Acme Rebar", pinned=True)
    plan = pull_choice(choice_export(selected_quote=ACME_SQ), spec, conflict_sidecar())
    assert plan.spec_changes == {} and not [o for o in plan.ops if o.kind == "write_spec"]
    ups = dict(plan.sidecar_updates)
    assert ups[f"packages.{RS}.spec_choice"] == {"selected": "Acme Rebar", "pinned": True, "picks": {}}
    assert ups[f"packages.{RS}.bm_choice"] == {"carry_mode": "pinned", "selected_quote_id": 55,
                                               "hand_items": []}
    sc = Sidecar(1234, 100)
    sc.package(RS).spec_choice = {"selected": "Acme Rebar", "pinned": True, "picks": {}}
    sc.package(RS).bm_choice = {"carry_mode": "pinned", "selected_quote_id": 54, "hand_items": []}
    ups = dict(pull_choice(choice_export(selected_quote=ACME_SQ), spec, sc).sidecar_updates)
    assert f"packages.{RS}.spec_choice" not in ups and f"packages.{RS}.bm_choice" in ups


def test_carried_quote_without_vendor_name():
    sq = {"id": 55, "vendor_id": 4722, "revision": 1, "value": "1650.00"}
    plan = pull_choice(choice_export(selected_quote=sq))
    assert plan.spec_changes[RS] == {"selected": "Acme Rebar", "pinned": True, "picks": {}}
    plan = pull_choice(choice_export(selected_quote={**sq, "id": 99}))
    assert plan.spec_changes == {}
    one(plan.entries, kind="notice", text="Reinforcing steel: carried quote 99 has no vendor name; nothing written")


def _derived_export(revision=2):
    from estimating_tools.estimate_spec.bm_sync.plan_push import DERIVED_AMOUNT_NOTE
    raw = builder().quote(
        "Reinforcing steel", 55, "Acme Rebar", 4722, revision=revision, amount=1600.0,
        lines=[{"item_number": "61", "line_id": 901, "unit_price": 1.60, "quantity": 1000}]).build()
    raw["packages"][0]["quotes"][0]["notes"] = f"{DERIVED_AMOUNT_NOTE}\nCouplers included: yes"
    return BmExport.from_dict(raw), DERIVED_AMOUNT_NOTE


def test_a_derived_amount_never_lands_in_a_file():
    """Probe E (ruling 42): BidSheet.ai's amount was derived by the push; the file states none."""
    ex, note = _derived_export()
    local = replace(acme_rebar(), amount=None)
    rewrite = pull(ex, acme_sidecar(), [(ACME_FILE, local, "sha-acme")]).files[ACME_FILE]
    assert rewrite.amount is None
    new = pull(ex).files[ACME_FILE]
    assert new.amount is None
    assert note not in (new.notes or "") and "Couplers included: yes" in new.notes
