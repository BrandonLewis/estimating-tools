"""read_back: refusals, the no-op round trip, and the whole-book findings."""
from __future__ import annotations

import copy

import pytest

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import format_pack as fp
from estimating_tools.estimate_spec.readback import (
    ReadBackRefused, fieldbook_pack, load_workbook, read_back)
from estimating_tools.estimate_spec.tests._fieldbook import (
    DERIVED, LEGACY, build, example_spec, rows_of_kind, simulate_delete_row)


def _saved(wb, tmp_path, name="edited.xlsx"):
    """Save `wb` and open it again, the way read-back opens a file."""
    path = tmp_path / name
    wb.save(path)
    return load_workbook(path)


def _restamp(wb, value):
    (prop,) = [p for p in wb.custom_doc_props.props if p.name == "estimate_format"]
    prop.value = value
    return wb


def test_an_unedited_workbook_reads_back_to_the_same_spec(tmp_path):
    spec = example_spec()
    result = read_back(spec, _saved(build(), tmp_path))
    assert result.spec == spec
    assert not result.changed and not result.blocked
    assert result.findings.needs_rate == {} and result.findings.overwrites == []
    assert spec == example_spec()                       # never mutated


def test_a_workbook_with_no_format_stamp_is_refused(tmp_path):
    wb = B.generate(example_spec(), fieldbook_pack(), stamp=False)
    with pytest.raises(ReadBackRefused, match="no estimate_format property"):
        read_back(example_spec(), _saved(wb, tmp_path))


def test_a_workbook_in_another_format_is_refused():
    with pytest.raises(ReadBackRefused, match="built in the 'demo' format"):
        read_back(example_spec(), _restamp(build(), "demo 1"))


def test_a_derived_pack_workbook_reads_back_with_that_pack(tmp_path):
    pack, spec = fp.load_pack(DERIVED), example_spec()
    wb = B.generate(copy.deepcopy(spec), pack)
    result = read_back(spec, _saved(wb, tmp_path), pack)
    assert result.changed is False and not result.blocked


def test_a_derived_pack_workbook_is_refused_by_the_bundled_pack(tmp_path):
    wb = B.generate(example_spec(), fp.load_pack(DERIVED))
    with pytest.raises(ReadBackRefused, match="built in the 'derived_demo' format") as exc:
        read_back(example_spec(), _saved(wb, tmp_path))
    assert "read-back resolved the 'fieldbook' pack" in str(exc.value)


def test_a_pack_outside_the_fieldbook_lineage_is_refused(tmp_path):
    # The pack cannot build the example spec, so stamp a fieldbook build as
    # its workbook: the lineage is refused before the stamp is even read.
    pack = fp.load_pack(LEGACY)
    wb = _restamp(build(), f"{pack.name} {pack.version}")
    with pytest.raises(ReadBackRefused, match="family") as exc:
        read_back(example_spec(), _saved(wb, tmp_path), pack)
    assert "'legacy_demo' family" in str(exc.value)


def test_a_workbook_from_another_fieldbook_version_is_refused():
    with pytest.raises(ReadBackRefused, match="built with fieldbook 1; this read-back needs "
                                              "fieldbook 2 -- rebuild from the spec"):
        read_back(example_spec(), _restamp(build(), "fieldbook 1"))


def test_the_fieldbook_stamp_is_name_and_version():
    (prop,) = [p for p in build().custom_doc_props.props if p.name == "estimate_format"]
    assert prop.value == "fieldbook 2" == fieldbook_pack().stamp


def test_a_derived_pack_stamp_carries_the_lineage(tmp_path):
    pack = fp.load_pack(DERIVED)
    assert pack.stamp == "derived_demo 1 / fieldbook 2"
    wb = B.generate(example_spec(), pack)
    (prop,) = [p for p in wb.custom_doc_props.props if p.name == "estimate_format"]
    assert prop.value == "derived_demo 1 / fieldbook 2"


@pytest.mark.parametrize("old", ["derived_demo 1", "derived_demo 1 / fieldbook 1",
                                 "derived_demo 2 / fieldbook 2",
                                 "derived_demo 1 / fieldbook 2 / extra 1"])
def test_a_derived_workbook_whose_lineage_differs_is_refused(tmp_path, old):
    # A stamp from before lineage stamps (no base element) or from another
    # base version: the base pack's grid moved under the derived pack.
    pack = fp.load_pack(DERIVED)
    wb = _restamp(B.generate(example_spec(), pack), old)
    with pytest.raises(ReadBackRefused) as exc:
        read_back(example_spec(), _saved(wb, tmp_path), pack)
    assert str(exc.value) == (f"built with {old}; this read-back needs derived_demo 1 / "
                              "fieldbook 2 -- rebuild from the spec")


def test_a_spec_with_other_items_is_refused():
    spec = example_spec()
    del spec["items"][2]
    with pytest.raises(ReadBackRefused, match=r"item sheets \['1 - MOBILIZATION', '2 - 8IN MAIN', "
                                              r"'3 - VALVES'\] are not the spec's"):
        read_back(spec, build())
    spec = example_spec()
    spec["items"][1]["item_no"] = "2A"
    with pytest.raises(ReadBackRefused, match="sheet '2 - 8IN MAIN' is item 2, but the spec puts item 2A there"):
        read_back(spec, build())


def test_an_unreadable_file_is_refused(tmp_path):
    bad = tmp_path / "notes.xlsx"
    bad.write_text("not a workbook", encoding="utf-8")
    with pytest.raises(ReadBackRefused, match="cannot read .*notes.xlsx as an .xlsx workbook"):
        load_workbook(bad)
    with pytest.raises(ReadBackRefused, match="no such file"):
        load_workbook(tmp_path / "missing.xlsx")


def test_a_spec_that_does_not_build_is_refused():
    spec = example_spec()
    spec["items"][1]["labor"][0]["crew"][0]["trade"] = "Asphalt Raker"     # not a pack resource
    with pytest.raises(ReadBackRefused, match="the spec itself does not build"):
        read_back(spec, build())


@pytest.mark.parametrize("bad", [None, "2 - 8IN MAIN", 7, ["a", "list"]],
                         ids=["null", "string", "number", "list"])
def test_a_malformed_item_record_is_refused_not_a_traceback(bad):
    # Copilot review (PR #355): check_items read every item record before the
    # baseline build had validated the spec -- `items: [null]` was an
    # AttributeError traceback, not a refusal.
    spec = example_spec()
    spec["items"][1] = bad
    with pytest.raises(ReadBackRefused, match="the spec itself does not build"):
        read_back(spec, build())


def test_an_item_with_no_item_no_or_sheet_is_refused_not_a_traceback():
    for key in ("item_no", "sheet"):
        spec = example_spec()
        del spec["items"][1][key]
        with pytest.raises(ReadBackRefused):
            read_back(spec, build())


def test_book_sheet_overwrites_and_needs_rate_come_back_from_the_whole_book(tmp_path):
    wb = build()
    wb["Bid Form"]["E6"] = 170
    ws = wb["2 - 8IN MAIN"]
    (crew,) = [r for r in rows_of_kind(ws, "CREW") if ws[f"A{r}"].value == "Pipelayer"][:1]
    ws[f"A{crew}"] = "Truck Driver"                     # a pack resource with no rate row
    result = read_back(example_spec(), _saved(wb, tmp_path))
    f = result.findings
    assert f.changes == ["item 2 · 02-100 · Pipelayer: trade Pipelayer → Truck Driver"]
    assert f.needs_rate == {"Truck Driver": ["item 2 · 02-100"]}
    assert f.overwrites == ["Bid Form!E6 (formula): typed 170 over the formula"]
    assert not result.blocked


def test_a_change_the_pack_would_refuse_is_a_problem():
    wb = build()
    ws = wb["3 - VALVES"]
    simulate_delete_row(ws, rows_of_kind(ws, "TAKEOFF")[0])     # the item's only takeoff row
    result = read_back(example_spec(), wb)
    assert result.findings.changes == [
        "item 3 · takeoff · − takeoff row label Gate valve, count 4, ref C-5 (removed)"]
    assert result.findings.problems == [
        "item 3 has no takeoff rows left -- a line_item item needs at least one\n"
        "  (the updated spec would not build: schema violation: $['items'][2]['takeoff']: "
        "{'kind': 'count', 'units': []} is not valid under any of the given schemas)"]
    assert result.blocked


def test_read_back_never_mutates_its_inputs():
    spec = example_spec()
    before = copy.deepcopy(spec)
    wb = build()
    wb["Markup"]["B5"] = 0.10
    result = read_back(spec, wb)
    assert spec == before
    assert result.spec["markup"]["profit"]["labor"] == 0.10


# --------------------------------------------------------------- bid date

def test_clearing_the_bid_date_removes_the_key_not_a_blank_string():
    wb = build()
    wb["Bid Form"]["B2"] = None
    result = read_back(example_spec(), wb)
    assert result.findings.changes == ["bid date 2026-10-01 → (blank)"]
    assert "bid_date" not in result.spec


def test_free_text_in_the_bid_date_cell_is_a_problem():
    wb = build()
    wb["Bid Form"]["B2"] = "Oct 8"
    result = read_back(example_spec(), wb)
    assert result.findings.problems == ["Bid Form: bid date 'Oct 8' is not a date -- type it as a date"]
    assert result.blocked


def test_a_missing_bid_date_label_row_is_a_notice_not_a_blank_change():
    wb = build()
    wb["Bid Form"]["A2"] = "Start date"             # the label itself is gone
    result = read_back(example_spec(), wb)
    # Retyping the label itself also makes column A no longer match the
    # fresh build's -- scan_against_baseline notices that too, harmlessly.
    assert result.findings.notices == [
        "Bid Form: no 'Bid date' row -- the bid date was not read",
        "Bid Form: rows were added, removed or moved -- not checked for typed-over formulas"]
    assert result.findings.changes == [] and not result.blocked
    assert result.spec.get("bid_date") == "2026-10-01"      # left exactly as it was


# ---------------------------------------------------------- broad exceptions

def test_any_exception_building_the_baseline_is_a_refusal(monkeypatch):
    wb = build()                                     # built before the patch
    import estimating_tools.estimate_spec.build as B_mod

    def boom(*a, **kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(B_mod, "generate", boom)
    with pytest.raises(ReadBackRefused, match="the spec itself does not build: kaboom"):
        read_back(example_spec(), wb)


def test_any_exception_from_the_test_build_is_a_problem(monkeypatch):
    wb = build()                                      # built before the patch
    wb["Markup"]["B5"] = 0.10                         # a real, valid edit
    import estimating_tools.estimate_spec.build as B_mod
    real_generate = B_mod.generate
    calls = []

    def flaky(*a, **kw):
        calls.append(1)
        if len(calls) > 1:                             # 1st call: the baseline build
            raise RuntimeError("kaboom")               # 2nd call: the post-merge test-build
        return real_generate(*a, **kw)

    monkeypatch.setattr(B_mod, "generate", flaky)
    result = read_back(example_spec(), wb)
    assert result.findings.problems == ["the updated spec would not build: kaboom"]
    assert result.blocked


# ---- the spec fingerprint: a stale workbook must not revert newer spec edits ----

def _props(wb) -> dict:
    return {p.name: p.value for p in wb.custom_doc_props.props}


def test_build_stamps_the_specs_fingerprint():
    spec = example_spec()
    assert _props(build(spec))["estimate_spec_sha"] == B.spec_fingerprint(spec)
    assert "estimate_spec_sha" not in _props(B.generate(example_spec(), fieldbook_pack(),
                                                        stamp=False))
    other = example_spec()
    other["markup"]["bond_pct"] = 0.02
    assert B.spec_fingerprint(other) != B.spec_fingerprint(spec)
    # Key order does not matter -- the data does.
    assert B.spec_fingerprint(dict(reversed(list(spec.items())))) == B.spec_fingerprint(spec)


def test_a_workbook_built_from_another_version_of_the_spec_is_a_problem(tmp_path):
    older = example_spec()
    wb = _saved(build(older), tmp_path)
    newer = example_spec()
    newer["markup"]["bond_pct"] = 0.02           # edited since the workbook was built
    result = read_back(newer, wb)
    assert result.blocked
    (problem,) = result.findings.problems
    assert "built from a different version of the spec" in problem and "--force" in problem
    # The report still says what applying it would do: put the old bond back.
    assert result.findings.changes == ["markup · bond_pct 0.02 → 0.012"]


def test_force_applies_a_stale_workbook_with_a_notice(tmp_path):
    newer = example_spec()
    newer["markup"]["bond_pct"] = 0.02
    result = read_back(newer, _saved(build(), tmp_path), force=True)
    assert not result.blocked
    assert any("different version of the spec" in n and "--force" in n
               for n in result.findings.notices)
    assert result.spec["markup"]["bond_pct"] == 0.012


def test_a_workbook_with_no_fingerprint_is_a_problem(tmp_path):
    wb = build()
    wb.custom_doc_props.props = [p for p in wb.custom_doc_props.props
                                 if p.name != "estimate_spec_sha"]
    result = read_back(example_spec(), _saved(wb, tmp_path))
    (problem,) = result.findings.problems
    assert "does not record which version of the spec" in problem


def test_edits_to_text_read_back_ignores_are_notices(tmp_path):
    """The item description and unit and the project name look editable but
    are not inputs: say so, rather than silently dropping the edit -- and a
    retitled Bid Form is not "rows were added, removed or moved"."""
    wb = build()
    ws = wb["2 - 8IN MAIN"]
    ws["B1"], ws["H1"] = "8-inch DIP water main", "FT"
    wb["Bid Form"]["A1"] = "Demo Pipeline Replacement, Phase 2"
    result = read_back(example_spec(), _saved(wb, tmp_path))
    f = result.findings
    assert not result.changed and not result.blocked and f.overwrites == []
    assert f.notices == [
        "2 - 8IN MAIN row 1 (item 2): the item description '8-inch water main' → "
        "'8-inch DIP water main' is not read back -- change it in the spec / bid schedule",
        "2 - 8IN MAIN row 1 (item 2): the item unit 'LF' → 'FT' is not read back -- "
        "change it in the spec / bid schedule",
        "Bid Form!A1: the project name 'Demo Pipeline Replacement' → 'Demo Pipeline "
        "Replacement, Phase 2' is not read back -- change it in the spec"]


def test_a_retitled_bid_form_is_still_scanned_for_typed_over_formulas(tmp_path):
    wb = build()
    wb["Bid Form"]["A1"] = "Renamed"
    wb["Bid Form"]["F9"] = 1
    f = read_back(example_spec(), _saved(wb, tmp_path)).findings
    assert f.overwrites == ["Bid Form!F9 (formula): typed 1 over the formula"]


def test_a_schema_refusal_is_explained_for_the_estimator(tmp_path):
    wb = build()
    ws = wb["3 - VALVES"]
    for name in ("Laborer", "Pipelayer"):
        (r,) = [r for r in rows_of_kind(ws, "CREW") if ws[f"A{r}"].value == name]
        simulate_delete_row(ws, r)
    result = read_back(example_spec(), _saved(wb, tmp_path))
    (problem,) = result.findings.problems
    first, second = problem.split("\n")
    assert first == ("item 3 · task 02-510 has no crew rows left -- every task needs at "
                     "least one crew row")
    assert second.strip() == ("(the updated spec would not build: schema violation: "
                              "$['items'][2]['labor'][0]['crew']: [] should be non-empty)")


def test_a_blocked_read_back_hands_back_the_spec_unchanged(tmp_path):
    """Nothing is half-applied: `.spec` is only the merged spec on success."""
    wb = build()
    wb["Markup"]["B5"] = 0.10                    # a good edit...
    wb["Markup"]["C5"] = "ten"                   # ...and a problem
    result = read_back(example_spec(), _saved(wb, tmp_path))
    assert result.blocked and result.changed
    assert result.spec == example_spec()
