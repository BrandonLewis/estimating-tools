import json
import re

import pytest
import yaml

from estimating_tools.estimate_spec.tests._fieldbook import packaged_spec
from estimating_tools.quotes.intake.batch import (
    BATCH_VERSION, ResultsError, batch_candidates, load_instructions, load_schema,
    package_digest, read_results, validate_results, write_batch)
from estimating_tools.quotes.intake.inventory import (
    Inventory, inbox_dir_for, state_dir_for)
from estimating_tools.quotes.intake.scan import scan_inbox
from estimating_tools.quotes.intake.text import pages_dir, recover_text, text_path
from estimating_tools.quotes.tests._intake import (
    QUOTE_TEXT, make_pdf, make_png, spec_on_disk)

SHA = "a" * 64
SHA_B = "b" * 64


def _setup(tmp_path):
    spec_path = spec_on_disk(tmp_path)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    state = state_dir_for(spec_path, spec)
    return spec, inbox_dir_for(spec_path, spec), state, Inventory.load(state)


def _three_docs(tmp_path):
    spec, inbox, state, inv = _setup(tmp_path)
    make_pdf(inbox / "text.pdf", [QUOTE_TEXT])
    make_pdf(inbox / "scan.pdf", [None, None])
    make_png(inbox / "photo.png", "quote")
    scan_inbox(inv, inbox, state)
    recover_text(inv, state)
    return spec, inbox, state, inv


def test_package_digest_carries_names_lines_and_condition_keys():
    digest = package_digest(packaged_spec())
    assert [d["name"] for d in digest] == ["Hauling", "Valves"]
    hauling = digest[0]
    assert hauling["kind"] == "subcontract" and hauling["scope"] is None
    assert hauling["conditions"] == ["Fuel surcharge", "Dump fees"]
    assert hauling["lines"] == [{"schedule_name": "Base", "item_number": "2",
                                 "line_name": "Haul, import + export", "uom": "CY", "qty": 460}]
    assert digest[1]["lines"][0]["line_name"] == "Valve boxes (subcontract)"


def test_schedule_name_falls_back_from_item_to_spec_to_base():
    spec = packaged_spec()
    spec["schedule"] = "A"
    assert package_digest(spec)[0]["lines"][0]["schedule_name"] == "A"
    (item2,) = [i for i in spec["items"] if i["item_no"] == "2"]
    item2["scaffold_meta"] = {"source": "x", "field_hashes": {}, "schedule": "B"}
    digest = package_digest(spec)
    assert digest[0]["lines"][0]["schedule_name"] == "B"
    assert digest[1]["lines"][0]["schedule_name"] == "A"


def test_write_batch_lists_only_routed_new_documents_with_their_paths(tmp_path):
    spec, inbox, state, inv = _three_docs(tmp_path)
    make_pdf(inbox / "done.pdf", [QUOTE_TEXT + "Another vendor\n"])
    scan_inbox(inv, inbox, state)
    recover_text(inv, state)
    (done,) = [d for d in inv if d.file_name == "done.pdf"]
    done.status = "extracted"
    path, not_rendered = write_batch(inv, spec, state)
    assert not_rendered == 0
    assert path.parent == state / "batches"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.json", path.name)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert (data["stage"], data["schema_version"]) == ("extract", BATCH_VERSION)
    assert data["instructions"] == load_instructions()
    assert data["packages"] == package_digest(spec)
    docs = {d["file_name"]: d for d in data["docs"]}
    assert set(docs) == {"text.pdf", "scan.pdf", "photo.png"}
    text = docs["text.pdf"]
    assert text["route"] == "text" and "image_paths" not in text
    assert text["text_path"] == str(text_path(state, text["sha256"]))
    assert text_path(state, text["sha256"]).is_absolute() and text_path(state, text["sha256"]).exists()
    for name in ("scan.pdf", "photo.png"):
        assert docs[name]["route"] == "vision" and "text_path" not in docs[name]
        assert all(p.startswith("/") for p in docs[name]["image_paths"])
    assert len(docs["scan.pdf"]["image_paths"]) == 2


def test_write_batch_holds_back_a_vision_document_without_a_manifest(tmp_path):
    spec, inbox, state, inv = _three_docs(tmp_path)
    (scan,) = [d for d in inv if d.file_name == "scan.pdf"]
    (pages_dir(state, scan.sha256) / "manifest.json").unlink()
    path, not_rendered = write_batch(inv, spec, state)
    assert not_rendered == 1
    docs = json.loads(path.read_text(encoding="utf-8"))["docs"]
    assert "scan.pdf" not in {d["file_name"] for d in docs}


def test_write_batch_honours_limit_and_include_held(tmp_path):
    spec, inbox, state, inv = _three_docs(tmp_path)
    path, _ = write_batch(inv, spec, state, limit=2, out=tmp_path / "limited.json")
    assert path == tmp_path / "limited.json"
    assert len(json.loads(path.read_text(encoding="utf-8"))["docs"]) == 2
    (held,) = [d for d in inv if d.file_name == "text.pdf"]
    held.status = "held"
    docs, _ = batch_candidates(inv, state)
    assert held not in docs and len(docs) == 2
    docs, _ = batch_candidates(inv, state, include_held=True)
    assert held in docs and len(docs) == 3


def test_write_batch_with_nothing_to_offer_writes_no_file(tmp_path):
    spec, inbox, state, inv = _setup(tmp_path)
    assert write_batch(inv, spec, state) == (None, 0)
    assert not (state / "batches").exists()


def test_batch_file_names_do_not_collide(tmp_path):
    spec, inbox, state, inv = _three_docs(tmp_path)
    names = {write_batch(inv, spec, state)[0].name for _ in range(3)}
    assert len(names) == 3 and all(n.endswith(".json") for n in names)


def test_a_document_missing_from_the_results_stays_new(tmp_path):
    spec, inbox, state, inv = _three_docs(tmp_path)
    before, _ = batch_candidates(inv, state)
    write_batch(inv, spec, state)
    assert all(d.status == "new" for d in inv)
    after, _ = batch_candidates(inv, state)
    assert [d.sha256 for d in after] == [d.sha256 for d in before] and len(after) == 3


def _line(item="2", name="Haul"):
    return {"description": "Haul", "item_number": item, "line_name": name, "unit_price": 1.5}


def test_validate_results_names_every_schema_error_and_duplicate():
    payload = {"stage": "extract", "schema_version": 1, "results": [
        {"sha256": SHA},
        {"sha256": SHA_B, "doc_type": "quote", "work_package_name": "Hauling", "lines": []},
        {"sha256": SHA, "doc_type": "quote", "vendor_name": "A", "work_package_name": "Hauling"},
        {"sha256": SHA, "doc_type": "quote", "vendor_name": "A", "work_package_name": "Hauling"},
        {"sha256": SHA_B, "doc_type": "quote", "vendor_name": "A", "work_package_name": "Valves",
         "lines": [_line("61", "Rebar"), _line("61", "Rebar")]},
    ]}
    with pytest.raises(ResultsError) as exc:
        validate_results(payload)
    errors = exc.value.errors
    assert len(errors) == 4, errors
    assert any(e.startswith("result 0 (aaaaaaaa)") and "doc_type" in e for e in errors)
    assert any(e.startswith("result 1 (bbbbbbbb)") and "vendor_name" in e for e in errors)
    assert any("results 2 and 3 both cover aaaaaaaa on Hauling" in e for e in errors)
    assert any(e.startswith("result 4") and "61" in e and "Rebar" in e for e in errors)
    good = {"stage": "extract", "schema_version": 1, "results": [
        {"sha256": SHA, "doc_type": "quote", "vendor_name": "A", "work_package_name": "Hauling",
         "lines": [_line()], "extras": [{"description": "Freight", "printed_price": 2}]},
        {"sha256": SHA_B, "doc_type": "not_quote", "reason": "a drawing"}]}
    assert validate_results(good) is None


def test_an_alternate_may_share_the_priced_lines_key_but_two_priced_lines_may_not():
    alt = dict(_line(), is_alternate=True, unit_price=2.0)
    ok = {"stage": "extract", "schema_version": 1, "results": [
        {"sha256": SHA, "doc_type": "quote", "vendor_name": "A", "work_package_name": "Hauling",
         "lines": [_line(), alt, dict(alt, unit_price=None)]}]}
    assert validate_results(ok) is None
    bad = {"stage": "extract", "schema_version": 1, "results": [
        {"sha256": SHA, "doc_type": "quote", "vendor_name": "A", "work_package_name": "Hauling",
         "lines": [_line(), alt, dict(_line(), is_alternate=False)]}]}
    with pytest.raises(ResultsError) as exc:
        validate_results(bad)
    assert exc.value.errors == ["result 0 (aaaaaaaa): two lines on item 2 / Haul"]


def test_read_results_loads_and_validates(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"stage": "extract", "schema_version": 1, "results": []}))
    assert read_results(path)["results"] == []
    path.write_text(json.dumps({"stage": "nope"}))
    with pytest.raises(ResultsError):
        read_results(path)


def test_the_schema_and_instructions_load_from_package_data():
    assert isinstance(load_schema()["title"], str)
    text = load_instructions()
    assert "Transcribe" in text and "work_package_name" in text


def test_the_instructions_example_validates_against_the_schema():
    text = load_instructions()
    block = re.search(r"```json\n(.*?)\n```", text, re.S).group(1)
    assert validate_results(json.loads(block)) is None


def test_validate_results_lists_schema_errors_for_malformed_parts_without_crashing():
    payload = {"stage": "extract", "schema_version": 1, "results": [
        {"sha256": SHA, "doc_type": "quote", "vendor_name": "A", "work_package_name": ["x"]},
        {"sha256": SHA_B, "doc_type": "quote", "vendor_name": "A", "work_package_name": "P",
         "lines": 5},
        {"sha256": SHA, "doc_type": "quote", "vendor_name": "A", "work_package_name": "P",
         "lines": [{"description": "d", "item_number": ["1"]}]}]}
    with pytest.raises(ResultsError) as exc:
        validate_results(payload)
    errors = exc.value.errors
    assert any(e.startswith("result 0") and "work_package_name" in e for e in errors)
    assert any(e.startswith("result 1") and "lines" in e for e in errors)
    assert any(e.startswith("result 2") and "item_number" in e for e in errors)


def test_read_results_wraps_unreadable_files_in_results_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    with pytest.raises(ResultsError) as exc:
        read_results(bad)
    assert len(exc.value.errors) == 1 and "bad.json" in exc.value.errors[0]
    bad.write_text("[1]")
    with pytest.raises(ResultsError):
        read_results(bad)
    with pytest.raises(ResultsError):
        read_results(tmp_path / "missing.json")


def test_write_batch_records_offered_in_and_it_round_trips(tmp_path):
    spec, inbox, state, inv = _three_docs(tmp_path)
    inv.save()
    path, _ = write_batch(inv, spec, state)
    assert inv.dirty
    assert all(d.status == "new" for d in inv)
    offered = [d for d in inv if d.offered_in]
    assert len(offered) == 3 and all(d.offered_in == [path.name] for d in offered)
    doc = offered[0]
    doc.requeued_from.append({"quote_file": "x.json", "seq": 1})
    inv.save()
    loaded = Inventory.load(state).get(doc.sha256)
    assert loaded.offered_in == [path.name]
    assert loaded.requeued_from == [{"quote_file": "x.json", "seq": 1}]


@pytest.mark.parametrize("names", [("Hauling", " hauling "), ("Hauling", "HAULING")])
def test_duplicate_package_results_use_the_importers_name_normalization(names):
    results = [{"sha256": SHA, "doc_type": "quote", "vendor_name": "V",
                "work_package_name": name} for name in names]
    with pytest.raises(ResultsError):
        validate_results({"stage": "extract", "schema_version": 1, "results": results})


def test_a_document_cannot_be_both_a_quote_and_not_a_quote():
    results = [{"sha256": SHA, "doc_type": "quote", "vendor_name": "V",
                "work_package_name": "Hauling"}, {"sha256": SHA, "doc_type": "not_quote"}]
    with pytest.raises(ResultsError):
        validate_results({"stage": "extract", "schema_version": 1, "results": results})
