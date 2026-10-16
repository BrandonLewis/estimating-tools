import copy
from pathlib import Path

import pytest

from estimating_tools.estimate_spec.artifact import find_item, replace_item
from estimating_tools.estimate_spec import format_pack as fp


DEMO_DIR = fp.ENGINE_DIR / "packs" / "demo"
ALT_DIR = Path(__file__).resolve().parent / "fixtures" / "packs" / "alt"


@pytest.fixture(scope="module")
def demo_pack():
    return fp.load_pack(DEMO_DIR)


@pytest.fixture(autouse=True)
def _bundled_pack_is_alt(monkeypatch):
    """render_item/parse_item below call `pack or bundled_pack()` — this
    file's items use recipe/trade literals from the alt pack's OWN
    vocabulary (preamble/work_item; FITTER/RIGGER/WELDER/OPER/HELPER), so
    they need a bundled pack that supports `artifact` and shares that
    vocabulary. Redirecting `bundled_pack()` to the alt pack — rather than
    depending on whichever pack format_pack.py actually bundles — is what
    lets this file's ~60 render/parse calls omit `pack=` individually while
    still not depending on the real default."""
    alt = fp.load_pack(ALT_DIR)
    monkeypatch.setattr(fp, "bundled_pack", lambda: alt)


def _spec():
    return {
        "project": "Sample",
        "markup": 100,
        "rate_table": [{"trade": "FITTER", "rate": 150}],
        "items": [
            {"item_no": "Item # 1", "recipe": "preamble", "sheet": "MOB",
             "description": "Mob", "uom": "LS", "labor": []},
            {"item_no": "Item # 41", "recipe": "work_item", "sheet": "S41",
             "description": "Trash", "uom": "EA", "labor": []},
            {"item_no": "Item # 42", "recipe": "work_item", "sheet": "S42",
             "description": "Outfall", "uom": "CY", "labor": []},
        ],
    }


def test_find_item_returns_object_identity():
    spec = _spec()
    got = find_item(spec, "Item # 41")
    assert got is spec["items"][1]


def test_find_item_missing_raises_with_locator():
    spec = _spec()
    with pytest.raises(KeyError, match=r"Item # 99.*Item # 1.*Item # 41.*Item # 42"):
        find_item(spec, "Item # 99")


def test_replace_item_returns_new_spec_with_target_swapped():
    spec = _spec()
    new_item = {"item_no": "Item # 41", "recipe": "work_item", "sheet": "S41",
                "description": "Trash (updated)", "uom": "EA", "labor": []}
    updated = replace_item(spec, "Item # 41", new_item)
    assert updated["items"][1]["description"] == "Trash (updated)"
    # Byte-identical other items
    assert updated["items"][0] == spec["items"][0]
    assert updated["items"][2] == spec["items"][2]
    # Order preserved
    assert [it["item_no"] for it in updated["items"]] == [
        "Item # 1", "Item # 41", "Item # 42",
    ]


def test_replace_item_does_not_mutate_input():
    spec = _spec()
    before = copy.deepcopy(spec)
    replace_item(spec, "Item # 41", {"item_no": "Item # 41", "recipe": "work_item",
                                     "sheet": "S41", "description": "x", "uom": "EA",
                                     "labor": []})
    assert spec == before                                         # input untouched


def test_replace_item_missing_raises():
    spec = _spec()
    with pytest.raises(KeyError, match="Item # 99"):
        replace_item(spec, "Item # 99", {"item_no": "Item # 99", "recipe": "preamble",
                                         "sheet": "X", "description": "x", "uom": "LS",
                                         "labor": []})


# ---- #257: x-* namespaced metadata survives the artifact round trip ---------
def test_replace_item_preserves_x_metadata_absent_from_new_item():
    """`x-*` is machine metadata never surfaced in the editable artifact, so a
    render->parse->replace round trip drops it from the parsed item. replace_item
    must carry it forward from the existing item, or #257's "persistent item
    metadata" promise breaks exactly where the consumer reported it."""
    spec = _spec()
    spec["items"][1]["x-work-type"] = "formliner"
    parsed = {"item_no": "Item # 41", "recipe": "work_item", "sheet": "S41",
              "description": "Trash (edited)", "uom": "EA", "labor": []}  # no x-*
    updated = replace_item(spec, "Item # 41", parsed)
    assert updated["items"][1]["x-work-type"] == "formliner"
    assert updated["items"][1]["description"] == "Trash (edited)"        # edit still applied


def test_replace_item_new_x_metadata_wins_over_original():
    spec = _spec()
    spec["items"][1]["x-work-type"] = "formliner"
    parsed = {"item_no": "Item # 41", "recipe": "work_item", "sheet": "S41",
              "description": "Trash", "uom": "EA", "labor": [], "x-work-type": "gang-form"}
    updated = replace_item(spec, "Item # 41", parsed)
    assert updated["items"][1]["x-work-type"] == "gang-form"


def test_full_render_parse_replace_round_trip_keeps_x_metadata():
    from estimating_tools.estimate_spec.artifact import parse_item, render_item
    spec = _spec()
    spec["items"][0]["x-work-type"] = "formliner"          # Item # 1 is a mob_item (no takeoff)
    item = find_item(spec, "Item # 1")
    reparsed = parse_item(render_item(item), item_no="Item # 1")
    assert "x-work-type" not in reparsed                    # the artifact text never carries it
    updated = replace_item(spec, "Item # 1", reparsed)
    assert updated["items"][0]["x-work-type"] == "formliner"


# ---- render_item shape tests (Phase 4) ----

from estimating_tools.estimate_spec.artifact import render_item


def _min_mob():
    """Minimal mob_item: no takeoff, empty labor, no notes, no spreads, no cost_details."""
    return {"item_no": "Item # 1", "recipe": "preamble", "sheet": "MOB",
            "description": "Mob", "qty": 1, "uom": "LS", "labor": []}


def _min_std_geometry():
    return {
        "item_no": "Item # 42", "recipe": "work_item", "sheet": "S42",
        "description": "Outfall", "qty": "={ref:takeoff.total_cy}", "uom": "CY",
        "labor": [{"slot": "AA", "description": "Fnd",
                    "crew": [{"trade": "FITTER", "count": 1, "days": 1}]}],
        "takeoff": {"kind": "geometry", "lines": [
            {"label": "Run A", "length": 4.5, "ftg_cy": 0.35, "wall_cy": 2,
             "wall_cf": 66}
        ]},
    }


def test_render_item_heading_uses_item_no():
    out = render_item(_min_mob())
    assert out.startswith("# Item # 1\n\n")


def test_render_item_always_emits_metadata_and_labor_sections():
    out = render_item(_min_mob())
    assert "\n## Metadata\n" in out
    assert "\n## Labor\n" in out
    assert "| field | value |" in out                             # metadata table shape


def test_render_item_omits_optional_sections_when_absent():
    out = render_item(_min_mob())
    assert "## Notes" not in out
    assert "## Takeoff" not in out
    assert "## Spreads" not in out
    assert "## Cost details" not in out


def test_render_item_notes_bullets_render_from_list():
    item = {**_min_mob(), "notes": ["first note", "second note"]}
    out = render_item(item)
    assert "\n## Notes\n\n- first note\n- second note" in out


def test_render_item_takeoff_geometry_heading_and_columns():
    out = render_item(_min_std_geometry())
    assert "\n## Takeoff (kind: geometry)\n\n" in out
    assert "| label | length | height | ftg_cy | ftg_cf | wall_cy | wall_cf |" in out
    # An absent column renders as -
    assert "| Run A | 4.5 | - | 0.35 | - | 2 | 66 |" in out


def test_render_item_takeoff_subcontractor_kv_bullets_and_columns():
    item = {**_min_mob(),
            "takeoff": {"kind": "subcontractor", "tax_rate": 0.0725, "freight": 1000,
                        "lines": [{"item": "Bar", "qty": 152, "uom": "FT",
                                    "unit_price": 7.3}]}}
    out = render_item(item)
    assert "\n## Takeoff (kind: subcontractor)\n\n" in out
    assert "- tax_rate: 0.0725\n" in out
    assert "- freight: 1000\n" in out
    assert "- galvanize:" not in out                              # absent key not emitted
    assert "| item | qty | uom | unit_price |" in out
    assert "| Bar | 152 | FT | 7.3 |" in out


def test_render_item_labor_slot_activities_one_liner():
    item = {**_min_mob(), "labor": [
        {"slot": "AA", "description": "Setup",
         "activities": [{"name": "Set-up yard", "factor": 1}],
         "crew": [{"trade": "FITTER", "count": 1, "days": 1}]},
    ]}
    out = render_item(item)
    assert "\n### AA: Setup\n" in out
    assert "\nActivities: Set-up yard (1)\n" in out
    assert "\nCrew:\n\n| trade | count | days |" in out


def test_render_item_labor_slot_omits_absent_kv_bullets_and_activities():
    item = {**_min_mob(), "labor": [
        {"slot": "AA", "description": "Setup",
         "crew": [{"trade": "FITTER", "count": 1, "days": 1}]},
    ]}
    out = render_item(item)
    assert "- crew_factor:" not in out
    assert "- driver:" not in out
    assert "Activities:" not in out


def test_render_item_spreads_kv_and_materials():
    item = {**_min_mob(), "spreads": {
        "ftg_qty": "={ref:takeoff.ftg_cy}", "ftg_waste": 0.15,
        "materials": [{"name": "Rebar", "qty": 4, "uom": "LS", "unit_price": 2000}],
    }}
    out = render_item(item)
    assert "\n## Spreads\n\n" in out
    assert "- ftg_qty: ={ref:takeoff.ftg_cy}\n" in out
    assert "- ftg_waste: 0.15\n" in out
    assert "- wall_qty:" not in out                               # absent key not emitted
    assert "\n### Materials\n\n| name | qty | uom | unit_price |" in out


def test_render_item_cost_details_header_price_marker_and_order():
    item = {**_min_mob(), "cost_details": [
        {"name": "VENDOR", "lines": [
            {"name": "PICKUP", "uom": "Hrs", "qty": 8, "unit_price": 10}]},
        {"name": "PARTS", "header_price": 125, "lines": []},
    ]}
    out = render_item(item)
    idx_eq = out.index("### VENDOR")
    idx_lu = out.index("### PARTS (header_price: 125)")
    assert idx_eq < idx_lu                                        # source order preserved
    assert "| name | uom | qty | unit_price |" in out


def test_render_item_escapes_pipe_in_string_cells():
    item = {**_min_mob(), "notes": ["left|right"], "description": "a|b"}
    out = render_item(item)
    assert "left\\|right" in out
    assert "a\\|b" in out


def test_render_item_alt_sample_all_items_render_without_error():
    """Every item in the alt pack's own example renders (structural / no
    assertion on content). This catches unhandled shapes across the
    item variety (geometry / subcontractor takeoff, spreads, header-price
    cost details)."""
    import yaml
    spec = yaml.safe_load(_SAMPLE_YAML.read_text())
    for it in spec["items"]:
        out = render_item(it)
        assert out.startswith(f"# {it['item_no']}\n\n")
        assert "\n## Metadata\n" in out
        assert "\n## Labor\n" in out


# ---- parse_item tests (Phase 4) ----

import yaml

from estimating_tools.estimate_spec.artifact import parse_item


_SAMPLE_YAML = ALT_DIR / "examples" / "sample.estimate.yaml"


# ---------- round-trip ----------

def test_parse_roundtrip_mob_item_minimal():
    item = _min_mob()
    assert parse_item(render_item(item), item_no=item["item_no"]) == item


def test_parse_roundtrip_standard_geometry():
    item = _min_std_geometry()
    assert parse_item(render_item(item), item_no=item["item_no"]) == item


def test_parse_roundtrip_every_pack_trade_survives_render_and_parse():
    # A rendered item carrying every trade the pack's own vocabulary allows
    # must round-trip clean — a hand-maintained copy of the trade list
    # (rather than reading it from the pack's schema) drifted once already.
    item = {**_min_std_geometry(),
            "labor": [{"slot": "AA", "description": "Fnd",
                       "crew": [{"trade": "RIGGER", "count": 1, "days": 1},
                                {"trade": "OPER", "count": 2, "days": 0.5},
                                {"trade": "HELPER", "count": 1, "days": 2}]}]}
    assert parse_item(render_item(item), item_no=item["item_no"]) == item


def test_valid_trades_is_read_from_the_schema():
    from estimating_tools.estimate_spec import artifact
    from estimating_tools.estimate_spec import format_pack as fp
    schema = fp.bundled_pack().schema
    crew = schema["$defs"]["labor_block"]["properties"]["crew"]
    assert list(artifact._valid_trades()) == crew["items"]["properties"]["trade"]["enum"]


def test_parse_roundtrip_standard_subcontractor():
    item = {
        "item_no": "Item # 41", "recipe": "work_item", "sheet": "S41",
        "description": "Trash", "qty": 3, "uom": "EA",
        "notes": ["Install Only"],
        "takeoff": {"kind": "subcontractor", "galvanize": "=810*1.75",
                    "tax_rate": 0.0725, "freight": 1000,
                    "lines": [{"item": "Bar", "qty": 152, "uom": "FT",
                                "unit_price": 7.3}]},
        "labor": [{"slot": "AA", "description": "Fab", "crew_factor": 3,
                    "driver": 761, "uom": "LBS",
                    "activities": [{"name": "Form", "factor": 0.5}],
                    "crew": [{"trade": "FITTER", "count": 1, "days": 3}]}],
        "cost_details": [{"name": "VENDOR", "lines": [
            {"name": "PICKUP", "uom": "Hrs", "qty": 8, "unit_price": 15}]}],
    }
    assert parse_item(render_item(item), item_no=item["item_no"]) == item


def test_parse_roundtrip_sample_yaml_all_items():
    """Every item in the shipped sample YAML round-trips clean."""
    spec = yaml.safe_load(_SAMPLE_YAML.read_text())
    for it in spec["items"]:
        got = parse_item(render_item(it), item_no=it["item_no"])
        assert got == it, f"round-trip mismatch on {it['item_no']!r}"


def test_parse_roundtrip_pipe_in_description():
    item = {**_min_mob(), "description": "a|b"}
    assert parse_item(render_item(item), item_no=item["item_no"]) == item


def test_parse_roundtrip_newline_in_note():
    item = {**_min_mob(), "notes": ["line1\nline2"]}
    assert parse_item(render_item(item), item_no=item["item_no"]) == item


def test_parse_roundtrip_formula_in_days_and_qty():
    item = {**_min_mob(),
            "qty": "={ref:takeoff.total_cy}",
            "labor": [{"slot": "AA", "description": "Setup",
                        "crew": [{"trade": "FITTER", "count": 1,
                                    "days": "=E{row:crew_first}"}]}]}
    assert parse_item(render_item(item), item_no=item["item_no"]) == item


# ---------- user edits ----------

def test_parse_after_qty_toggle_number_to_formula():
    item = _min_mob()
    text = render_item(item)
    edited = text.replace("| qty | 1 |", "| qty | ={ref:takeoff.total_cy} |")
    parsed = parse_item(edited, item_no=item["item_no"])
    assert parsed["qty"] == "={ref:takeoff.total_cy}"


def test_parse_after_add_note_bullet_to_item_without_notes():
    """Adding a Notes section adds the key to the parsed dict."""
    item = _min_mob()
    text = render_item(item)
    edited = text + "\n\n## Notes\n\n- freshly added note\n"
    parsed = parse_item(edited, item_no=item["item_no"])
    assert parsed["notes"] == ["freshly added note"]


def test_parse_after_add_labor_slot():
    item = {**_min_mob(), "labor": [
        {"slot": "AA", "description": "Setup",
         "crew": [{"trade": "FITTER", "count": 1, "days": 1}]},
    ]}
    text = render_item(item)
    new_slot = (
        "\n\n### BB: Cleanup\n\nCrew:\n\n"
        "| trade | count | days |\n"
        "| --- | --- | --- |\n"
        "| HELPER | 1 | 2 |"
    )
    edited = text + new_slot
    parsed = parse_item(edited, item_no=item["item_no"])
    assert [s["slot"] for s in parsed["labor"]] == ["AA", "BB"]
    assert parsed["labor"][1]["crew"][0]["trade"] == "HELPER"


def test_parse_item_no_meta_overrides_heading():
    """Caller's item_no wins even if the # heading in text says otherwise."""
    item = _min_mob()
    text = render_item(item).replace("# Item # 1", "# XYZ")
    parsed = parse_item(text, item_no="Item # 1")
    assert parsed["item_no"] == "Item # 1"


def test_parse_after_toggle_takeoff_kind():
    item = _min_std_geometry()
    text = render_item(item)
    # Replace geometry section with a subcontractor section that has valid content
    new_takeoff = (
        "## Takeoff (kind: subcontractor)\n\n"
        "| item | qty | uom | unit_price |\n"
        "| --- | --- | --- | --- |\n"
        "| Bar | 10 | FT | 5 |"
    )
    idx = text.index("## Takeoff (kind: geometry)")
    end = text.index("## Labor")
    edited = text[:idx] + new_takeoff + "\n\n" + text[end:]
    parsed = parse_item(edited, item_no=item["item_no"])
    assert parsed["takeoff"]["kind"] == "subcontractor"
    assert parsed["takeoff"]["lines"][0]["item"] == "Bar"


# ---------- malformed ----------

def test_parse_raises_on_unknown_top_section():
    item = _min_mob()
    text = render_item(item) + "\n\n## Bogus\n\n(nothing)"
    with pytest.raises(ValueError, match="unknown heading"):
        parse_item(text, item_no=item["item_no"])


def test_parse_raises_on_takeoff_missing_kind_marker():
    text = ("# Item # 1\n\n"
            "## Metadata\n\n| field | value |\n| --- | --- |\n"
            "| description | Mob |\n| recipe | preamble |\n| sheet | MOB |\n"
            "| qty | 1 |\n| uom | LS |\n\n"
            "## Takeoff\n\n(no marker)\n\n"
            "## Labor\n")
    with pytest.raises(ValueError, match=r"kind"):
        parse_item(text, item_no="Item # 1")


def test_parse_raises_on_wrong_column_count():
    item = _min_std_geometry()
    text = render_item(item)
    # Break the geometry table by adding a bogus column
    edited = text.replace("| Run A | 4.5 | - | 0.35 | - | 2 | 66 |",
                          "| Run A | 4.5 | - | 0.35 | - | 2 | 66 | extra |")
    with pytest.raises(ValueError, match="expected 7 columns"):
        parse_item(edited, item_no=item["item_no"])


def test_parse_raises_on_unrecognized_recipe():
    item = _min_mob()
    text = render_item(item).replace("| recipe | preamble |", "| recipe | WEIRD |")
    with pytest.raises(ValueError, match="unrecognized recipe"):
        parse_item(text, item_no=item["item_no"])


def test_parse_raises_on_unrecognized_trade():
    item = {**_min_mob(), "labor": [
        {"slot": "AA", "description": "Setup",
         "crew": [{"trade": "FITTER", "count": 1, "days": 1}]},
    ]}
    text = render_item(item).replace("| FITTER |", "| IRONWORKER |")
    with pytest.raises(ValueError, match="unrecognized trade"):
        parse_item(text, item_no=item["item_no"])


def test_parse_raises_on_blank_required_component_cell():
    item = _min_std_geometry()
    text = render_item(item).replace("| Run A | 4.5 |", "| - | 4.5 |")
    with pytest.raises(ValueError, match=r"'label' is required"):
        parse_item(text, item_no=item["item_no"])


def test_parse_raises_on_non_numeric_where_num_or_formula_required():
    item = _min_mob()
    text = render_item(item).replace("| qty | 1 |", "| qty | TBD |")
    with pytest.raises(ValueError, match=r"'qty' expected a number or formula"):
        parse_item(text, item_no=item["item_no"])


def test_parse_raises_on_duplicate_labor_slot_letter():
    item = {**_min_mob(), "labor": [
        {"slot": "AA", "description": "one",
         "crew": [{"trade": "FITTER", "count": 1, "days": 1}]},
        {"slot": "AA", "description": "two",
         "crew": [{"trade": "FITTER", "count": 1, "days": 1}]},
    ]}
    text = render_item(item)
    with pytest.raises(ValueError, match="duplicate labor slot 'AA'"):
        parse_item(text, item_no=item["item_no"])


def test_parse_raises_on_duplicate_cost_detail_name():
    item = {**_min_mob(), "cost_details": [
        {"name": "VENDOR", "lines": []},
        {"name": "VENDOR", "lines": []},
    ]}
    text = render_item(item)
    with pytest.raises(ValueError, match="duplicate cost-detail section 'VENDOR'"):
        parse_item(text, item_no=item["item_no"])


def test_parse_schema_violation_surfaces_as_valueerror():
    """Delete a required field via editing; parse must surface the schema violation."""
    item = _min_mob()
    text = render_item(item).replace("| description | Mob |", "")
    with pytest.raises(ValueError, match="schema violation"):
        parse_item(text, item_no=item["item_no"])


# ---- Copilot-review fixes (Phase 4) ----


def test_parse_labor_slot_empty_string_uom_round_trips():
    """Fix A: an explicit empty string on a labor slot's optional string field
    (uom / note) round-trips as empty string, not as an absent key."""
    item = {**_min_mob(), "labor": [
        {"slot": "AA", "description": "Setup", "uom": "",
         "crew": [{"trade": "FITTER", "count": 1, "days": 1}]},
    ]}
    got = parse_item(render_item(item), item_no=item["item_no"])
    assert got == item                                            # uom: "" preserved


def test_parse_subcontractor_uom_dash_raises():
    """Fix B: subcontractor takeoff line 'uom' is schema-required; '-' must raise."""
    item = {**_min_mob(),
            "takeoff": {"kind": "subcontractor",
                        "lines": [{"item": "Bar", "qty": 152, "uom": "FT",
                                    "unit_price": 7.3}]}}
    text = render_item(item)
    edited = text.replace("| Bar | 152 | FT | 7.3 |",
                          "| Bar | 152 | - | 7.3 |")
    with pytest.raises(ValueError, match=r"'uom' is required"):
        parse_item(edited, item_no=item["item_no"])


def test_parse_materials_uom_dash_raises():
    """Fix C: spreads/materials line 'uom' is schema-required; '-' must raise."""
    item = {**_min_mob(), "spreads": {
        "materials": [{"name": "Rebar", "qty": 4, "uom": "LS",
                       "unit_price": 2000}],
    }}
    text = render_item(item)
    edited = text.replace("| Rebar | 4 | LS | 2000 |",
                          "| Rebar | 4 | - | 2000 |")
    with pytest.raises(ValueError, match=r"'uom' is required"):
        parse_item(edited, item_no=item["item_no"])


# ---- Phase 4.5: optional metadata fields (wbs, cost_code, crew_id) ----------

def test_render_metadata_omits_optional_fields_when_absent():
    """Existing items without wbs/cost_code/crew_id must render exactly as before."""
    item = _min_mob()
    out = render_item(item)
    assert "wbs" not in out
    assert "cost_code" not in out
    assert "crew_id" not in out


def test_render_metadata_includes_wbs_row_when_set():
    item = _min_mob() | {"wbs": "1.2.3"}
    out = render_item(item)
    assert "| wbs | 1.2.3 |" in out


def test_render_metadata_includes_cost_code_row_when_set():
    item = _min_mob() | {"cost_code": "02-110"}
    out = render_item(item)
    assert "| cost_code | 02-110 |" in out


def test_render_metadata_includes_crew_id_row_when_set():
    item = _min_mob() | {"crew_id": "crew_lab_2"}
    out = render_item(item)
    assert "| crew_id | crew_lab_2 |" in out


def test_render_metadata_optional_rows_appear_after_required_rows():
    """Optional rows follow the required rows so the Metadata table stays stable."""
    item = _min_mob() | {"wbs": "1.2", "cost_code": "02-110", "crew_id": "crew_lab_2"}
    out = render_item(item)
    lines = out.splitlines()
    # find_index helper: locate a table row by its field name column
    def row_index(field: str) -> int:
        for i, line in enumerate(lines):
            if line.startswith(f"| {field} |"):
                return i
        raise AssertionError(f"row for field {field!r} not found in output")
    assert row_index("uom") < row_index("wbs")
    assert row_index("uom") < row_index("cost_code")
    assert row_index("uom") < row_index("crew_id")


def test_render_metadata_omits_optional_field_when_value_is_none():
    item = _min_mob() | {"wbs": None}
    out = render_item(item)
    assert "wbs" not in out


def test_render_metadata_omits_optional_field_when_value_is_empty_string():
    item = _min_mob() | {"wbs": ""}
    out = render_item(item)
    assert "wbs" not in out


# ---- Phase 4.5: parse_item round-trip for optional metadata fields ----------


def test_parse_item_round_trip_with_wbs():
    item = _min_mob() | {"wbs": "1.2.3"}
    text = render_item(item)
    parsed = parse_item(text, item_no=item["item_no"])
    assert parsed == item


def test_parse_item_round_trip_with_cost_code():
    item = _min_mob() | {"cost_code": "02-110"}
    text = render_item(item)
    parsed = parse_item(text, item_no=item["item_no"])
    assert parsed == item


def test_parse_item_round_trip_with_crew_id():
    item = _min_mob() | {"crew_id": "crew_lab_2"}
    text = render_item(item)
    parsed = parse_item(text, item_no=item["item_no"])
    assert parsed == item


def test_parse_item_round_trip_with_all_three_optional_fields():
    item = _min_mob() | {"wbs": "1.2", "cost_code": "02-110", "crew_id": "crew_lab_2"}
    text = render_item(item)
    parsed = parse_item(text, item_no=item["item_no"])
    assert parsed == item


def test_parse_item_omits_absent_optional_fields():
    """Round-trip an item without any of the three optional fields → keys stay absent."""
    item = _min_mob()
    text = render_item(item)
    parsed = parse_item(text, item_no=item["item_no"])
    assert "wbs" not in parsed
    assert "cost_code" not in parsed
    assert "crew_id" not in parsed


# ---- Phase 4 follow-up: estimate_item_id in metadata round-trip -----------


def test_render_item_includes_estimate_item_id_row_when_set():
    """A synced item with estimate_item_id renders it as a metadata row."""
    item = _min_mob() | {"estimate_item_id": 100}
    out = render_item(item)
    assert "| estimate_item_id | 100 |" in out


def test_render_item_omits_estimate_item_id_row_when_absent():
    """An item without estimate_item_id must NOT produce a metadata row for it
    (regression guard against accidentally emitting `-`)."""
    item = _min_mob()
    out = render_item(item)
    assert "estimate_item_id" not in out


def test_parse_item_round_trip_with_estimate_item_id():
    """Full round-trip on an item carrying estimate_item_id plus other
    Phase 4.5 fields. This is the primary contract this follow-up closes."""
    item = _min_mob() | {
        "estimate_item_id": 100,
        "wbs": "1.2.3",
        "cost_code": "02-110",
        "crew_id": "crew_lab_2",
    }
    text = render_item(item)
    parsed = parse_item(text, item_no=item["item_no"])
    assert parsed == item


def test_parse_item_round_trip_without_estimate_item_id():
    """An item without estimate_item_id must round-trip with the key still
    absent — regression guard for the 'silent-strip' bug this follow-up
    closes. If render or parse ever accidentally inserts a `None` or `0`
    default, this test catches it."""
    item = _min_mob()
    text = render_item(item)
    parsed = parse_item(text, item_no=item["item_no"])
    assert "estimate_item_id" not in parsed
    assert parsed == item


def test_parse_item_malformed_estimate_item_id_raises_locator_error():
    """A manually-corrupted artifact with a non-integer estimate_item_id
    value raises ValueError naming the section, row, and value."""
    item = _min_mob() | {"estimate_item_id": 100}
    text = render_item(item)
    # Corrupt the id cell (100 → abc):
    corrupted = text.replace("| estimate_item_id | 100 |",
                             "| estimate_item_id | abc |")
    with pytest.raises(ValueError,
                       match=r"Metadata.*estimate_item_id.*'abc'"):
        parse_item(corrupted, item_no=item["item_no"])


# ---- artifact support gate ----

def test_render_item_refuses_unsupported_pack(demo_pack):
    """render_item must refuse a pack that does not declare artifact support,
    preventing silent-wrong output. This matches the parse_item gate."""
    item = {"item_no": "1", "description": "x", "recipe": "line_item"}
    with pytest.raises(fp.FormatPackError, match="does not support"):
        render_item(item, pack=demo_pack)
