from estimating_tools.profiles.merge import merge
from estimating_tools.profiles.model import Profile


def test_merge_later_layer_wins_and_deep_merges():
    base = {"argot": {"compliance_label": "Compliance", "spec_note": "base"}}
    org = {"letterhead": {"company_name": "Acme"}}
    agency = {"argot": {"spec_note": "Caltrans 48-2"}}  # overrides nested key only
    merged = merge([base, org, agency])
    assert merged["argot"]["spec_note"] == "Caltrans 48-2"
    assert merged["argot"]["compliance_label"] == "Compliance"  # preserved from base
    assert merged["letterhead"]["company_name"] == "Acme"


def test_merge_extra_top_layer_overrides_lower():
    # forward-compat seam for the deferred enforcement tier
    merged = merge([{"argot": {"spec_note": "x"}}, {"argot": {"spec_note": "ENFORCED"}}])
    assert merged["argot"]["spec_note"] == "ENFORCED"


def test_merge_empty_list_is_empty_dict():
    assert merge([]) == {}


def test_profile_section_and_is_empty():
    p = Profile(data={"argot": {"spec_note": "n"}}, sources=("/p",))
    assert p.section("argot") == {"spec_note": "n"}
    assert p.section("missing") == {}
    assert not p.is_empty
    assert Profile(data={}, sources=()).is_empty
