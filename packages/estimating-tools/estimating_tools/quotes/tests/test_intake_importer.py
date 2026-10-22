
from pathlib import Path

import pytest
import yaml

from estimating_tools.estimate_spec.package_frames import build_package_frames
from estimating_tools.quotes.files import load_quote_file
from estimating_tools.quotes.intake.importer import (
    ImportReport, assemble_quote, import_results, is_carried, vendor_total)
from estimating_tools.quotes.intake.batch import package_digest
from estimating_tools.quotes.intake.inventory import Inventory, inbox_dir_for, state_dir_for
from estimating_tools.quotes.intake.scan import scan_inbox
from estimating_tools.quotes.intake.text import recover_text
from estimating_tools.quotes.model import CanonicalQuote, QuoteLine
from estimating_tools.quotes.tests._intake import QUOTE_TEXT, make_pdf, spec_on_disk

HAUL_LINE = {"description": "Haul import/export", "item_number": "2",
             "line_name": "Haul, import + export", "unit_price": 16.5, "unit": "CY"}


@pytest.fixture
def env(tmp_path):
    spec_path = spec_on_disk(tmp_path)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    state = state_dir_for(spec_path, spec)
    inv = Inventory.load(state)
    make_pdf(inbox_dir_for(spec_path, spec) / "dirt-movers.pdf", [QUOTE_TEXT])
    scan_inbox(inv, inbox_dir_for(spec_path, spec), state)
    recover_text(inv, state)
    (doc,) = list(inv)
    assert doc.route == "text"

    class Env:
        pass
    e = Env()
    e.spec, e.inv, e.state, e.sha = spec, inv, state, doc.sha256
    e.quotes = tmp_path / "quotes"
    return e


def result(sha, **overrides):
    res = {"sha256": sha, "doc_type": "quote", "vendor_name": "Dirt Movers",
           "work_package_name": "Hauling", "quote_date": "2026-10-20",
           "lines": [dict(HAUL_LINE)]}
    res.update(overrides)
    return res


def payload(*results):
    return {"stage": "extract", "schema_version": 1, "results": list(results)}


def run(env, *results, write=True):
    return import_results(env.inv, env.spec, env.quotes, payload(*results), write=write,
                          batch_name="b1.json")


def written_quote(env, name="dirt-movers--hauling.json"):
    return load_quote_file(env.quotes / name)


def hauling():
    return package_digest(spec_from_fixture())[0]


def spec_from_fixture():
    from estimating_tools.estimate_spec.tests._fieldbook import packaged_spec
    return packaged_spec()


def assembled(**overrides):
    quote, reasons = assemble_quote(result("a" * 64, **overrides), hauling(), source="q.pdf")
    return quote, reasons


def test_a_quote_result_becomes_a_quote_file_and_an_extracted_record(env):
    report = run(env, result(env.sha))
    q = written_quote(env)
    assert (q.vendor_name, q.work_package_name, q.quote_date) == ("Dirt Movers", "Hauling",
                                                                  "2026-10-20")
    (line,) = q.lines
    assert (line.schedule_name, line.item_number, line.unit_price) == ("Base", "2", 16.5)
    assert line.line_name is None and line.is_included and not line.is_alternate
    doc = env.inv.get(env.sha)
    assert doc.status == "extracted"
    assert doc.results[0]["quote_file"] == "dirt-movers--hauling.json"
    assert doc.results[0]["batch"] == "b1.json"
    assert report.written == ["dirt-movers--hauling.json (Dirt Movers / Hauling)"]
    assert report.summary() == "1 written, 0 revised, 0 unchanged, 0 held, 0 not quotes, 0 refused"
    assert report.lines() == ["written dirt-movers--hauling.json (Dirt Movers / Hauling)"]
    saved = Inventory.load(env.state).get(env.sha)
    assert saved.status == "extracted"


def test_a_dry_run_writes_nothing(env):
    env.inv.save()
    before = env.inv.path.read_bytes()
    report = run(env, result(env.sha), write=False)
    assert report.written == ["dirt-movers--hauling.json (Dirt Movers / Hauling)"]
    assert not (env.quotes / "dirt-movers--hauling.json").exists()
    assert env.inv.path.read_bytes() == before
    assert env.inv.get(env.sha).status == "new" and env.inv.get(env.sha).results == []


def test_an_unknown_sha_refuses_only_that_result(env):
    report = run(env, result("0" * 64), result(env.sha))
    assert report.refused == ["00000000: not in the inventory"]
    assert (env.quotes / "dirt-movers--hauling.json").exists()


def test_not_quote_and_unreadable_set_the_record_status(env):
    report = run(env, {"sha256": env.sha, "doc_type": "not_quote", "reason": "cut sheet"})
    doc = env.inv.get(env.sha)
    assert (doc.status, doc.reason) == ("not_quote", "cut sheet")
    assert len(report.not_quote) == 1
    report = run(env, {"sha256": env.sha, "doc_type": "unreadable", "reason": "blurred"})
    assert doc.status == "error" and doc.reason.startswith("unreadable by the agent")
    assert len(report.held) == 1


def test_a_package_the_spec_does_not_have_is_held(env):
    report = run(env, result(env.sha, work_package_name="Fencing"))
    doc = env.inv.get(env.sha)
    assert (doc.status, doc.reason) == ("held", "package 'Fencing' is not in the spec")
    assert len(report.held) == 1 and report.written == []
    assert list(env.quotes.glob("*.json")) == []


def test_the_package_name_is_matched_case_insensitively_and_written_as_the_spec_spells_it(env):
    run(env, result(env.sha, work_package_name="  hauling "))
    assert written_quote(env).work_package_name == "Hauling"


def test_extras_land_in_the_conditions_grid_with_a_review_flag(env):
    report = run(env, result(env.sha, extras=[{"description": "Fuel surcharge adder",
                                               "printed_price": 1.25, "printed_unit": "CY"}]))
    q = written_quote(env)
    assert q.conditions["Also quoted: Fuel surcharge adder"] == "1.25 / CY"
    assert "extra line: Fuel surcharge adder" in q.conditions["Review"]
    assert "review: extra line" in q.notes
    assert report.review == ["dirt-movers--hauling.json: extra line: Fuel surcharge adder"]


def test_a_printed_extension_that_contradicts_is_flagged_and_the_unit_price_kept():
    q, reasons = assembled(lines=[dict(HAUL_LINE, quantity=460, extension=76.0)])
    assert q.lines[0].unit_price == 16.5 and q.lines[0].quantity == 460
    assert ("item 2 'Haul, import + export': printed extension 76.0 does not reproduce "
            "460 × 16.5") in q.conditions["Review"]
    assert reasons


def test_a_rounded_extension_is_not_a_contradiction():
    q, reasons = assembled(lines=[dict(HAUL_LINE, quantity=8390, unit_price=2.80,
                                       extension=23470)])
    assert "Review" not in q.conditions and reasons == []


def test_a_unit_that_differs_from_the_package_line_is_flagged():
    q, _ = assembled(lines=[dict(HAUL_LINE, unit="CWT")])
    assert ("item 2 'Haul, import + export': priced per CWT, package line is CY"
            in q.conditions["Review"])
    assert q.lines[0].unit_price == 16.5
    q, reasons = assembled(lines=[dict(HAUL_LINE, unit=" cy ")])
    assert reasons == []


def test_an_ambiguous_date_is_normalised_and_flagged():
    q, _ = assembled(quote_date="03/04/2026")
    assert q.quote_date == "2026-03-04"
    assert "read as 2026-03-04 (US month-first)" in q.conditions["Review"]
    q, _ = assembled(quote_date="see attached")
    assert q.quote_date is None
    assert "quote date 'see attached' could not be read" in q.conditions["Review"]


def test_a_freight_rate_is_kept_apart_and_flagged():
    q, _ = assembled(lines=[dict(HAUL_LINE, freight_unit_price=2.0)])
    assert q.conditions["Freight rate: Haul, import + export"] == "2.0 / CY"
    assert q.lines[0].unit_price == 16.5
    assert "freight rate 2.0 printed beside the unit price; not combined" in q.conditions["Review"]


def test_conditions_match_the_package_keys_case_insensitively():
    q, _ = assembled(conditions={"fuel SURCHARGE": "4%", "Bond": "excluded"})
    assert q.conditions == {"Fuel surcharge": "4%", "Bond": "excluded"}


def test_a_lump_sum_writes_amount_and_a_printed_total_otherwise_goes_to_conditions():
    q, _ = assembled(lines=[], total_amount=8740)
    assert q.amount == 8740 and "Printed total" not in q.conditions
    q, _ = assembled(total_amount=7590)
    assert q.amount is None and q.conditions["Printed total"] == "7,590.00"
    q, _ = assembled(total_amount=9000, total_covers_unpriced=True)
    assert q.amount == 9000


def test_the_header_fields_pass_through():
    q, _ = assembled(vendor_name=" Dirt Movers ", quote_ref="Q-17", contact_info="Al 555-0100",
                     is_dbe=True, surcharge=0.04)
    assert (q.vendor_name, q.quote_ref, q.contact_info, q.is_dbe, q.surcharge) == (
        "Dirt Movers", "Q-17", "Al 555-0100", True, 0.04)
    assert assembled(is_dbe=None)[0].is_dbe is False


def test_needs_review_and_line_review_are_carried():
    q, reasons = assembled(needs_review=["handwritten total"],
                           lines=[dict(HAUL_LINE, review="price partly obscured")])
    assert reasons == ["handwritten total", "price partly obscured"]
    assert q.conditions["Review"] == "handwritten total; price partly obscured"
    assert q.notes.splitlines() == ["review: handwritten total", "review: price partly obscured"]


def test_the_build_gate_holds_a_result_the_frames_refuse(env):
    report = run(env, result(env.sha, lines=[dict(HAUL_LINE, item_number="9")]))
    doc = env.inv.get(env.sha)
    assert doc.status == "held"
    assert "Hauling: Dirt Movers quotes item '9', which is not in the package" in doc.reason
    assert doc.results[-1]["vendor_name"] == "Dirt Movers"
    assert doc.results[-1]["work_package_name"] == "Hauling"
    assert len(report.held) == 1
    assert list(env.quotes.glob("*.json")) == []


def test_the_build_gate_holds_a_selector_that_resolves_to_nothing(env):
    env.spec["work_packages"][0]["selected"] = "Bulk Haul Co"
    report = run(env, result(env.sha))
    assert env.inv.get(env.sha).status == "held"
    assert "selected 'Bulk Haul Co'" in env.inv.get(env.sha).reason
    assert report.written == []


def test_one_document_on_two_packages_writes_two_files(env):
    valves = result(env.sha, work_package_name="Valves",
                    lines=[{"description": "Valve boxes", "item_number": "3",
                            "line_name": "Valve boxes (subcontract)", "unit_price": 900}])
    report = run(env, result(env.sha), valves)
    assert (env.quotes / "dirt-movers--hauling.json").exists()
    assert (env.quotes / "dirt-movers--valves.json").exists()
    assert len(env.inv.get(env.sha).results) == 2
    assert len(report.written) == 2


def test_two_packages_in_a_dry_run_gate_against_each_other(env):
    valves = result(env.sha, work_package_name="Valves",
                    lines=[{"description": "Valve boxes", "item_number": "3",
                            "line_name": "Valve boxes (subcontract)", "unit_price": 900}])
    report = run(env, result(env.sha), valves, write=False)
    assert len(report.written) == 2 and report.held == []


def test_a_document_already_on_file_is_unchanged_whatever_its_result_says(env):
    run(env, result(env.sha))
    report = run(env, result(env.sha, quote_date="2026-10-25"))
    assert report.held == [] and report.revised == [] and report.written == []
    assert report.unchanged == [
        "dirt-movers--hauling.json (Dirt Movers / Hauling): already on file"]
    assert written_quote(env).quote_date == "2026-10-20"


def test_a_quantity_basis_is_kept_in_notes_without_a_flag():
    q, reasons = assembled(lines=[dict(HAUL_LINE, quantity_basis="loose CY")])
    assert reasons == [] and "Review" not in q.conditions
    assert "item 2 'Haul, import + export': quantity basis loose CY" in q.notes


def test_is_carried_folds_selected_and_picks():
    assert is_carried({"selected": " dirt movers"}, "Dirt Movers")
    assert is_carried({"selected": "ARR", "picks": {"2": "DIRT MOVERS"}}, "Dirt Movers")
    assert not is_carried({"selected": "ARR"}, "Dirt Movers")


def test_vendor_total_sums_cells_by_qty_and_uses_the_lump_amount():
    spec = spec_from_fixture()
    quotes = [CanonicalQuote(vendor_name="Dirt Movers", work_package_name="Hauling",
                             lines=[QuoteLine(schedule_name="Base", item_number="2",
                                              unit_price=16.5)]),
              CanonicalQuote(vendor_name="Bulk Haul Co", work_package_name="Hauling",
                             amount=8740)]
    frame = build_package_frames(spec, quotes, spare_columns=0, taken=set())[0]
    assert vendor_total(frame, "dirt movers") == pytest.approx(460 * 16.5)
    assert vendor_total(frame, "Bulk Haul Co") == 8740


def test_report_lines_prefix_each_entry_with_its_list():
    r = ImportReport(written=["a"], revised=[], unchanged=["u"], held=["b"], not_quote=["c"],
                     review=["d"], refused=["e"])
    assert r.lines() == ["written a", "unchanged u", "held b", "not_quote c", "review d",
                         "refused e"]


def test_a_covering_lump_sum_drops_an_unpriced_line_and_the_file_loads(env):
    unpriced = {"description": "Haul import/export", "item_number": "2",
                "line_name": "Haul, import + export", "unit": "CY"}
    report = run(env, result(env.sha, lines=[unpriced], total_amount=9000,
                             total_covers_unpriced=True))
    assert report.written
    q = written_quote(env)
    assert q.amount == 9000 and q.lines == []
    assert "item 2 'Haul, import + export': unpriced, covered by the lump sum" in q.notes


def test_an_unpriced_alternate_becomes_a_condition_and_the_file_loads(env):
    alt = {"description": "Night hauling", "item_number": "2",
           "line_name": "Haul, import + export", "is_alternate": True}
    report = run(env, result(env.sha, lines=[dict(HAUL_LINE), alt]))
    assert report.written
    q = written_quote(env)
    assert len(q.lines) == 1 and q.lines[0].unit_price == 16.5
    frame = build_package_frames(env.spec, [q], spare_columns=0, taken=set())[0]
    (col,) = frame.vendors
    assert list(col.cells.values()) == [16.5]
    assert q.conditions["Alternate: Haul, import + export"] == "no price"
    assert "item 2 'Haul, import + export': alternate without a price" in q.conditions["Review"]


def test_an_unpriced_line_with_no_total_is_held_by_the_quote_file_check(env):
    unpriced = {"description": "Haul import/export", "item_number": "2",
                "line_name": "Haul, import + export"}
    report = run(env, result(env.sha, lines=[unpriced]))
    doc = env.inv.get(env.sha)
    assert doc.status == "held" and doc.reason.startswith("quote file check: ")
    assert "has no price" in doc.reason
    assert report.written == [] and list(env.quotes.glob("*.json")) == []


def test_a_failed_write_is_an_error_and_the_inventory_still_records_the_first(env, tmp_path,
                                                                               monkeypatch):
    from estimating_tools.quotes.intake import importer
    from estimating_tools.quotes.intake.scan import scan_inbox as rescan

    inbox = tmp_path / "inbox"
    make_pdf(inbox / "valves.pdf", [QUOTE_TEXT + "Valve boxes 2 EA @ 900\n"])
    rescan(env.inv, inbox, env.state)
    (second,) = [d for d in env.inv if d.file_name == "valves.pdf"]
    real, calls = importer.write_quote_file, []

    def flaky(path, quote):           # the second write into the quotes folder fails
        if Path(path).parent == env.quotes:
            calls.append(path)
        if len(calls) == 2 and calls[-1] == path:
            raise OSError("disk full")
        real(path, quote)
    monkeypatch.setattr(importer, "write_quote_file", flaky)
    valves = result(second.sha256, work_package_name="Valves",
                    lines=[{"description": "Valve boxes", "item_number": "3",
                            "line_name": "Valve boxes (subcontract)", "unit_price": 900}])
    run(env, result(env.sha), valves)
    saved = Inventory.load(env.state)
    assert saved.get(env.sha).status == "extracted"
    failed = saved.get(second.sha256)
    assert failed.status == "error"
    assert failed.reason == "could not write dirt-movers--valves.json: disk full"


def test_a_hand_named_file_for_the_same_vendor_and_package_is_found(env):
    from estimating_tools.quotes.files import write_quote_file
    env.quotes.mkdir(exist_ok=True)
    write_quote_file(env.quotes / "dm-haul.json", CanonicalQuote(
        vendor_name="dirt movers", work_package_name="HAULING", quote_date="2026-10-01",
        lines=[QuoteLine(schedule_name="Base", item_number="2", unit_price=15.0)]))
    report = run(env, result(env.sha))
    assert report.written == []
    assert report.revised == [
        "dm-haul.json: Dirt Movers revised Hauling (carried): 6,900.00 → 7,590.00"]
    assert written_quote(env, "dm-haul.json").lines[0].unit_price == 16.5
    assert len(list(env.quotes.glob("dm-haul.json.bak-*"))) == 1
    assert env.inv.get(env.sha).results[0]["supersedes"] is None
    assert not (env.quotes / "dirt-movers--hauling.json").exists()


def test_a_slug_file_holding_another_vendors_quote_is_held(env):
    from estimating_tools.quotes.files import write_quote_file
    env.quotes.mkdir(exist_ok=True)
    write_quote_file(env.quotes / "dirt-movers--hauling.json", CanonicalQuote(
        vendor_name="Dirt-Movers", work_package_name="Hauling", quote_date="2026-10-01",
        lines=[QuoteLine(schedule_name="Base", item_number="2", unit_price=15.0)]))
    report = run(env, result(env.sha))
    assert report.written == [] and report.revised == []
    assert env.inv.get(env.sha).reason == (
        "dirt-movers--hauling.json holds another vendor's or package's quote")


EMPTY = "no priced lines and no total (a failed read; see prompt rule 3)"


def test_a_quote_with_no_lines_and_no_total_is_held_as_a_failed_read(env):
    report = run(env, result(env.sha, lines=[]))
    doc = env.inv.get(env.sha)
    assert (doc.status, doc.reason) == ("held", EMPTY)
    assert report.written == [] and list(env.quotes.glob("*.json")) == []


def test_only_unpriced_alternates_and_an_uncovering_total_is_held_as_a_failed_read(env):
    alt = {"description": "Night hauling", "item_number": "2",
           "line_name": "Haul, import + export", "is_alternate": True}
    report = run(env, result(env.sha, lines=[alt], total_amount=9000))
    doc = env.inv.get(env.sha)
    assert (doc.status, doc.reason) == ("held", EMPTY)
    assert report.written == [] and list(env.quotes.glob("*.json")) == []


def test_a_priced_line_with_no_unit_is_flagged():
    line = {k: v for k, v in HAUL_LINE.items() if k != "unit"}
    q, reasons = assembled(lines=[line])
    assert "item 2 'Haul, import + export': unit not stated; package line is CY" in reasons
    assert q.lines[0].unit_price == 16.5
    unpriced = dict(line, unit_price=None, is_included=False)
    assert assembled(lines=[unpriced])[1] == []      # nothing priced: nothing to check


@pytest.mark.parametrize("replacement", ["vendor", "package", "not_quote"])
def test_corrected_identity_is_held_without_leaving_a_second_quote(env, replacement):
    run(env, result(env.sha))
    before = (env.quotes / "dirt-movers--hauling.json").read_bytes()
    env.inv.requeue(env.inv.get(env.sha))
    if replacement == "vendor":
        corrected = result(env.sha, vendor_name="Correct Vendor")
    elif replacement == "package":
        corrected = result(env.sha, work_package_name="Valves", lines=[{
            "description": "Valve boxes", "item_number": "3",
            "line_name": "Valve boxes (subcontract)", "unit_price": 900, "unit": "EA"}])
    else:
        corrected = {"sha256": env.sha, "doc_type": "not_quote"}
    report = run(env, corrected)
    assert report.held and "previous quote" in report.held[0]
    assert report.written == [] and report.revised == []
    assert (env.quotes / "dirt-movers--hauling.json").read_bytes() == before
    assert len(list(env.quotes.glob("*.json"))) == 1


def test_late_results_for_a_superseded_document_cannot_create_a_quote(env, tmp_path):
    old = env.inv.get(env.sha)
    make_pdf(tmp_path / "inbox" / "dirt-movers.pdf", [QUOTE_TEXT + "Corrected"])
    scan_inbox(env.inv, tmp_path / "inbox", env.state)
    assert old.superseded_by
    report = run(env, result(env.sha))
    assert report.refused and "superseded" in report.refused[0]
    assert not list(env.quotes.glob("*.json"))
