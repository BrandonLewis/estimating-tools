from __future__ import annotations

import pytest
import yaml

from estimating_tools.heavycivil import style as S


def test_bundled_style_has_every_required_style():
    pack = S.load_style()
    assert pack.name == "heavycivil"
    missing = S.REQUIRED_STYLES - set(pack.tokens["styles"])
    assert not missing


def test_partial_override_changes_only_its_keys(tmp_path):
    (tmp_path / "tokens.yaml").write_text(yaml.safe_dump({"fills": {"input": "E8F0FE"}}))
    base = S.load_style()
    pack = S.load_style(tmp_path)
    assert pack.tokens["fills"]["input"] == "E8F0FE"
    assert pack.tokens["fills"]["band"] == base.tokens["fills"]["band"]
    assert pack.sheets == base.sheets
    assert pack.source == str(tmp_path)


def test_heading_rename_and_optional_hide(tmp_path):
    (tmp_path / "sheets.yaml").write_text(yaml.safe_dump({"columns": {"cost_report": {
        "other": {"show": False}, "labor": {"heading": "Labour"}}}}))
    pack = S.load_style(tmp_path)
    assert pack.column("cost_report", "labor")["heading"] == "Labour"
    assert pack.column("cost_report", "other")["show"] is False


def test_hiding_a_required_column_is_refused(tmp_path):
    (tmp_path / "sheets.yaml").write_text(yaml.safe_dump(
        {"columns": {"cost_report": {"total": {"show": False}}}}))
    with pytest.raises(S.StyleError, match=r"sheets\.yaml.*cost_report\.total"):
        S.load_style(tmp_path)


def test_styling_a_hidden_column_is_refused(tmp_path):
    (tmp_path / "sheets.yaml").write_text(yaml.safe_dump(
        {"columns": {"cost_report": {"v": {"width": 20}}}}))
    with pytest.raises(S.StyleError, match=r"cost_report\.v"):
        S.load_style(tmp_path)


def test_unknown_key_is_refused(tmp_path):
    (tmp_path / "sheets.yaml").write_text(yaml.safe_dump({"layout": {"order": []}}))
    with pytest.raises(S.StyleError, match="layout"):
        S.load_style(tmp_path)


def test_bad_tab_name_is_refused(tmp_path):
    (tmp_path / "sheets.yaml").write_text(yaml.safe_dump(
        {"sheets": {"crews": {"tab": "Crews/Rates"}}}))
    with pytest.raises(S.StyleError, match="tab"):
        S.load_style(tmp_path)


def test_duplicate_tab_names_are_refused(tmp_path):
    (tmp_path / "sheets.yaml").write_text(yaml.safe_dump(
        {"sheets": {"crews": {"tab": "Rates"}}}))
    with pytest.raises(S.StyleError, match="Rates"):
        S.load_style(tmp_path)


def test_style_naming_a_missing_token_is_refused(tmp_path):
    (tmp_path / "tokens.yaml").write_text(yaml.safe_dump(
        {"styles": {"label": {"fill": "nope"}}}))
    with pytest.raises(S.StyleError, match="nope"):
        S.load_style(tmp_path)


def test_resolve_prefers_cli_then_profile(tmp_path):
    from estimating_tools.profiles.model import Profile
    (tmp_path / "tokens.yaml").write_text(yaml.safe_dump({"fills": {"input": "111111"}}))
    profile = Profile(data={"estimating": {"heavycivil_style": str(tmp_path)}})
    assert S.resolve_style(None, profile).tokens["fills"]["input"] == "111111"
    assert S.resolve_style(None, Profile(data={})).source == "bundled"


def test_missing_style_directory_is_refused(tmp_path):
    with pytest.raises(S.StyleError, match="no such"):
        S.load_style(tmp_path / "absent")


@pytest.mark.parametrize("conf, match", [
    ({"sheets": {"crews": {"tab_color": "12345"}}}, "tab_color"),
    ({"sheets": {"crews": {"tab_color": "GGGGGG"}}}, "tab_color"),
    ({"sheets": {"crews": {"freeze": "5C"}}}, "freeze"),
    ({"sheets": {"crews": {"freeze": "B0"}}}, "freeze"),
    ({"sheets": {"crews": {"print": {"orientation": "sideways"}}}}, "orientation"),
    ({"columns": {"crews": {"name": {"width": -3}}}}, "width"),
    ({"columns": {"crews": {"name": {"width": "wide"}}}}, "width"),
    ({"columns": {"crews": {"name": {"width": True}}}}, "width"),
    ({"sheets": {"crews": {"tab": "rates"}}}, "rates"),
    ({"sheets": {"crews": {"tab": "History"}}}, "History"),
    ({"sheets": {"crews": {"tab": "HISTORY"}}}, "HISTORY"),
])
def test_bad_style_values_are_refused(tmp_path, conf, match):
    (tmp_path / "sheets.yaml").write_text(yaml.safe_dump(conf))
    with pytest.raises(S.StyleError, match=match):
        S.load_style(tmp_path)


def test_good_style_values_are_accepted(tmp_path):
    (tmp_path / "sheets.yaml").write_text(yaml.safe_dump({
        "sheets": {"crews": {"tab_color": "a1b2c3", "freeze": "AB12",
                             "print": {"orientation": "portrait"}}},
        "columns": {"crews": {"name": {"width": 12.5}}}}))
    assert S.load_style(tmp_path).sheets["crews"]["freeze"] == "AB12"


def test_lowercase_freeze_is_accepted_as_uppercase(tmp_path):
    (tmp_path / "sheets.yaml").write_text(yaml.safe_dump({"sheets": {"crews": {"freeze": "c5"}}}))
    assert S.load_style(tmp_path).sheets["crews"]["freeze"] == "C5"


def test_bid_form_tab_can_be_renamed(tmp_path):
    (tmp_path / "sheets.yaml").write_text(yaml.safe_dump(
        {"sheets": {"bid_form": {"tab": "Bid Schedule"}}}))
    pack = S.load_style(tmp_path)
    assert pack.tab("bid_form") == "Bid Schedule"
    assert pack.sheets["bid_form"]["freeze"] == "C13"


def test_new_sheets_have_tabs_and_new_styles():
    pack = S.load_style()
    assert [pack.tab(k) for k in ("bid_form", "recap", "schedule", "flat")] == \
        ["Bid Form", "Recap", "Schedule", "Flat"]
    assert {"section_text", "schedule_bar", "calc_date", "export_date", "total_label",
            "total_money", "input_select"} <= S.REQUIRED_STYLES
    assert pack.tokens["number_formats"]["date"] == "yyyy-mm-dd"
