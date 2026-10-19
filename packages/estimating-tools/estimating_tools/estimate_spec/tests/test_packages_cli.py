"""`est-estimate packages init | sync | coverage`."""
from __future__ import annotations

import copy
import json

import pytest
import yaml

from estimating_tools.estimate_spec import cli
from estimating_tools.estimate_spec.packages import (
    init_packages, package_coverage, sync_package_lines)
from estimating_tools.estimate_spec.tests._fieldbook import EXAMPLE, example_spec
from estimating_tools.estimate_spec.validate import validate_cross_references
from estimating_tools.quotes.model import CanonicalQuote, QuoteLine

PACKAGES_YAML = {"packages": [
    {"name": "Haul", "strategy": "subcontract", "scope": "Import and export",
     "items": ["1", "2"], "conditions": ["Dump fees by others"]},
    {"name": "Pipe", "strategy": "self_perform", "items": [2]},
]}


@pytest.fixture(autouse=True)
def _no_ambient_profile(monkeypatch):
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)


def _with_packages():
    spec = example_spec()
    init_packages(spec, PACKAGES_YAML)
    return spec


def _lines(spec, n):
    item = next(i for i in spec["items"] if str(i["item_no"]) == n)
    return [ln for b in item["labor"] for ln in b.get("lines", [])]


def test_init_maps_strategy_to_kind_and_copies_only_what_is_present():
    spec = example_spec()
    report = init_packages(spec, PACKAGES_YAML)
    haul, pipe = spec["work_packages"]
    assert (haul["kind"], pipe["kind"]) == ("subcontract", "supply")
    assert haul["selected"] == pipe["selected"] == "ARR"
    assert haul["conditions"] == ["Dump fees by others"] and "detail" not in haul
    assert pipe["items"] == ["2"] and "scope" not in pipe and "conditions" not in pipe
    assert len(report) == 2 and "Haul" in report[0]
    validate_cross_references(spec)


def test_init_refuses_an_existing_list():
    spec = _with_packages()
    with pytest.raises(ValueError, match="already"):
        init_packages(spec, PACKAGES_YAML)


def test_sync_tags_adds_and_is_idempotent():
    spec = _with_packages()
    report = sync_package_lines(spec)
    haul = next(ln for ln in _lines(spec, "2") if ln["name"] == "Haul, import + export")
    pipe = next(ln for ln in _lines(spec, "2") if ln["name"] == "8-inch ductile iron pipe")
    assert haul["package"] == "Haul" and pipe["package"] == "Pipe"
    rock = next(ln for ln in _lines(spec, "2") if ln["name"] == "Bedding rock")
    assert rock["package"] == "Pipe"  # every untagged material line of a supply item
    trench = next(ln for ln in _lines(spec, "2") if ln["cost_type"] == "equipment")
    assert "package" not in trench
    added = _lines(spec, "1")
    assert added == [{"cost_type": "subcontract", "name": "Haul", "qty": 1, "uom": "LS",
                      "unit_price": 0, "source": "plug", "vendor": "Haul", "package": "Haul"}]
    assert len(report.tagged) == 3 and len(report.added) == 1 and report.ambiguous == []
    validate_cross_references(spec)
    snapshot = copy.deepcopy(spec)
    again = sync_package_lines(spec)
    assert spec == snapshot and again.changes == 0


def test_sync_leaves_lines_of_another_package_and_says_so():
    spec = _with_packages()
    spec["work_packages"].append({"name": "Other", "kind": "subcontract", "items": ["2"]})
    sync_package_lines(spec)
    report = sync_package_lines(spec)
    assert report.ambiguous == [
        "Other: item '2' -- its subcontract lines already belong to Haul"]


def _quote(pkg, *lines, vendor="V"):
    return CanonicalQuote(vendor_name=vendor, work_package_name=pkg, lines=list(lines))


def test_coverage_reports_each_gap():
    spec = _with_packages()
    sync_package_lines(spec)
    assert package_coverage(spec, []) == ["Haul: no quote", "Pipe: no quote"]
    q = _quote("Haul", QuoteLine("Main", "2", line_name="Haul, import + export"),
               QuoteLine("Main", "3"))
    assert package_coverage(spec, [q]) == [
        "Haul: V quotes item '3' which is not in the package",
        "Haul: item '1' line 'Haul' priced by nobody",
        "Pipe: no quote",
    ]


def test_init_never_writes_a_null_strategy():
    spec = example_spec()
    init_packages(spec, {"packages": [{"name": "Signals", "items": ["1"]},
                                      {"name": "Fence", "strategy": "", "items": ["1"]}]})
    assert all("strategy" not in p for p in spec["work_packages"])
    assert "strategy" not in yaml.safe_dump(spec["work_packages"])
    validate_cross_references(spec)


def test_coverage_matches_the_package_name_case_insensitively():
    spec = _with_packages()
    sync_package_lines(spec)
    q = _quote(" haul ", QuoteLine("Main", "2", line_name="Haul, import + export"),
               QuoteLine("Main", "1"))
    assert package_coverage(spec, [q]) == ["Pipe: no quote"]


def test_a_lump_sum_quote_prices_every_included_line():
    spec = _with_packages()
    sync_package_lines(spec)
    lump = CanonicalQuote(vendor_name="L", work_package_name="Haul", amount=9000)
    assert package_coverage(spec, [lump]) == ["Pipe: no quote"]
    # ... but not a line it excludes, nor one only an alternate prices
    lump.lines = [QuoteLine("Main", "1", is_included=False)]
    alt = _quote("Haul", QuoteLine("Main", "1", unit_price=5, is_alternate=True), vendor="A")
    assert package_coverage(spec, [lump, alt]) == [
        "Haul: item '1' line 'Haul' priced by nobody", "Pipe: no quote"]


def _bid(tmp_path):
    spec = tmp_path / "bid.estimate.yaml"
    spec.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    src = tmp_path / "work-packages.yaml"
    src.write_text(yaml.safe_dump(PACKAGES_YAML), encoding="utf-8")
    return spec, src


def _backups(spec):
    return sorted(spec.parent.glob(spec.name + ".bak-*"))


def test_cli_init_dry_run_then_write_with_backup(tmp_path, capsys):
    spec, src = _bid(tmp_path)
    before = spec.read_bytes()
    assert cli.main(["packages", "init", str(spec), "--from", str(src)]) == 0
    out = capsys.readouterr().out
    assert "dry run: 2 change(s) -- run again with --write to apply them" in out
    assert spec.read_bytes() == before and _backups(spec) == []
    assert cli.main(["packages", "init", str(spec), "--from", str(src), "--write"]) == 0
    assert len(_backups(spec)) == 1
    assert _backups(spec)[0].read_bytes() == before
    written = yaml.safe_load(spec.read_text(encoding="utf-8"))
    assert [p["name"] for p in written["work_packages"]] == ["Haul", "Pipe"]
    # a second init is a ValueError: exit 1, spec untouched
    after = spec.read_bytes()
    assert cli.main(["packages", "init", str(spec), "--from", str(src), "--write"]) == 1
    assert spec.read_bytes() == after


def test_cli_sync_and_coverage(tmp_path, capsys):
    spec, src = _bid(tmp_path)
    cli.main(["packages", "init", str(spec), "--from", str(src), "--write"])
    capsys.readouterr()
    assert cli.main(["packages", "sync", str(spec), "--write"]) == 0
    assert "added item '1' line 'Haul'" in capsys.readouterr().out
    assert cli.main(["packages", "sync", str(spec), "--write"]) == 0
    assert "nothing to write" in capsys.readouterr().out
    qdir = tmp_path / "quotes"
    qdir.mkdir()
    (qdir / "v.json").write_text(json.dumps({
        "vendor_name": "V", "work_package_name": "Haul",
        "lines": [{"schedule_name": "Main", "item_number": "2",
                   "line_name": "Haul, import + export", "unit_price": 18}]}), encoding="utf-8")
    assert cli.main(["packages", "coverage", str(spec)]) == 0
    out = capsys.readouterr().out
    assert "Haul: item '1' line 'Haul' priced by nobody" in out
    assert "Pipe: no quote" in out


def test_cli_file_problems_exit_2(tmp_path, capsys):
    assert cli.main(["packages", "sync", str(tmp_path / "missing.yaml")]) == 2
    spec, src = _bid(tmp_path)
    assert cli.main(["packages", "init", str(spec), "--from", str(tmp_path / "no.yaml")]) == 2
    qdir = tmp_path / "quotes"
    qdir.mkdir()
    (qdir / "bad.json").write_text("{not json", encoding="utf-8")
    cli.main(["packages", "init", str(spec), "--from", str(src), "--write"])
    assert cli.main(["packages", "coverage", str(spec)]) == 2


def test_sync_leaves_a_hand_tagged_item_alone():
    spec = _with_packages()
    for ln in _lines(spec, "2"):
        ln.pop("package", None)
    trench = next(ln for ln in _lines(spec, "2") if ln["name"] == "Trench box (rental)")
    trench["package"] = "Hauling"
    spec["work_packages"] = [{"name": "Hauling", "kind": "subcontract", "items": ["2"]}]
    snapshot = copy.deepcopy(spec)
    report = sync_package_lines(spec)
    assert report.changes == 0 and report.added == [] and spec == snapshot


def test_sync_never_changes_a_tagged_line():
    spec = _with_packages()
    sync_package_lines(spec)
    for ln in _lines(spec, "2"):
        if ln.get("package"):
            ln["package"] = "Elsewhere"
    snapshot = copy.deepcopy(spec)
    sync_package_lines(spec)
    assert [ln.get("package") for ln in _lines(spec, "2")] == [
        ln.get("package") for ln in _lines(snapshot, "2")]
