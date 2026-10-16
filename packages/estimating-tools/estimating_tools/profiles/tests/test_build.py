import warnings

import pytest
import yaml

from estimating_tools.profiles.build import ProfileInputs, build_profile_dir
from estimating_tools.profiles.loader import load_one


def _full() -> ProfileInputs:
    return ProfileInputs(
        name="Acme Builders", company_name="Acme Builders, Inc.",
        address="123 Main St, Springfield", logo="logo.png",
        tree="- Estimates\n- Quotes\n", letterhead="# Acme letterhead\n",
        compliance_label="DBE Goal", spec_note="2026 Std Specs",
        naming={"project": "{number}-{name}"},
    )


def test_returns_three_files_with_asset_refs():
    files = build_profile_dir(_full())
    assert set(files) == {"profile.yaml", "tree.yaml", "letterhead.md"}
    prof = yaml.safe_load(files["profile.yaml"])
    assert prof["kind"] == "org" and prof["name"] == "Acme Builders"
    assert prof["letterhead"]["template"] == "letterhead.md"
    assert prof["letterhead"]["company_name"] == "Acme Builders, Inc."
    assert prof["folder_conventions"]["tree"] == "tree.yaml"
    assert prof["argot"] == {"compliance_label": "DBE Goal", "spec_note": "2026 Std Specs"}
    assert prof["naming"] == {"project": "{number}-{name}"}
    assert files["tree.yaml"] == "- Estimates\n- Quotes\n"
    assert files["letterhead.md"] == "# Acme letterhead\n"


def test_logo_referenced_only_when_provided():
    with_logo = yaml.safe_load(build_profile_dir(_full())["profile.yaml"])
    assert with_logo["letterhead"]["logo"] == "logo.png"
    no_logo = yaml.safe_load(build_profile_dir(ProfileInputs(name="A"))["profile.yaml"])
    assert "logo" not in no_logo["letterhead"]
    # a whitespace-only logo is treated as no logo (stripped, like company_name/address)
    blank_logo = yaml.safe_load(build_profile_dir(ProfileInputs(name="A", logo="   "))["profile.yaml"])
    assert "logo" not in blank_logo["letterhead"]


def test_minimal_input_is_valid_and_omits_empty_sections():
    files = build_profile_dir(ProfileInputs(name="Solo Co"))
    prof = yaml.safe_load(files["profile.yaml"])
    assert prof["name"] == "Solo Co" and prof["kind"] == "org"
    assert prof["letterhead"]["template"] == "letterhead.md"
    assert prof["folder_conventions"]["tree"] == "tree.yaml"
    assert "argot" not in prof and "naming" not in prof
    # default tree + letterhead are non-empty
    assert files["tree.yaml"].strip() and files["letterhead.md"].strip()
    # the default tree is a YAML list (consumable by materialize_tree), not a scalar
    assert isinstance(yaml.safe_load(files["tree.yaml"]), list)


def test_blank_name_raises():
    with pytest.raises(ValueError, match=r"name"):
        build_profile_dir(ProfileInputs(name="  "))


def test_schema_violation_raises_valueerror():
    # naming must be an object; a list violates the schema -> ValueError (not raw jsonschema)
    with pytest.raises(ValueError):
        build_profile_dir(ProfileInputs(name="A", naming=["not", "a", "dict"]))


def test_house_rules_emitted_when_provided_and_omitted_when_not():
    rules = [
        {"name": "unit price governs", "rule": "recompute extension as qty x unit",
         "exceptions": "display-rounded unit columns whose extensions reconcile to the total"},
        {"name": "cost-vs-pay quantity", "rule": "bid unit price = total cost / pay quantity"},
    ]
    prof = yaml.safe_load(
        build_profile_dir(ProfileInputs(name="A", house_rules=rules))["profile.yaml"])
    assert prof["house_rules"] == rules
    without = yaml.safe_load(build_profile_dir(ProfileInputs(name="A"))["profile.yaml"])
    assert "house_rules" not in without


def test_house_rules_schema_violation_raises():
    # each rule needs name + rule; a bare string violates the schema
    with pytest.raises(ValueError):
        build_profile_dir(ProfileInputs(name="A", house_rules=["not-an-object"]))


def test_output_loads_through_loader_without_warnings(tmp_path):
    files = build_profile_dir(ProfileInputs(name="Acme Builders", company_name="Acme, Inc."))
    for fname, content in files.items():
        (tmp_path / fname).write_text(content)
    with warnings.catch_warnings():
        warnings.simplefilter("error")          # any loader warning fails the test
        sections = load_one(tmp_path)
    assert sections["kind"] == "org" and sections["name"] == "Acme Builders"
    # the asset fields are resolved to absolute paths pointing at the written files
    assert sections["folder_conventions"]["tree"] == str((tmp_path / "tree.yaml").resolve())
    assert sections["letterhead"]["template"] == str((tmp_path / "letterhead.md").resolve())
