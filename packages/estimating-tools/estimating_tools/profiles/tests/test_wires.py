import pytest
from pathlib import Path
from estimating_tools.profiles.model import Profile
from estimating_tools.profiles.wires import to_calc_meta, to_letterhead


def test_to_calc_meta_extracts_present_argot_keys():
    p = Profile(data={"argot": {"compliance_label": "Compliance (CT 48-2.01D(3))",
                                "spec_note": "CT 48-2.01D(3). PE seal required."}})
    meta = to_calc_meta(p)
    assert meta == {"compliance_label": "Compliance (CT 48-2.01D(3))",
                    "spec_note": "CT 48-2.01D(3). PE seal required."}


def test_to_calc_meta_omits_absent_keys():
    assert to_calc_meta(Profile(data={"argot": {"spec_note": "only note"}})) == {"spec_note": "only note"}


def test_to_calc_meta_empty_profile_is_empty_dict():
    assert to_calc_meta(Profile(data={})) == {}


def test_calc_sheet_meta_default_keys_match_agnostic_seam():
    # The argot wire must only ever supply keys calc_sheet actually reads.
    # calc_sheet.py reads meta["compliance_label"] and meta["spec_note"]
    # (plus project_label, which is project- not profile-derived).
    from estimating_tools.profiles.wires import _ARGOT_KEYS
    assert set(_ARGOT_KEYS) == {"compliance_label", "spec_note"}


def test_to_letterhead_returns_template_path_and_frontmatter(tmp_path):
    tpl = tmp_path / "lh.docx"; tpl.write_bytes(b"x")
    p = Profile(data={"letterhead": {"template": str(tpl), "company_name": "Acme", "address": "123 Main"}})
    path, frontmatter = to_letterhead(p)
    assert path == tpl
    assert frontmatter == {"company_name": "Acme", "address": "123 Main"}


def test_to_letterhead_missing_section_raises():
    with pytest.raises(ValueError):
        to_letterhead(Profile(data={}))


def test_to_letterhead_missing_file_raises(tmp_path):
    p = Profile(data={"letterhead": {"template": str(tmp_path / "nope.docx")}})
    with pytest.raises(FileNotFoundError):
        to_letterhead(p)
