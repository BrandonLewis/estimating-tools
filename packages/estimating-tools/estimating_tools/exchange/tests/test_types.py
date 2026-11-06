from __future__ import annotations

from typing import get_args

import pytest

from estimating_tools.exchange.types import (ApplyResult, BookFacts, NotYet, PatchReport,
                                             ReadResult, Verdict)


def test_verdict_values_match_the_navigator_stamp_kinds():
    assert set(get_args(Verdict)) == {"none", "ok", "newer", "bad"}


def test_apply_result_from_a_plan_dict():
    plan = {"request_id": "r-1", "replayed": False,
            "created": {"new:r1": "resource:41", "new:r2": "resource:42"},
            "versions": {"resource:41": "aaaa", "resource:42": "bbbb"},
            "deleted": [], "warnings": [], "totals": {"before": 1, "after": 2}}
    r = ApplyResult.from_plan(plan, dry_run=False)
    assert r.created == {"new:r1": ("resource", 41), "new:r2": ("resource", 42)}
    assert r.versions == {("resource", 41): "aaaa", ("resource", 42): "bbbb"}
    assert r.request_id == "r-1" and r.dry_run is False and r.replayed is False


def test_apply_result_tolerates_a_plan_without_versions():
    r = ApplyResult.from_plan({"created": {}, "deleted": [], "totals": {}}, dry_run=True)
    assert r.versions == {} and r.request_id is None


def test_read_result_is_one_or_the_other():
    with pytest.raises(ValueError):
        ReadResult(change_set={"ops": []}, problems=["x"])


def test_book_facts_defaults():
    f = BookFacts(path="x.xlsx")
    assert f.properties == {} and f.names == {} and f.sheets == []


def test_not_yet_is_an_exception_with_a_message():
    with pytest.raises(NotYet, match="fieldbook"):
        raise NotYet("fieldbook reads back through est-estimate read-back until roadmap 1.11")


def test_patch_report_counts():
    r = PatchReport(cells_written=3, rows_tagged=2, baseline_replaced=True)
    assert r.text() == "2 row(s) tagged, 3 cell(s) written, baseline replaced"
    assert r.problems == []


def test_patch_report_lists_what_was_not_written_like_a_change_sets_notes():
    r = PatchReport(cells_written=3, rows_tagged=2, baseline_replaced=True,
                    problems=["Crews rows 6-7: crew A's member rows could not be matched to "
                              "BidSheet.ai's -- rebuild the book from BidSheet.ai",
                              "Cost Report row 9: x -- rebuild the book from BidSheet.ai"])
    assert r.text().splitlines() == [
        "2 row(s) tagged, 3 cell(s) written, baseline replaced",
        "",
        "Not written:",
        "  Crews rows 6-7: crew A's member rows could not be matched to BidSheet.ai's -- "
        "rebuild the book from BidSheet.ai",
        "  Cost Report row 9: x -- rebuild the book from BidSheet.ai"]


def test_apply_result_names_a_malformed_ref():
    with pytest.raises(ValueError, match="resource"):
        ApplyResult.from_plan({"created": {"new:r1": "resource"}}, dry_run=False)
    with pytest.raises(ValueError, match="resource:abc"):
        ApplyResult.from_plan({"created": {"new:r1": "resource:abc"}}, dry_run=False)


def test_read_result_states():
    assert ReadResult(change_set={"ops": []}).refused is False
    assert ReadResult(problems=["x"]).refused is True
    with pytest.raises(ValueError):
        ReadResult()


@pytest.mark.parametrize("key,bad", [("created", ["a"]), ("versions", "x"), ("totals", 3),
                                     ("deleted", {"a": 1}), ("warnings", "w")])
def test_apply_result_refuses_a_malformed_plan_shape_with_a_value_error(key, bad):
    with pytest.raises(ValueError, match=key):
        ApplyResult.from_plan({key: bad}, dry_run=True)


def test_change_set_protocol_is_what_the_cli_touches():
    from estimating_tools.exchange.types import ChangeSet
    from estimating_tools.exchange.reader.report import ChangeSet as HeavyBook
    cs = HeavyBook(estimate_id=1, estimate_v="v")
    assert isinstance(cs, ChangeSet)
    assert cs.as_json()["ops"] == [] and cs.text() == "no changes"

    class Bare:
        estimate_id = 1
        ops = []
        rows = []

    assert not isinstance(Bare(), ChangeSet)      # no text(), no as_json()


def test_build_refused_names_its_kind():
    from estimating_tools.exchange.types import BuildRefused
    exc = BuildRefused("style", "no such style pack")
    assert exc.kind == "style" and str(exc) == "no such style pack"
    with pytest.raises(ValueError):
        BuildRefused("colour", "x")


def test_refresh_report_says_what_was_written_or_why_not():
    from estimating_tools.exchange.types import Collision, RefreshReport

    clean = RefreshReport(dry_run=False, baseline_replaced=True, cells_written=3, rows_added=1,
                          written=["Cost Report row 9: line 'CAT 336' quantity 30 -> 32"])
    assert clean.clean
    assert clean.text().startswith("refreshed -- 3 cell(s), 1 row(s) added, 0 removed")
    c = Collision("Cost Report", 9, "line 'CAT 336' Quantity: BidSheet.ai 32, this book 31 "
                                    "(built with 30)")
    assert str(c).startswith("Cost Report row 9: line 'CAT 336' Quantity")
    assert str(Collision("Cost Report", None, "gone")) == "Cost Report: gone"
    blocked = RefreshReport(dry_run=False, baseline_replaced=False, collisions=[c],
                            structural=["item Z9 was added in BidSheet.ai -- rebuild"])
    assert not blocked.clean
    text = blocked.text()
    assert "nothing written" in text and str(c) in text and "Needs a rebuild" in text
    current = RefreshReport(dry_run=False, baseline_replaced=False, current=True)
    assert current.text().startswith("the book is current")


def test_patch_report_lists_its_notes_last():
    from estimating_tools.exchange.types import PatchReport

    report = PatchReport(cells_written=1, rows_tagged=1, baseline_replaced=True,
                         notes=["Checks row 25: no figure now"])
    assert report.text().endswith("Notes:\n  Checks row 25: no figure now")
