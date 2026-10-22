import json
from pathlib import Path

import yaml

from estimating_tools.estimate_spec.package_frames import build_package_frames
from estimating_tools.quotes.files import load_quotes
from estimating_tools.quotes.intake import cli
from estimating_tools.quotes.intake.inventory import Inventory
from estimating_tools.quotes.tests._intake import QUOTE_TEXT, make_pdf, make_xlsx, spec_on_disk

HAUL_LINE = {"description": "Haul import and export", "item_number": "2",
             "line_name": "Haul, import + export", "unit_price": 16.5, "unit": "CY"}


def _results(tmp_path, *results, name="b1.json"):
    path = Path(tmp_path) / name
    path.write_text(json.dumps({"stage": "extract", "schema_version": 1,
                                "results": list(results)}), encoding="utf-8")
    return path


def _quote(sha, **overrides):
    res = {"sha256": sha, "doc_type": "quote", "vendor_name": "Dirt Movers",
           "work_package_name": "Hauling", "quote_date": "10/20/2026",
           "lines": [dict(HAUL_LINE)]}
    res.update(overrides)
    return res


def _inventory(tmp_path):
    return Inventory.load(Path(tmp_path) / "quotes" / "_intake")


def _one_doc(tmp_path, capsys):
    """A spec, a text PDF in its inbox, scanned and read; returns (spec_path, sha)."""
    spec_path = spec_on_disk(tmp_path)
    make_pdf(tmp_path / "inbox" / "dirt-movers.pdf", [QUOTE_TEXT])
    assert cli.main(["run", str(spec_path)]) == 0
    capsys.readouterr()
    (doc,) = list(_inventory(tmp_path))
    return spec_path, doc.sha256


def test_scan_text_batch_import_report_round_trip(tmp_path, capsys):
    spec_path = spec_on_disk(tmp_path)
    make_pdf(tmp_path / "inbox" / "dirt-movers.pdf", [QUOTE_TEXT])

    assert cli.main(["run", str(spec_path)]) == 0
    batch_path = Path(capsys.readouterr().out.strip())
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    (entry,) = batch["docs"]
    assert entry["file_name"] == "dirt-movers.pdf" and entry["route"] == "text"
    assert Path(entry["text_path"]).is_file()

    results = _results(tmp_path, _quote(entry["sha256"]))
    assert cli.main(["import", str(spec_path), str(results), "--write"]) == 0
    out = capsys.readouterr().out
    assert "written dirt-movers--hauling.json (Dirt Movers / Hauling)" in out
    assert (tmp_path / "quotes" / "_intake" / "results" / "b1.json").is_file()

    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    quotes = load_quotes(tmp_path / "quotes")
    assert [q.quote_date for q in quotes] == ["2026-10-20"]
    frames = build_package_frames(spec, quotes, spare_columns=0, taken=set())
    hauling = next(f for f in frames if f.name == "Hauling")
    col = next(v for v in hauling.vendors if v.name == "Dirt Movers")
    assert col.cells == {"2/02/0": 16.5}

    assert cli.main(["report", str(spec_path)]) == 0
    rows = capsys.readouterr().out.splitlines()
    assert rows[0].split()[:4] == ["sha", "file", "route", "status"]
    row = next(r for r in rows if "dirt-movers.pdf" in r)
    for value in ("extracted", "Dirt Movers", "Hauling", "dirt-movers--hauling.json"):
        assert value in row


def test_run_on_an_unchanged_inbox_prints_nothing_new_and_exits_0(tmp_path, capsys):
    spec_path, sha = _one_doc(tmp_path, capsys)
    cli.main(["import", str(spec_path), str(_results(tmp_path, _quote(sha))), "--write"])
    capsys.readouterr()
    inventory = tmp_path / "quotes" / "_intake" / "inventory.json"
    before = (inventory.stat().st_mtime_ns, inventory.read_bytes())
    assert cli.main(["run", str(spec_path)]) == 0
    assert capsys.readouterr().out == "nothing new\n"
    assert (inventory.stat().st_mtime_ns, inventory.read_bytes()) == before
    # An empty inbox reads the same.
    (tmp_path / "other").mkdir()
    empty = spec_on_disk(tmp_path / "other")
    assert cli.main(["run", str(empty)]) == 0
    assert capsys.readouterr().out == "nothing new\n"


def test_run_with_only_unreadable_files_prints_nothing_to_extract(tmp_path, capsys):
    spec_path = spec_on_disk(tmp_path)
    make_xlsx(tmp_path / "inbox" / "blank.xlsx", {"Sheet": []})
    assert cli.main(["run", str(spec_path)]) == 0
    assert capsys.readouterr().out == "nothing to extract\n"
    (doc,) = list(_inventory(tmp_path))
    assert doc.route == "unreadable"


def test_scan_and_text_print_their_summaries_and_save(tmp_path, capsys):
    spec_path = spec_on_disk(tmp_path)
    make_pdf(tmp_path / "inbox" / "dirt-movers.pdf", [QUOTE_TEXT])
    (tmp_path / "inbox" / "a.zip").write_bytes(b"zip")
    (tmp_path / "inbox" / "b.doc").write_bytes(b"doc")
    assert cli.main(["scan", str(spec_path)]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines()[0] == "1 new, 0 known, 2 unsupported"
    assert captured.err == "unsupported: .zip ×1, .doc ×1\n"
    assert len(list(_inventory(tmp_path))) == 1
    assert cli.main(["text", str(spec_path)]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "1 text, 0 vision, 0 unreadable"
    assert [d.route for d in _inventory(tmp_path)] == ["text"]
    assert cli.main(["batch", str(spec_path), "-o", str(tmp_path / "work.json")]) == 0
    assert capsys.readouterr().out == f"{tmp_path / 'work.json'}\n"


def test_import_without_write_is_a_dry_run(tmp_path, capsys):
    spec_path, sha = _one_doc(tmp_path, capsys)
    results = _results(tmp_path, _quote(sha))
    assert cli.main(["import", str(spec_path), str(results)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "written dirt-movers--hauling.json (Dirt Movers / Hauling)"
    assert out[1] == "1 written, 0 revised, 0 unchanged, 0 held, 0 not quotes, 0 refused"
    assert out[-1] == "dry run: run again with --write to apply"
    assert not (tmp_path / "quotes" / "dirt-movers--hauling.json").exists()
    assert not (tmp_path / "quotes" / "_intake" / "results").exists()
    assert _inventory(tmp_path).get(sha).status == "new"


def test_a_results_file_that_fails_the_schema_is_refused_whole(tmp_path, capsys):
    spec_path, sha = _one_doc(tmp_path, capsys)
    results = _results(tmp_path, _quote(sha), _quote("not-a-sha"),
                       _quote(sha, work_package_name="Hauling", lines=[{"item_number": "2"}]))
    assert cli.main(["import", str(spec_path), str(results), "--write"]) == 1
    captured = capsys.readouterr()
    errors = captured.err.splitlines()
    assert len(errors) >= 3
    assert any("$.sha256" in e for e in errors)
    assert any("description" in e for e in errors)
    assert any("both cover" in e for e in errors)
    assert captured.out == ""
    assert not (tmp_path / "quotes" / "dirt-movers--hauling.json").exists()
    assert _inventory(tmp_path).get(sha).status == "new"
    # A file that is not JSON is refused the same way.
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert cli.main(["import", str(spec_path), str(bad), "--write"]) == 1
    assert "cannot read results" in capsys.readouterr().err


def test_a_malformed_quote_file_on_disk_exits_2_without_a_traceback(tmp_path, capsys):
    spec_path, sha = _one_doc(tmp_path, capsys)
    (tmp_path / "quotes" / "broken.json").write_text('{"bogus_key": 1}', encoding="utf-8")
    assert cli.main(["import", str(spec_path), str(_results(tmp_path, _quote(sha))),
                     "--write"]) == 2
    assert capsys.readouterr().err.startswith("quote file problem: ")


def test_requeue_reopens_a_held_record_and_held_flag_takes_all(tmp_path, capsys):
    spec_path = spec_on_disk(tmp_path)
    make_pdf(tmp_path / "inbox" / "dirt-movers.pdf", [QUOTE_TEXT])
    make_pdf(tmp_path / "inbox" / "fence-co.pdf", [QUOTE_TEXT.replace("DIRT MOVERS", "FENCE CO")])
    cli.main(["run", str(spec_path)])
    capsys.readouterr()
    a, b = list(_inventory(tmp_path))
    results = _results(tmp_path, _quote(a.sha256, work_package_name="Fencing"),
                       _quote(b.sha256, vendor_name="Fence Co", work_package_name="Fencing"))
    cli.main(["import", str(spec_path), str(results), "--write"])
    capsys.readouterr()
    assert {d.status for d in _inventory(tmp_path)} == {"held"}

    assert cli.main(["requeue", str(spec_path), a.sha256[:10]]) == 0
    assert capsys.readouterr().out == f"requeued {a.short} {a.file_name}\n"
    doc = _inventory(tmp_path).get(a.sha256)
    assert (doc.status, doc.reason, doc.results, doc.route) == ("new", None, [], "text")
    assert _inventory(tmp_path).get(b.sha256).status == "held"

    assert cli.main(["requeue", str(spec_path), "--held"]) == 0
    assert capsys.readouterr().out == f"requeued {b.short} {b.file_name}\n"
    assert {d.status for d in _inventory(tmp_path)} == {"new"}
    # The next batch offers both again.
    assert cli.main(["batch", str(spec_path)]) == 0
    batch = json.loads(Path(capsys.readouterr().out.strip()).read_text(encoding="utf-8"))
    assert len(batch["docs"]) == 2


def test_import_of_a_held_sha_applies_without_requeue(tmp_path, capsys):
    spec_path, sha = _one_doc(tmp_path, capsys)
    cli.main(["import", str(spec_path),
              str(_results(tmp_path, _quote(sha, work_package_name="Fencing"))), "--write"])
    capsys.readouterr()
    assert _inventory(tmp_path).get(sha).status == "held"
    assert cli.main(["import", str(spec_path), str(_results(tmp_path, _quote(sha), name="b2.json")),
                     "--write"]) == 0
    assert "written dirt-movers--hauling.json" in capsys.readouterr().out
    assert _inventory(tmp_path).get(sha).status == "extracted"
    assert (tmp_path / "quotes" / "dirt-movers--hauling.json").is_file()


def test_inbox_override_and_the_spec_key(tmp_path, capsys):
    spec_path = spec_on_disk(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    make_pdf(other / "q.pdf", [QUOTE_TEXT])
    make_pdf(tmp_path / "inbox" / "dirt-movers.pdf", [QUOTE_TEXT + "Revised.\n"])
    assert cli.main(["scan", str(spec_path), "--inbox", "elsewhere"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "1 new, 0 known, 0 unsupported"
    assert [d.file_name for d in _inventory(tmp_path)] == ["q.pdf"]
    assert cli.main(["scan", str(spec_path)]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "1 new, 0 known, 0 unsupported"
    # A mistyped --inbox is an error, not an empty inbox.
    assert cli.main(["scan", str(spec_path), "--inbox", "nowhere"]) == 2
    captured = capsys.readouterr()
    assert captured.err == f"inbox {tmp_path / 'nowhere'} does not exist\n"
    assert captured.out == ""

    # Neither the flag nor the key: <spec dir>/../Subquotes/inbox.
    bid = tmp_path / "bid" / "Estimate"
    bid.mkdir(parents=True)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    del spec["work_packages_inbox_dir"]
    bare = bid / "demo.estimate.yaml"
    bare.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    default = tmp_path / "bid" / "Subquotes" / "inbox"
    default.mkdir(parents=True)
    make_pdf(default / "q.pdf", [QUOTE_TEXT])
    assert cli.main(["scan", str(bare)]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "1 new, 0 known, 0 unsupported"


def test_a_spec_without_work_packages_exits_2(tmp_path, capsys):
    spec_path = tmp_path / "s.yaml"
    spec_path.write_text(yaml.safe_dump({"items": []}), encoding="utf-8")
    assert cli.main(["scan", str(spec_path)]) == 2
    assert capsys.readouterr().err == "the spec has no work_packages\n"
    spec_path.write_text("- a list\n", encoding="utf-8")
    assert cli.main(["report", str(spec_path)]) == 2
    assert capsys.readouterr().err != ""
    spec_path.write_text("key: [unclosed\n", encoding="utf-8")
    assert cli.main(["run", str(spec_path)]) == 2
    assert capsys.readouterr().err.startswith("invalid YAML in ")
    assert cli.main(["run", str(tmp_path / "missing.yaml")]) == 2
    assert capsys.readouterr().err.startswith("no such file: ")
    assert not (tmp_path / "quotes").exists()


def test_report_json_lists_every_document(tmp_path, capsys):
    spec_path = spec_on_disk(tmp_path)
    make_pdf(tmp_path / "inbox" / "dirt-movers.pdf", [QUOTE_TEXT])
    make_xlsx(tmp_path / "inbox" / "blank.xlsx", {"Sheet": []})
    cli.main(["run", str(spec_path)])
    capsys.readouterr()
    assert cli.main(["report", str(spec_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    docs = payload["documents"]
    assert sorted(Path(d["paths"][0]).name for d in docs) == ["blank.xlsx", "dirt-movers.pdf"]
    assert set(docs[0]) >= {"sha256", "paths", "route", "status", "reason", "results"}


def test_run_on_a_missing_inbox_exits_2(tmp_path, capsys):
    spec_path = spec_on_disk(tmp_path)
    (tmp_path / "inbox").rmdir()
    assert cli.main(["run", str(spec_path)]) == 2
    captured = capsys.readouterr()
    assert captured.err == f"inbox {tmp_path / 'inbox'} does not exist\n"
    assert captured.out == ""
    assert not (tmp_path / "quotes" / "_intake" / "inventory.json").exists()


def test_work_packages_that_do_not_build_exit_2_without_a_traceback(tmp_path, capsys):
    spec_path, sha = _one_doc(tmp_path, capsys)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    spec["work_packages"][0]["items"].append("999")
    spec_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    message = "the spec's work packages: Hauling: item '999' is not in the spec\n"
    for argv in (["batch", str(spec_path)], ["run", str(spec_path)],
                 ["import", str(spec_path), str(_results(tmp_path, _quote(sha))), "--write"]):
        assert cli.main(argv) == 2
        captured = capsys.readouterr()
        assert (captured.out, captured.err) == ("", message)


def test_run_names_the_records_it_left_held_or_in_error_on_stderr(tmp_path, capsys):
    spec_path = spec_on_disk(tmp_path)
    make_pdf(tmp_path / "inbox" / "dirt-movers.pdf", [QUOTE_TEXT])
    (tmp_path / "inbox" / "old.xls").write_bytes(b"\xd0\xcf\x11\xe0")
    (tmp_path / "inbox" / "mail.msg").write_bytes(b"\xd0\xcf\x11\xe0msg")
    assert cli.main(["run", str(spec_path)]) == 0
    captured = capsys.readouterr()
    (out,) = captured.out.splitlines()
    assert Path(out).is_file()
    docs = {d.kind: d for d in _inventory(tmp_path)}
    err = captured.err.splitlines()
    assert (f"held {docs['msg'].short} mail.msg: save the message as .eml or save its "
            "attachments") in err
    assert f"error {docs['xls'].short} old.xls: xls is not readable here; save it as .xlsx" in err
    assert not any("dirt-movers" in line for line in err)
    # The next tick changes nothing: no line repeats.
    assert cli.main(["run", str(spec_path)]) == 0
    assert "mail.msg" not in capsys.readouterr().err


def test_inventory_paths_do_not_depend_on_the_working_directory(tmp_path, capsys, monkeypatch):
    spec_path = spec_on_disk(tmp_path)
    make_pdf(tmp_path / "inbox" / "dirt-movers.pdf", [QUOTE_TEXT])
    monkeypatch.chdir(tmp_path)
    assert cli.main(["scan", spec_path.name]) == 0
    assert cli.main(["text", spec_path.name]) == 0
    (doc,) = list(_inventory(tmp_path))
    assert Path(doc.paths[0]).is_absolute()
    monkeypatch.chdir(tmp_path.parent)
    capsys.readouterr()
    assert cli.main(["batch", str(Path(tmp_path.name) / spec_path.name)]) == 0
    batch = json.loads(Path(capsys.readouterr().out.strip()).read_text(encoding="utf-8"))
    (entry,) = batch["docs"]
    assert Path(entry["text_path"]).is_file()


def test_a_second_tick_on_the_same_open_document_says_so(tmp_path, capsys):
    spec_path, _ = _one_doc(tmp_path, capsys)        # the first tick offered it
    assert cli.main(["run", str(spec_path)]) == 0
    captured = capsys.readouterr()
    assert Path(captured.out.strip()).is_file()
    assert captured.err == "1 document(s) offered before and still open\n"
