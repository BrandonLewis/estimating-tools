import os
import warnings
from pathlib import Path

from estimating_tools.profiles.loader import discover, load, load_one


def _write(d: Path, text: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.yaml").write_text(text)
    return d


def test_discover_orders_existing_dirs_and_skips_missing(tmp_path):
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    env = {"ESTIMATING_PROFILES": os.pathsep.join([str(a), str(tmp_path / "missing"), str(b)])}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dirs = discover(env)
    assert dirs == [a, b]


def test_discover_unset_is_empty():
    assert discover({}) == []


def test_load_cascades_org_then_agency(tmp_path):
    org = _write(tmp_path / "org", "kind: org\nname: Acme\nletterhead:\n  company_name: Acme\n")
    agency = _write(tmp_path / "ag", "kind: agency\nname: CT\nargot:\n  spec_note: 'CT 48-2'\n")
    prof = load([org, agency])
    assert prof.section("letterhead")["company_name"] == "Acme"
    assert prof.section("argot")["spec_note"] == "CT 48-2"
    assert prof.sources == (str(org), str(agency))


def test_load_default_when_no_dirs():
    prof = load([])
    assert prof.is_empty


def test_per_field_validation_drops_bad_field_keeps_rest(tmp_path):
    # argot must be an object; here it's a string -> dropped, name kept
    d = _write(tmp_path / "p", "name: P\nargot: 'not-an-object'\n")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        prof = load([d])
    assert prof.data.get("name") == "P"
    assert "argot" not in prof.data
    assert any("argot" in str(w.message) for w in caught)


def test_unknown_field_dropped_with_warning(tmp_path):
    d = _write(tmp_path / "p", "name: P\nbogus: 1\n")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        prof = load([d])
    assert "bogus" not in prof.data
    assert any("bogus" in str(w.message) for w in caught)


def test_house_rules_survive_validation(tmp_path):
    d = _write(tmp_path / "p", (
        "name: P\n"
        "house_rules:\n"
        "  - name: unit price governs\n"
        "    rule: recompute extension as qty x unit; never back-solve unit\n"
        "    exceptions: display-rounded units whose extensions reconcile to the total\n"
    ))
    with warnings.catch_warnings():
        warnings.simplefilter("error")          # a dropped-field warning fails the test
        prof = load([d])
    assert prof.data["house_rules"][0]["name"] == "unit price governs"


def test_asset_paths_resolve_to_absolute(tmp_path):
    d = _write(tmp_path / "p", "letterhead:\n  template: lh.docx\nfolder_conventions:\n  tree: trees/t.yaml\n")
    sections = load_one(d)
    assert sections["letterhead"]["template"] == str((d / "lh.docx").resolve())
    assert sections["folder_conventions"]["tree"] == str((d / "trees" / "t.yaml").resolve())


def test_discover_warns_on_missing_entry(tmp_path):
    a = tmp_path / "a"; a.mkdir()
    env = {"ESTIMATING_PROFILES": os.pathsep.join([str(a), str(tmp_path / "missing")])}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        discover(env)
    assert any("missing" in str(w.message) for w in caught)


def test_asset_absolute_ref_left_unchanged(tmp_path):
    abs_tpl = (tmp_path / "abs" / "lh.docx")
    d = tmp_path / "p"; d.mkdir()
    (d / "profile.yaml").write_text(f"letterhead:\n  template: {abs_tpl}\n")
    sections = load_one(d)
    assert sections["letterhead"]["template"] == str(abs_tpl)


def test_non_mapping_profile_yields_empty_with_warning(tmp_path):
    d = tmp_path / "p"; d.mkdir()
    (d / "profile.yaml").write_text("just a scalar string\n")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        prof = load([d])
    assert prof.is_empty
    assert any("not a mapping" in str(w.message) for w in caught)
