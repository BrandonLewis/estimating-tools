import pytest

from estimating_tools.importers.mapping_artifact import (
    MappingRow, ProposedMapping, parse, propose_mapping, render, to_mapping_dict,
)


def _pm(*rows):
    return ProposedMapping(rows=tuple(MappingRow(*r) for r in rows))


def test_render_shape_and_required_marker():
    pm = _pm(
        ("rate_type", "Type", True, ("labor", "equipment")),
        ("name", "Classification", True, ("Carpenter",)),
        ("burden_percentage", "Burden %", False, ("35",)),
    )
    out = render(pm)
    assert out.startswith("<!--")                        # editability hint
    assert "| Canonical field | Spreadsheet column | Sample values |" in out
    assert "| --- | --- | --- |" in out
    assert "| rate_type* | Type | labor; equipment |" in out
    assert "| name* | Classification | Carpenter |" in out
    assert "| burden_percentage | Burden % | 35 |" in out  # no asterisk on optional
    assert not out.endswith("\n")                        # md_table contract


def test_render_uses_dash_for_skipped_column():
    pm = _pm(("region", None, False, ()))
    out = render(pm)
    assert "| region | - | " in out                      # skipped col is '-'


def test_parse_roundtrip():
    pm = _pm(
        ("rate_type", "Type", True, ("labor", "equipment")),
        ("name", "Classification", True, ("Carpenter",)),
        ("region", None, False, ()),
    )
    assert parse(render(pm)) == pm


def test_parse_after_user_rename_column():
    pm = _pm(
        ("rate_type", "Type", True, ("labor",)),
        ("name", "Classification", True, ("Carpenter",)),
    )
    edited = render(pm).replace("| Classification |", "| Trade Name |")
    reparsed = parse(edited)
    assert reparsed.rows[1].spreadsheet_column == "Trade Name"
    assert reparsed.rows[0].spreadsheet_column == "Type"   # unchanged


def test_parse_after_user_skips_a_field():
    pm = _pm(
        ("rate_type", "Type", True, ("labor",)),
        ("region", "Region", False, ("Norcal",)),
    )
    edited = render(pm).replace("| Region |", "| - |")
    reparsed = parse(edited)
    assert reparsed.rows[1].spreadsheet_column is None


def test_parse_after_user_removes_a_row():
    pm = _pm(
        ("rate_type", "Type", True, ("labor",)),
        ("region", "Region", False, ("Norcal",)),
        ("trade", "Trade", False, ()),
    )
    text = render(pm)
    edited = "\n".join(line for line in text.splitlines() if "| region |" not in line)
    reparsed = parse(edited)
    assert [r.canonical_field for r in reparsed.rows] == ["rate_type", "trade"]


def test_parse_pipe_in_cell_roundtrips():
    pm = _pm(("name", "Full|Name", True, ("Ac|me",)))
    assert parse(render(pm)) == pm


def test_parse_raises_on_missing_column_cell():
    text = (
        "<!-- editable -->\n"
        "| Canonical field | Spreadsheet column | Sample values |\n"
        "| --- | --- | --- |\n"
        "| rate_type* | Type |\n"                       # missing sample column
    )
    try:
        parse(text)
    except ValueError as e:
        assert "row 1" in str(e).lower() and ("column" in str(e).lower())
    else:
        raise AssertionError("expected ValueError")


def test_parse_raises_on_unknown_asterisk_use():
    """A row whose canonical_field ends with '*' but that we did not construct is
    still parsed by stripping the asterisk. Two rows with the same canonical_field
    is an ambiguity."""
    text = (
        "<!-- editable -->\n"
        "| Canonical field | Spreadsheet column | Sample values |\n"
        "| --- | --- | --- |\n"
        "| rate_type* | Type |  |\n"
        "| rate_type | Also Type |  |\n"
    )
    try:
        parse(text)
    except ValueError as e:
        assert "duplicate" in str(e).lower() and "rate_type" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_to_mapping_dict_skips_identity_and_none():
    pm = _pm(
        ("rate_type", "rate_type", True, ()),          # identity — omit
        ("name", "Classification", True, ()),          # non-identity — keep
        ("region", None, False, ()),                   # skipped — omit
    )
    assert to_mapping_dict(pm) == {"name": "Classification"}


def test_propose_mapping_exact_and_snake_case_matches():
    canonical = ("rate_type", "name", "region", "burden_percentage")
    required = ("rate_type", "name")
    headers = ["Rate Type", "Classification", "Region", "burden_percentage"]
    rows = [
        {"Rate Type": "labor", "Classification": "Carpenter", "Region": "Norcal",
         "burden_percentage": 35},
        {"Rate Type": "labor", "Classification": "Ironworker", "Region": "Socal",
         "burden_percentage": 40},
    ]
    pm = propose_mapping(canonical, required, headers, rows)
    guesses = {r.canonical_field: r.spreadsheet_column for r in pm.rows}
    assert guesses["rate_type"] == "Rate Type"                # snake ↔ Title case
    assert guesses["region"] == "Region"                      # case-insensitive
    assert guesses["burden_percentage"] == "burden_percentage" # identity


def test_propose_mapping_leaves_unmatched_as_none():
    canonical = ("rate_type", "trade")
    required = ("rate_type",)
    headers = ["Type"]
    rows = [{"Type": "labor"}]
    pm = propose_mapping(canonical, required, headers, rows)
    guesses = {r.canonical_field: r.spreadsheet_column for r in pm.rows}
    assert guesses["rate_type"] is None                        # nothing matches
    assert guesses["trade"] is None


def test_propose_mapping_marks_required_and_samples_up_to_3():
    canonical = ("name",)
    required = ("name",)
    headers = ["Name"]
    rows = [{"Name": v} for v in ("Carpenter", "Ironworker", "Painter", "Roofer")]
    pm = propose_mapping(canonical, required, headers, rows)
    row = pm.rows[0]
    assert row.is_required
    assert row.sample_values == ("Carpenter", "Ironworker", "Painter")   # max 3


def test_parse_semicolon_in_sample_roundtrips():
    pm = _pm(("name", "Col", False, ("a;b", "c;d;e")))
    assert parse(render(pm)) == pm


def test_mapping_row_rejects_canonical_field_ending_in_asterisk():
    with pytest.raises(ValueError, match="must not end with"):
        MappingRow("foo*", "Col", False, ())


def test_parse_raises_when_header_missing():
    text = "| foo | bar | baz |\n| --- | --- | --- |\n| rate_type* | Type |  |\n"
    with pytest.raises(ValueError, match="header row"):
        parse(text)


def test_parse_tolerates_indented_table():
    pm = _pm(("rate_type", "Type", True, ("labor",)))
    indented = "\n".join("  " + line for line in render(pm).splitlines())
    assert parse(indented) == pm


def test_to_mapping_dict_raises_on_skipped_required():
    pm = _pm(
        ("rate_type", None, True, ()),
        ("name", "Classification", True, ()),
    )
    with pytest.raises(ValueError, match="rate_type"):
        to_mapping_dict(pm)


def test_to_mapping_dict_explicit_required_overrides_is_required():
    """When the caller passes an explicit `required` set, it wins over is_required."""
    import pytest
    pm = _pm(
        # is_required=False here — but caller says rate_type IS required, so skip must raise
        ("rate_type", None, False, ()),
        ("name", "Classification", True, ()),
    )
    # Without explicit required: no raise (falls back to is_required — False)
    assert to_mapping_dict(pm) == {"name": "Classification"}
    # With explicit required containing rate_type: raise
    with pytest.raises(ValueError, match="rate_type"):
        to_mapping_dict(pm, required={"rate_type"})


def test_to_mapping_dict_explicit_required_ignores_non_required_star_marker():
    """When explicit `required` is passed, is_required is ignored for the skip check.
    A row marked required (is_required=True) but NOT in the explicit required set may be
    skipped without raising."""
    pm = _pm(
        ("optional_but_starred", None, True, ()),   # is_required True (has *), but caller says not required
        ("name", "Classification", True, ()),
    )
    assert to_mapping_dict(pm, required={"name"}) == {"name": "Classification"}
