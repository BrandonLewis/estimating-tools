"""Parts and revisions: a second document from a vendor already on file."""
import pytest
import yaml

from estimating_tools.quotes.files import load_quote_file
from estimating_tools.quotes.intake.importer import import_results, merge_part
from estimating_tools.quotes.intake.inventory import Inventory, inbox_dir_for, state_dir_for
from estimating_tools.quotes.intake.scan import scan_inbox
from estimating_tools.quotes.model import CanonicalQuote, QuoteLine
from estimating_tools.quotes.tests._intake import QUOTE_TEXT, make_pdf, spec_on_disk

HAUL = "Haul, import + export"
HAUL_LINE = {"description": "Haul import/export", "item_number": "2", "line_name": HAUL,
             "unit_price": 16.5, "unit": "CY"}
FILE = "dirt-movers--hauling.json"


@pytest.fixture
def env(tmp_path):
    spec_path = spec_on_disk(tmp_path)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    state = state_dir_for(spec_path, spec)
    inbox = inbox_dir_for(spec_path, spec)
    make_pdf(inbox / "a.pdf", [QUOTE_TEXT])
    make_pdf(inbox / "b.pdf", [QUOTE_TEXT + "Revised quote\n"])
    inv = Inventory.load(state)
    scan_inbox(inv, inbox, state)

    class Env:
        pass
    e = Env()
    e.spec, e.inv, e.state = spec, inv, state
    by_name = {d.file_name: d.sha256 for d in inv}
    e.a, e.b = by_name["a.pdf"], by_name["b.pdf"]
    assert e.a != e.b
    e.quotes = tmp_path / "quotes"
    return e


def result(sha, **overrides):
    res = {"sha256": sha, "doc_type": "quote", "vendor_name": "Dirt Movers",
           "work_package_name": "Hauling", "quote_date": "2026-10-20",
           "lines": [dict(HAUL_LINE)]}
    res.update(overrides)
    return res


def run(env, *results, write=True):
    return import_results(env.inv, env.spec, env.quotes,
                          {"stage": "extract", "schema_version": 1, "results": list(results)},
                          write=write, batch_name="b1.json")


def backups(env, name=FILE):
    return sorted(env.quotes.glob(f"{name}.bak-*"))


def priced(price):
    return [dict(HAUL_LINE, unit_price=price)]


def test_a_same_date_part_is_unioned_into_the_one_file(env):
    run(env, result(env.a, quote_ref="Q1", conditions={"Fuel surcharge": "4%"}))
    before = (env.quotes / FILE).read_bytes()
    report = run(env, result(env.b, quote_ref="Q1 p2", conditions={"Dump fees": "included"}))
    q = load_quote_file(env.quotes / FILE)
    (line,) = q.lines
    assert line.unit_price == 16.5
    assert q.conditions == {"Fuel surcharge": "4%", "Dump fees": "included"}
    assert q.quote_ref == "Q1; Q1 p2" and q.quote_date == "2026-10-20"
    doc = env.inv.get(env.b)
    assert doc.status == "extracted"
    assert doc.results[0]["part_of"] == FILE
    assert report.written == [f"{FILE} (Dirt Movers / Hauling, part)"]
    assert report.revised == [] and report.held == []
    (bak,) = backups(env)
    assert bak.read_bytes() == before
    assert Inventory.load(env.state).get(env.b).results[0]["part_of"] == FILE


def test_a_conflicting_part_is_held_and_the_file_is_untouched(env):
    run(env, result(env.a))
    before = (env.quotes / FILE).read_bytes()
    report = run(env, result(env.b, lines=priced(15.0)))
    doc = env.inv.get(env.b)
    assert (doc.status, doc.reason) == (
        "held", f"conflicts with the quote on file on item 2 line '{HAUL}'")
    assert len(report.held) == 1 and report.written == []
    assert (env.quotes / FILE).read_bytes() == before
    assert backups(env) == []


def test_a_newer_revision_rewrites_with_a_backup_and_reports_the_move(env):
    run(env, result(env.a))
    report = run(env, result(env.b, quote_date="2026-10-22", lines=priced(15.0)))
    assert load_quote_file(env.quotes / FILE).lines[0].unit_price == 15.0
    (bak,) = backups(env)
    assert load_quote_file(bak).lines[0].unit_price == 16.5
    doc = env.inv.get(env.b)
    assert doc.status == "extracted"
    assert doc.results[0]["supersedes"] == env.a
    assert doc.results[0]["quote_file"] == FILE
    assert report.revised == [
        f"{FILE}: Dirt Movers revised Hauling (carried): 7,590.00 → 6,900.00"]
    assert report.written == []
    assert report.summary().startswith("0 written, 1 revised")


def test_a_revision_that_drops_a_line_names_it(env):
    run(env, result(env.a))
    out = {"description": "Haul import/export", "item_number": "2", "line_name": HAUL,
           "is_included": False, "exclusion_note": "by others"}
    report = run(env, result(env.b, quote_date="2026-10-22", lines=[out]))
    assert report.revised == [
        f"{FILE}: Dirt Movers revised Hauling (carried): 7,590.00 → 0.00; dropped {HAUL}"]


def test_a_not_carried_vendor_says_so(env):
    env.spec["work_packages"][0]["selected"] = "ARR"
    run(env, result(env.a))
    report = run(env, result(env.b, quote_date="2026-10-22", lines=priced(15.0)))
    assert report.revised == [
        f"{FILE}: Dirt Movers revised Hauling (not carried): 7,590.00 → 6,900.00"]


def test_an_older_document_is_held_and_never_written(env):
    run(env, result(env.a))
    before = (env.quotes / FILE).read_bytes()
    report = run(env, result(env.b, quote_date="2026-10-18", lines=priced(15.0)))
    doc = env.inv.get(env.b)
    assert (doc.status, doc.reason) == ("held", "older than the quote on file (2026-10-20)")
    assert report.written == [] and report.revised == []
    assert (env.quotes / FILE).read_bytes() == before and backups(env) == []


def test_a_dated_document_supersedes_an_undated_file_and_not_the_reverse(env):
    run(env, result(env.a, quote_date=None))
    report = run(env, result(env.b, lines=priced(15.0)))
    assert len(report.revised) == 1
    assert load_quote_file(env.quotes / FILE).quote_date == "2026-10-20"

    for p in env.quotes.glob(f"{FILE}*"):
        p.unlink()
    for doc in env.inv:
        doc.results.clear()
    run(env, result(env.a))
    report = run(env, result(env.b, quote_date=None, lines=priced(15.0)))
    assert env.inv.get(env.b).reason == "older than the quote on file (2026-10-20)"
    assert report.revised == [] and load_quote_file(env.quotes / FILE).lines[0].unit_price == 16.5


def test_the_same_vendor_on_two_packages_keeps_two_files(env):
    run(env, result(env.a))
    valves = result(env.b, work_package_name="Valves", quote_date="2026-10-22",
                    lines=[{"description": "Valve boxes", "item_number": "3",
                            "line_name": "Valve boxes (subcontract)", "unit_price": 900}])
    report = run(env, valves)
    assert report.written == ["dirt-movers--valves.json (Dirt Movers / Valves)"]
    assert report.revised == []
    assert load_quote_file(env.quotes / FILE).lines[0].unit_price == 16.5
    assert (env.quotes / "dirt-movers--valves.json").exists()
    assert backups(env) == []


def test_a_part_and_a_revision_in_one_run_build_on_each_other(env):
    report = run(env, result(env.a), result(env.b, quote_date="2026-10-22", lines=priced(15.0)))
    assert report.written == [f"{FILE} (Dirt Movers / Hauling)"]
    assert report.revised == [
        f"{FILE}: Dirt Movers revised Hauling (carried): 7,590.00 → 6,900.00"]
    assert env.inv.get(env.b).results[0]["supersedes"] == env.a


def test_a_dry_run_revision_touches_nothing(env):
    run(env, result(env.a))
    env.inv.save()
    before, inv_before = (env.quotes / FILE).read_bytes(), env.inv.path.read_bytes()
    report = run(env, result(env.b, quote_date="2026-10-22", lines=priced(15.0)), write=False)
    assert len(report.revised) == 1
    assert (env.quotes / FILE).read_bytes() == before and backups(env) == []
    assert env.inv.path.read_bytes() == inv_before
    assert env.inv.get(env.b).results == []


def test_importing_the_same_results_twice_changes_nothing(env):
    res = result(env.a, lines=[dict(HAUL_LINE, quantity_basis="loose CY")])
    run(env, res)
    part = result(env.b, quote_ref="P2", lines=[dict(HAUL_LINE, quantity_basis="bank CY")])
    run(env, part)                                               # a part: one backup
    before, baks = (env.quotes / FILE).read_bytes(), backups(env)
    assert len(baks) == 1 and "bank CY" in load_quote_file(env.quotes / FILE).notes
    report = run(env, res, part)
    assert report.written == [] and report.revised == [] and report.held == []
    assert report.unchanged == [f"{FILE} (Dirt Movers / Hauling): already on file"] * 2
    assert (env.quotes / FILE).read_bytes() == before and backups(env) == baks
    assert len(env.inv.get(env.a).results) == 1 and len(env.inv.get(env.b).results) == 1


def test_a_same_date_part_that_adds_nothing_is_unchanged(env):
    run(env, result(env.a))
    before = (env.quotes / FILE).read_bytes()
    report = run(env, result(env.b))
    assert report.written == [] and backups(env) == []
    assert report.unchanged == [f"{FILE} (Dirt Movers / Hauling): already on file"]
    assert (env.quotes / FILE).read_bytes() == before
    doc = env.inv.get(env.b)
    assert doc.status == "extracted" and doc.results[0]["part_of"] == FILE
    assert run(env, result(env.b)).unchanged and len(doc.results) == 1


def test_merge_part_does_not_repeat_a_parts_notes():
    existing = _q([], notes="first\npart cccccccc:\nsecond")
    merged, _ = merge_part(existing, _q([], notes="second"), "c" * 64)
    assert merged.notes == existing.notes


def _q(lines, **kw):
    return CanonicalQuote(vendor_name="Dirt Movers", work_package_name="Hauling", lines=lines,
                          **kw)


def _l(price, **kw):
    return QuoteLine(schedule_name="Base", item_number="2", unit_price=price, **kw)


def test_merge_part_unions_lines_and_keeps_the_existing_header():
    existing = _q([_l(16.5)], quote_date="2026-10-20", notes="first",
                  conditions={"Fuel surcharge": "4%"})
    valves = QuoteLine(schedule_name="Base", item_number="3", unit_price=900)
    part = _q([_l(16.5), valves], quote_date="2026-10-20", notes="second",
              conditions={"Fuel surcharge": "5%", "Dump fees": "incl"}, quote_ref="P2")
    merged, reason = merge_part(existing, part, "c" * 64)
    assert reason is None
    assert [(ln.item_number, ln.unit_price) for ln in merged.lines] == [("2", 16.5), ("3", 900)]
    assert merged.conditions == {"Fuel surcharge": "4%; 5%", "Dump fees": "incl"}
    assert merged.quote_ref == "P2" and merged.quote_date == "2026-10-20"
    assert merged.notes.startswith("first\n") and "second" in merged.notes
    assert existing.lines == [_l(16.5)]          # pure: the inputs are not changed


def test_merge_part_keeps_an_alternate_beside_the_priced_line_on_its_key():
    existing = _q([_l(16.5, line_name=HAUL)])
    part = _q([_l(18.0, line_name=HAUL, is_alternate=True)])
    merged, reason = merge_part(existing, part, "c" * 64)
    assert reason is None and len(merged.lines) == 2


def test_merge_part_returns_the_existing_quote_on_a_conflict():
    existing = _q([_l(16.5, line_name=HAUL)])
    merged, reason = merge_part(existing, _q([_l(16.5, line_name=HAUL, is_included=False)]),
                                "c" * 64)
    assert merged is existing
    assert reason == f"conflicts with the quote on file on item 2 line '{HAUL}'"


def test_a_requeued_document_reimported_with_a_corrected_price_replaces_its_own_quote(env):
    run(env, result(env.a, lines=priced(61.5)))                  # a misread price
    env.inv.requeue(env.inv.get(env.a))
    assert env.inv.get(env.a).requeued_from[0]["quote_file"] == FILE
    report = run(env, result(env.a))
    assert report.held == [] and report.written == []
    assert report.revised == [
        f"{FILE}: Dirt Movers revised Hauling (carried): 28,290.00 → 7,590.00"]
    assert load_quote_file(env.quotes / FILE).lines[0].unit_price == 16.5
    (bak,) = backups(env)
    assert load_quote_file(bak).lines[0].unit_price == 61.5
    doc = env.inv.get(env.a)
    assert doc.status == "extracted" and doc.results[0]["supersedes"] == env.a
    saved = Inventory.load(env.state).get(env.a)
    assert saved.requeued_from and saved.results[0]["supersedes"] == env.a
    # The next document of the same date is a part of the corrected quote.
    report = run(env, result(env.b, conditions={"Dump fees": "included"}))
    assert report.written == [f"{FILE} (Dirt Movers / Hauling, part)"]


def test_a_resaved_corrected_document_replaces_the_one_it_supersedes(env, tmp_path):
    run(env, result(env.a, lines=priced(61.5)))
    make_pdf(tmp_path / "inbox" / "a.pdf", [QUOTE_TEXT + "Corrected\n"])
    scan_inbox(env.inv, tmp_path / "inbox", env.state)
    old = env.inv.get(env.a)
    new = old.superseded_by
    assert new is not None and new != env.a
    report = run(env, result(new))                               # the same quote date
    assert report.held == [] and len(report.revised) == 1
    assert load_quote_file(env.quotes / FILE).lines[0].unit_price == 16.5
    assert load_quote_file(backups(env)[0]).lines[0].unit_price == 61.5
    assert env.inv.get(new).results[0]["supersedes"] == env.a


def test_a_requeued_part_of_a_union_file_is_held_with_the_requeue_hint(env):
    run(env, result(env.a))
    run(env, result(env.b, conditions={"Dump fees": "included"}))   # a part
    before = (env.quotes / FILE).read_bytes()
    env.inv.requeue(env.inv.get(env.b))
    report = run(env, result(env.b, lines=priced(15.0)))
    doc = env.inv.get(env.b)
    assert (doc.status, doc.reason) == (
        "held", f"the file holds parts from other documents; requeue them too: {env.a[:8]}")
    assert len(report.held) == 1 and report.revised == []
    assert (env.quotes / FILE).read_bytes() == before
    # Requeue the other part too and both go back in.
    env.inv.requeue(env.inv.get(env.a))
    report = run(env, result(env.a), result(env.b, lines=priced(16.5),
                                            conditions={"Dump fees": "by others"}))
    assert report.held == [] and len(report.revised) == 1
    assert report.written == [f"{FILE} (Dirt Movers / Hauling, part)"]
    assert load_quote_file(env.quotes / FILE).conditions["Dump fees"] == "by others"


def test_a_part_keeps_both_review_texts(env):
    run(env, result(env.a, needs_review=["handwritten total"]))
    run(env, result(env.b, quote_ref="P2", needs_review=["page 2 faint"]))
    review = load_quote_file(env.quotes / FILE).conditions["Review"]
    assert review == "handwritten total; page 2 faint"


def test_a_lump_sum_part_beside_an_itemised_file_is_kept_as_a_printed_total(env):
    run(env, result(env.a))
    report = run(env, result(env.b, lines=[], total_amount=8740))
    q = load_quote_file(env.quotes / FILE)
    assert q.amount is None and q.lines[0].unit_price == 16.5
    reason = "lump sum 8,740.00 from a second document; not merged as amount"
    assert q.conditions["Printed total"] == "8,740.00"
    assert reason in q.conditions["Review"]
    assert report.written == [f"{FILE} (Dirt Movers / Hauling, part)"]
    assert report.review == [f"{FILE}: {reason}"]
    assert env.inv.get(env.b).results[0]["needs_review"] == [reason]


def test_two_lump_sums_of_the_same_date_that_differ_conflict(env):
    run(env, result(env.a, lines=[], total_amount=8740))
    before = (env.quotes / FILE).read_bytes()
    report = run(env, result(env.b, lines=[], total_amount=9000))
    assert env.inv.get(env.b).reason == (
        "conflicts with the quote on file on the lump sum (8,740.00 on file, 9,000.00 in this part)")
    assert len(report.held) == 1 and (env.quotes / FILE).read_bytes() == before


def test_a_partial_write_cannot_corrupt_the_carried_quote(env, monkeypatch):
    from estimating_tools.quotes.intake import importer

    run(env, result(env.a))
    before = (env.quotes / FILE).read_bytes()
    real = importer.write_quote_file

    def disk_full(path, quote):
        if path.parent == env.quotes:
            path.write_text('{"partial":', encoding="utf-8")
            raise OSError("disk full")
        real(path, quote)

    monkeypatch.setattr(importer, "write_quote_file", disk_full)
    report = run(env, result(env.b, quote_date="2026-10-22", lines=priced(15)))
    assert report.held and env.inv.get(env.b).status == "error"
    assert (env.quotes / FILE).read_bytes() == before
    assert not list(env.quotes.glob("*.tmp"))
