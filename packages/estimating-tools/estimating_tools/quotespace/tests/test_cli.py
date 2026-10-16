"""est-quotespace CLI (estimating_tools.quotespace.cli)."""
import json

from estimating_tools.quotespace import cli
from estimating_tools.quotespace.model import read_journal


def _package_json(tmp_path):
    p = tmp_path / "package.json"
    p.write_text(json.dumps({
        "project_name": "Hwy 41 Culvert", "name": "Structural Concrete",
        "items": [{"schedule": "A", "item_number": "23",
                   "description": "Structural Concrete, Bridge",
                   "quantity": 210.0, "unit": "CY"}],
    }), encoding="utf-8")
    return p


def _vendors_json(tmp_path):
    p = tmp_path / "vendors.json"
    p.write_text(json.dumps([
        {"org_name": "ACME Rebar", "contacts": ["joe@acmerebar.com"]},
        {"org_name": "Basalt Steel", "contacts": []},
    ]), encoding="utf-8")
    return p


def test_solicit_appends_a_validated_record(tmp_path, capsys):
    journal = tmp_path / "Subquotes" / "solicitations.jsonl"
    rc = cli.main([
        "solicit", "--journal", str(journal),
        "--package", "Structural Concrete", "--bm-package-id", "12",
        "--vendor", "ACME Rebar", "--contact", "joe@acmerebar.com",
        "--items", '[{"schedule": "A", "item_number": "23"}]',
        "--status", "sent", "--sent-at", "2026-08-07"])
    assert rc == 0
    recs = read_journal(journal)
    assert len(recs) == 1 and recs[0].status == "sent"
    assert "WROTE:" in capsys.readouterr().err


def test_solicit_rejects_invalid_record_cleanly(tmp_path, capsys):
    journal = tmp_path / "solicitations.jsonl"
    rc = cli.main(["solicit", "--journal", str(journal),
                   "--package", "P", "--vendor", "V", "--status", "sent"])
    assert rc == 1
    assert "sent_at" in capsys.readouterr().err
    assert not journal.exists()


def test_itb_writes_one_doc_per_vendor(tmp_path, capsys):
    out = tmp_path / "ITB"
    rc = cli.main(["itb", "--package-json", str(_package_json(tmp_path)),
                   "--vendors-json", str(_vendors_json(tmp_path)),
                   "--respond-by", "2026-08-14", "-o", str(out)])
    assert rc == 0
    assert (out / "acme-rebar.md").is_file()
    assert (out / "basalt-steel.md").is_file()
    text = (out / "acme-rebar.md").read_text(encoding="utf-8")
    assert "Invitation to Bid" in text and "2026-08-14" in text


def test_itb_colliding_vendor_slugs_get_distinct_files(tmp_path):
    # Two vendors slugging identically (here both fall back to "vendor")
    # must produce two files, never a silent overwrite.
    vendors = tmp_path / "vendors.json"
    vendors.write_text(json.dumps([
        {"org_name": "!!!", "contacts": []},
        {"org_name": "???", "contacts": []},
    ]), encoding="utf-8")
    out = tmp_path / "ITB"
    rc = cli.main(["itb", "--package-json", str(_package_json(tmp_path)),
                   "--vendors-json", str(vendors), "-o", str(out)])
    assert rc == 0
    assert (out / "vendor.md").is_file()
    assert (out / "vendor-2.md").is_file()
    assert "!!!" in (out / "vendor.md").read_text(encoding="utf-8")
    assert "???" in (out / "vendor-2.md").read_text(encoding="utf-8")


def test_itb_missing_input_is_clean_one_liner(tmp_path, capsys):
    rc = cli.main(["itb", "--package-json", str(tmp_path / "nope.json"),
                   "--vendors-json", str(tmp_path / "nope2.json"),
                   "-o", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no such file" in err and "Traceback" not in err


def _coverage_fixtures(tmp_path):
    journal = tmp_path / "solicitations.jsonl"
    cli.main(["solicit", "--journal", str(journal), "--package",
              "Structural Concrete", "--vendor", "ACME Rebar",
              "--status", "sent", "--sent-at", "2026-08-07"])
    packages = tmp_path / "packages.json"
    packages.write_text(json.dumps([
        {"name": "Structural Concrete", "strategy": "sub_out",
         "items": [{"schedule": "A", "item_number": "23",
                    "description": "Str Conc"}]},
    ]), encoding="utf-8")
    return journal, packages


def test_coverage_markdown_to_stdout(tmp_path, capsys):
    journal, packages = _coverage_fixtures(tmp_path)
    capsys.readouterr()
    rc = cli.main(["coverage", "--journal", str(journal),
                   "--packages", str(packages)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# Quote-Space Coverage" in out and "solicited" in out


def test_coverage_json_mode(tmp_path, capsys):
    journal, packages = _coverage_fixtures(tmp_path)
    capsys.readouterr()
    rc = cli.main(["coverage", "--journal", str(journal),
                   "--packages", str(packages), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["packages"][0]["items"][0]["best"] == "solicited"


def test_coverage_missing_packages_file(tmp_path, capsys):
    rc = cli.main(["coverage", "--journal", str(tmp_path / "j.jsonl"),
                   "--packages", str(tmp_path / "nope.json")])
    assert rc == 1
    assert "no such file" in capsys.readouterr().err


def test_condition_appends_record(tmp_path, capsys):
    journal = tmp_path / "quote-conditions.jsonl"
    rc = cli.main([
        "condition", "--journal", str(journal),
        "--package", "Rebar", "--vendor", "Nucor",
        "--separate-acceptance", "no",
        "--acceptance-notes", "not for separate acceptance",
        "--tag", '{"group": "cages", "items": [{"schedule": "A", '
                 '"item_number": "35"}], "treatment": "separate"}'])
    assert rc == 0
    from estimating_tools.quotespace.conditions import read_conditions
    [rec] = read_conditions(journal)
    assert rec.separate_acceptance_permitted is False
    assert rec.scope_tags[0]["group"] == "cages"
    assert "WROTE:" in capsys.readouterr().err


def test_condition_unknown_flag_default(tmp_path):
    journal = tmp_path / "qc.jsonl"
    assert cli.main(["condition", "--journal", str(journal),
                     "--package", "P", "--vendor", "V"]) == 0
    from estimating_tools.quotespace.conditions import read_conditions
    assert read_conditions(journal)[0].separate_acceptance_permitted is None


def test_condition_rejects_non_object_tag_cleanly(tmp_path, capsys):
    journal = tmp_path / "qc.jsonl"
    rc = cli.main(["condition", "--journal", str(journal),
                   "--package", "P", "--vendor", "V",
                   "--tag", '"just a string"'])
    assert rc == 1
    err = capsys.readouterr().err
    assert "JSON object" in err and "Traceback" not in err
    assert not journal.exists()


def test_condition_rejects_bad_tag_cleanly(tmp_path, capsys):
    journal = tmp_path / "qc.jsonl"
    rc = cli.main(["condition", "--journal", str(journal),
                   "--package", "P", "--vendor", "V",
                   "--tag", '{"group": "g", "items": [], "treatment": "folded"}'])
    assert rc == 1
    assert "folded_into" in capsys.readouterr().err
    assert not journal.exists()


def test_sync_emits_only_the_delta(tmp_path, capsys):
    journal = tmp_path / "solicitations.jsonl"
    # two local records: one already in BM (identical), one new
    cli.main(["solicit", "--journal", str(journal), "--package", "Rebar",
              "--vendor", "ACME", "--bm-package-id", "175", "--bm-vendor-id",
              "10", "--status", "sent", "--sent-at", "2026-08-07"])
    cli.main(["solicit", "--journal", str(journal), "--package", "Rebar",
              "--vendor", "Basalt", "--status", "planned"])
    bm = tmp_path / "bm.json"
    bm.write_text(json.dumps([
        {"work_package_id": 175, "vendor_id": 10, "status": "sent",
         "sent_at": "2026-08-07", "channel": "email", "contacts": [], "items": [],
         "notes": "", "work_package_name": "Rebar", "vendor_org_name": "ACME"}
    ]), encoding="utf-8")
    capsys.readouterr()
    rc = cli.main(["sync", "--journal", str(journal), "--bm-solicitations",
                   str(bm)])
    assert rc == 0
    delta = json.loads(capsys.readouterr().out)
    keys = {(d["work_package"]["name"], d["vendor"]["org_name"]) for d in delta}
    assert keys == {("Rebar", "Basalt")}          # ACME matched BM, excluded


def test_sync_pushes_changed_status(tmp_path, capsys):
    journal = tmp_path / "s.jsonl"
    cli.main(["solicit", "--journal", str(journal), "--package", "R",
              "--vendor", "V", "--bm-package-id", "1", "--bm-vendor-id", "2",
              "--status", "declined", "--notes", "no bid"])
    bm = tmp_path / "bm.json"
    bm.write_text(json.dumps([
        {"work_package_id": 1, "vendor_id": 2, "status": "sent",
         "sent_at": "2026-08-01", "channel": "email", "contacts": [], "items": [],
         "notes": "", "work_package_name": "R", "vendor_org_name": "V"}]),
        encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["sync", "--journal", str(journal),
                     "--bm-solicitations", str(bm)]) == 0
    delta = json.loads(capsys.readouterr().out)
    assert len(delta) == 1 and delta[0]["status"] == "declined"


def test_sync_empty_when_all_present(tmp_path, capsys):
    journal = tmp_path / "s.jsonl"
    cli.main(["solicit", "--journal", str(journal), "--package", "R",
              "--vendor", "V", "--bm-package-id", "1", "--bm-vendor-id", "2",
              "--status", "planned"])
    bm = tmp_path / "bm.json"
    bm.write_text(json.dumps([
        {"work_package_id": 1, "vendor_id": 2, "status": "planned",
         "sent_at": "", "channel": "email", "contacts": [], "items": [],
         "notes": "", "work_package_name": "R", "vendor_org_name": "V"}]),
        encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["sync", "--journal", str(journal),
                     "--bm-solicitations", str(bm)]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_sync_ignores_item_keyorder_and_contact_order(tmp_path, capsys):
    # Local and BM describe the SAME solicitation, but BM serializes item keys
    # and the contact list in a different order — must produce an EMPTY delta.
    journal = tmp_path / "s.jsonl"
    cli.main(["solicit", "--journal", str(journal), "--package", "R",
              "--vendor", "V", "--bm-package-id", "1", "--bm-vendor-id", "2",
              "--status", "sent", "--sent-at", "2026-08-07",
              "--contact", "a@x.com", "--contact", "b@x.com",
              "--items", '[{"schedule": "A", "item_number": "1"}]'])
    bm = tmp_path / "bm.json"
    bm.write_text(json.dumps([
        {"work_package_id": 1, "vendor_id": 2, "status": "sent",
         "sent_at": "2026-08-07", "channel": "email",
         "contacts": ["b@x.com", "a@x.com"],
         "items": [{"item_number": "1", "schedule": "A"}],
         "notes": "", "work_package_name": "R", "vendor_org_name": "V"}]),
        encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["sync", "--journal", str(journal),
                     "--bm-solicitations", str(bm)]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_sync_missing_name_field_exits_clean(tmp_path, capsys):
    journal = tmp_path / "s.jsonl"
    cli.main(["solicit", "--journal", str(journal), "--package", "R",
              "--vendor", "V", "--bm-package-id", "1", "--bm-vendor-id", "2",
              "--status", "planned"])
    bm = tmp_path / "bm.json"
    bm.write_text(json.dumps([
        {"work_package_id": 1, "vendor_id": 2, "status": "planned"}]),
        encoding="utf-8")  # no work_package_name / vendor_org_name
    capsys.readouterr()
    assert cli.main(["sync", "--journal", str(journal),
                     "--bm-solicitations", str(bm)]) == 1
    assert "invalid bm-solicitations row" in capsys.readouterr().err


def test_sync_out_of_vocab_status_exits_clean(tmp_path, capsys):
    journal = tmp_path / "s.jsonl"
    cli.main(["solicit", "--journal", str(journal), "--package", "R",
              "--vendor", "V", "--status", "planned"])
    bm = tmp_path / "bm.json"
    bm.write_text(json.dumps([
        {"work_package_id": 1, "vendor_id": 2, "status": "responded",
         "work_package_name": "R", "vendor_org_name": "V"}]),
        encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["sync", "--journal", str(journal),
                     "--bm-solicitations", str(bm)]) == 1
    assert "invalid bm-solicitations row" in capsys.readouterr().err


def test_sync_non_list_dump_exits_clean(tmp_path, capsys):
    journal = tmp_path / "s.jsonl"
    cli.main(["solicit", "--journal", str(journal), "--package", "R",
              "--vendor", "V", "--status", "planned"])
    bm = tmp_path / "bm.json"
    bm.write_text(json.dumps({"rows": []}), encoding="utf-8")  # object, not a list
    capsys.readouterr()
    assert cli.main(["sync", "--journal", str(journal),
                     "--bm-solicitations", str(bm)]) == 1
    assert "bm-solicitations must be a JSON list" in capsys.readouterr().err


def test_sync_non_dict_row_exits_clean(tmp_path, capsys):
    journal = tmp_path / "s.jsonl"
    cli.main(["solicit", "--journal", str(journal), "--package", "R",
              "--vendor", "V", "--status", "planned"])
    bm = tmp_path / "bm.json"
    bm.write_text(json.dumps(["not-a-row"]), encoding="utf-8")  # list of non-dict
    capsys.readouterr()
    assert cli.main(["sync", "--journal", str(journal),
                     "--bm-solicitations", str(bm)]) == 1
    assert "invalid bm-solicitations row" in capsys.readouterr().err
