"""The plugin skeleton + the pack vocabulary compose to a pack's schema."""
from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest

from estimating_tools.estimate_spec import format_pack as fp

ES = Path(fp.__file__).resolve().parent
LEGACY_DIR = ES / "tests" / "fixtures" / "packs" / "legacy_demo"
ALT_DIR = Path(__file__).resolve().parent / "fixtures" / "packs" / "alt"

# NOTE: this file used to also pin the composed schema against a frozen
# pre-split snapshot of the reference pack's own schema
# (tests/fixtures/estimate.schema.pre-split.json) as a migration-invariant
# regression check. That check's premise — "today's bundled pack (the
# reference pack) composes to exactly this frozen schema" — cannot survive
# the reference pack's departure (Plan C Task 7/8): there is no equivalent
# snapshot for a generic pack, and inventing one wouldn't verify anything
# historically meaningful. Retired here rather than genericized.


def _crew_member_trade(schema):
    return schema["properties"]["crews"]["items"]["properties"]["members"]["items"]["properties"]["trade"]


def test_the_skeleton_names_no_vocabulary():
    text = (ES / "schema" / "skeleton.schema.json").read_text()
    for word in ("FORE", "LUMBER", "EQUIPMENT", "ftg_cy", "wall_cf", "mob_item", "standard_item"):
        assert word not in text, word


def test_one_trade_list():
    pack = fp.load_pack(LEGACY_DIR)
    labor = pack.schema["$defs"]["labor_block"]["properties"]["crew"]["items"]["properties"]["trade"]["enum"]
    assert labor == _crew_member_trade(pack.schema)["enum"] == pack.vocabulary["trades"]
    assert set(pack.seed["rate_table_trades"]) <= set(pack.vocabulary["trades"])


def test_x_properties_pass_and_typos_still_fail():
    schema = fp.load_pack(ALT_DIR).schema
    item_schema = {"$defs": schema["$defs"], **schema["$defs"]["item"]}
    good = {"recipe": "preamble", "sheet": "PRE", "item_no": "1", "description": "d",
            "uom": "LS", "labor": [{"slot": "AA", "description": "d",
                                     "crew": [{"trade": "FITTER", "days": 0}]}],
            "x-work-type-profile": "cip_structure"}
    jsonschema.validate(good, item_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**good, "desciption": "typo"}, item_schema)


def test_the_recipe_enum_is_derived_from_recipes():
    pack = fp.load_pack(LEGACY_DIR)
    names = sorted(k for k in pack.recipes["recipes"] if k != "cover")
    assert sorted(pack.schema["$defs"]["item"]["properties"]["recipe"]["enum"]) == names


def test_a_pack_naming_a_schema_file_is_refused(tmp_path):
    import shutil
    root = tmp_path / "p"
    shutil.copytree(LEGACY_DIR, root, ignore=shutil.ignore_patterns("*.py", "__pycache__", "tests", "examples", "packs"))
    manifest = root / "format.yaml"
    # Insert inside the `files:` block itself — appending at end-of-file would
    # instead land inside whatever mapping happens to be last (e.g. `labor:`),
    # which is not what this test means to exercise.
    text = manifest.read_text().replace(
        "  seed: seed.yaml\n", "  seed: seed.yaml\n  schema: schema/skeleton.schema.json\n")
    assert "schema: schema/skeleton.schema.json" in text
    manifest.write_text(text)
    with pytest.raises(fp.FormatPackError, match="schema"):
        fp.load_pack(root)
