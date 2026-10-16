"""Task 7b: the skeleton's composed schema is narrower than real specs need
it to be, on field classes no format pack can reach. These six relaxations
widen the skeleton so that generic shapes (cost coding on a labor/cost-detail
block, fractional crew counts, days-optional crews, optional bid items, and
labor-optional items with root-level cost_code_system/schedule) validate
everywhere, without narrowing anything for any pack.

Fragments here are synthetic, derived from the schema itself -- never from
any real spec.
"""
from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest

from estimating_tools.estimate_spec import format_pack as fp

ES = Path(fp.__file__).resolve().parent
DEMO_DIR = ES / "packs" / "demo"
ALT_DIR = Path(__file__).resolve().parent / "fixtures" / "packs" / "alt"


def _item_schema(pack):
    schema = pack.schema
    return {"$defs": schema["$defs"], **schema["$defs"]["item"]}


def _base_item(**extra):
    item = {"recipe": "setup", "sheet": "S1", "item_no": "1",
            "description": "d", "uom": "LS"}
    item.update(extra)
    return item


def _base_doc(pack, **extra):
    doc = {
        "project": "P", "markup": 0,
        "rate_table": [{"trade": "SUPR", "rate": 95}],
        "items": [_base_item()],
    }
    doc.update(extra)
    return doc


# --------------------------------------------------------------------------
# 1. cost_code (string) permitted on a labor block
# --------------------------------------------------------------------------

def test_relaxation_1_labor_block_cost_code():
    pack = fp.load_pack(DEMO_DIR)
    item = _base_item(labor=[{
        "slot": "01", "description": "d", "cost_code": "02-110",
        "crew": [{"trade": "SUPR", "days": 1}],
    }])
    jsonschema.validate(item, _item_schema(pack))


# --------------------------------------------------------------------------
# 2. cost_code (string) permitted on a cost-detail block
# --------------------------------------------------------------------------

def test_relaxation_2_cost_detail_cost_code():
    pack = fp.load_pack(DEMO_DIR)
    item = _base_item(cost_details=[{
        "name": "MATL", "cost_code": "02-110",
        "lines": [{"name": "x", "qty": 1, "unit_price": 1}],
    }])
    jsonschema.validate(item, _item_schema(pack))


# --------------------------------------------------------------------------
# 3. crew[].count accepts a number, not only an integer
# --------------------------------------------------------------------------

def test_relaxation_3_half_crew_count():
    pack = fp.load_pack(DEMO_DIR)
    item = _base_item(labor=[{
        "slot": "01", "description": "d",
        "crew": [{"trade": "SUPR", "count": 0.5, "days": 1}],
    }])
    jsonschema.validate(item, _item_schema(pack))


# --------------------------------------------------------------------------
# 4. crew[].days is optional, not required
# --------------------------------------------------------------------------

def test_relaxation_4_crew_days_optional():
    pack = fp.load_pack(DEMO_DIR)
    item = _base_item(labor=[{
        "slot": "01", "description": "d",
        "crew": [{"trade": "SUPR"}],
    }])
    jsonschema.validate(item, _item_schema(pack))


# --------------------------------------------------------------------------
# 5. item.optional (boolean) permitted
# --------------------------------------------------------------------------

def test_relaxation_5_item_optional_flag():
    pack = fp.load_pack(DEMO_DIR)
    item = _base_item(optional=True)
    jsonschema.validate(item, _item_schema(pack))


# --------------------------------------------------------------------------
# 6. labor is optional on an item; root cost_code_system / schedule permitted
# --------------------------------------------------------------------------

def test_relaxation_6_item_with_no_labor_block():
    pack = fp.load_pack(DEMO_DIR)
    item = _base_item()  # no "labor" key at all
    assert "labor" not in item
    jsonschema.validate(item, _item_schema(pack))


def test_relaxation_6_root_cost_code_system_and_schedule():
    # Fix round 1: cost_code_system is a generic object (name required,
    # edition/source optional); schedule is object-shaped too, but a pack
    # that supplies no defs.schedule only guarantees a plain object -- see
    # the dedicated schedule tests below for the two halves of that split.
    pack = fp.load_pack(DEMO_DIR)
    doc = _base_doc(pack, cost_code_system={"name": "AIA-16", "edition": "2018"},
                     schedule={"note": "generic, no pack-supplied shape here"})
    jsonschema.validate(doc, pack.schema)


def test_cost_code_system_is_still_type_checked():
    pack = fp.load_pack(DEMO_DIR)
    # additionalProperties false and name required -- a typo/omission still fails.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_base_doc(pack, cost_code_system={"nam": "typo"}), pack.schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_base_doc(pack, cost_code_system="AIA-16"), pack.schema)


# --------------------------------------------------------------------------
# schedule: fix round 1. Documentation-only, so a pack that supplies no
# defs.schedule still accepts a plain object (the field cannot affect a
# render); a pack that DOES supply a strict def has it genuinely enforced,
# not silently ignored.
# --------------------------------------------------------------------------

def test_schedule_with_no_pack_def_accepts_a_plain_object():
    pack = fp.load_pack(DEMO_DIR)
    assert "schedule" not in (pack.vocabulary.get("defs") or {})
    doc = _base_doc(pack, schedule={"anything": "goes", "here": 1})
    jsonschema.validate(doc, pack.schema)


def test_schedule_with_no_pack_def_still_requires_an_object():
    pack = fp.load_pack(DEMO_DIR)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_base_doc(pack, schedule="not an object"), pack.schema)


def test_a_pack_supplied_schedule_def_is_genuinely_enforced():
    """Proves the {"$vocab": "schedule"} marker really wires a pack's def in
    -- not silently ignored -- by composing with a synthetic vocabulary that
    defines a strict defs.schedule (mirroring how a real org's pack would)."""
    demo_vocab = fp.load_pack(DEMO_DIR).vocabulary
    strict_vocab = {**demo_vocab, "defs": {
        **demo_vocab["defs"],
        "schedule": {
            "type": "object", "additionalProperties": False,
            "required": ["activities"],
            "properties": {"activities": {"type": "array", "minItems": 1}},
        },
    }}
    schema = fp.compose_schema(fp._skeleton(), strict_vocab, ["setup"])
    doc = {"project": "P", "markup": 0, "rate_table": [{"trade": "SUPR", "rate": 95}],
           "items": [_base_item()], "schedule": {"activities": [{"id": "a1"}]}}
    jsonschema.validate(doc, schema)  # well-formed: passes

    # Malformed against the PACK's own def (missing required "activities")
    # must still fail -- proving the def is actually in force.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**doc, "schedule": {"not_activities": []}}, schema)


# --------------------------------------------------------------------------
# Malformed shapes are still rejected: validation is still on.
# --------------------------------------------------------------------------

def test_still_rejects_malformed_shapes():
    pack = fp.load_pack(DEMO_DIR)
    item_schema = _item_schema(pack)

    # optional is type-checked, not merely present -- a string is not a bool.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_base_item(optional="yes"), item_schema)

    # additionalProperties is still false: an unknown key still fails.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_base_item(bogus_field=1), item_schema)

    # crew[].trade is still required -- only "days" was relaxed.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_base_item(labor=[{
            "slot": "01", "description": "d",
            "crew": [{"days": 1}],
        }]), item_schema)

    # crew[].count is still type-checked -- a string is not a number.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_base_item(labor=[{
            "slot": "01", "description": "d",
            "crew": [{"trade": "SUPR", "count": "half", "days": 1}],
        }]), item_schema)


# --------------------------------------------------------------------------
# rebar_spread: the one pack-side move. The skeleton grows a marker for it,
# but no pack shipped in this repo defines defs.rebar_spread, so the field
# stays rejected everywhere here -- it is permitted only by the consuming
# org's own pack (Work repo), never by the demo pack, the alt pack, or the
# skeleton itself.
# --------------------------------------------------------------------------

def test_the_skeleton_names_no_org_vocabulary():
    text = (ES / "schema" / "skeleton.schema.json").read_text()
    for word in ("FORE", "LUMBER", "EQUIPMENT", "ftg_cy", "wall_cf",
                 "mob_item", "standard_item", "selected", "carry"):
        assert word not in text, word


# Each shipped pack's own first-item recipe, one that item_rules does not
# require a takeoff for -- keeps the fragment isolated to rebar_spread alone.
_NO_TAKEOFF_RECIPE = {DEMO_DIR: "setup", ALT_DIR: "preamble"}


@pytest.mark.parametrize("pack_dir", [DEMO_DIR, ALT_DIR])
def test_rebar_spread_not_permitted_by_any_shipped_pack(pack_dir):
    pack = fp.load_pack(pack_dir)
    assert "rebar_spread" not in (pack.vocabulary.get("defs") or {})
    item_schema = _item_schema(pack)
    item = _base_item(recipe=_NO_TAKEOFF_RECIPE[pack_dir],
                       rebar_spread={"lines": []})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(item, item_schema)
