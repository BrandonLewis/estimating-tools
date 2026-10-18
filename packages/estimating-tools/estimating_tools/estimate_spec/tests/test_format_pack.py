"""FormatPack loading and resolution."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from estimating_tools.estimate_spec import format_pack as fp
from estimating_tools.profiles.model import Profile

ES = Path(fp.__file__).resolve().parent
LEGACY_DIR = ES / "tests" / "fixtures" / "packs" / "legacy_demo"
ALT_DIR = Path(__file__).resolve().parent / "fixtures" / "packs" / "alt"
MANIFEST = """\
name: {name}
version: 1
files:
  units: units.yaml
  tokens: tokens.yaml
  recipes: recipes.yaml
  vocabulary: vocabulary.yaml
  seed: seed.yaml
"""


def _make_pack(tmp_path: Path, name: str = "copy") -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    for f in ("units.yaml", "tokens.yaml", "recipes.yaml", "vocabulary.yaml", "seed.yaml"):
        shutil.copy(LEGACY_DIR / f, root / f)
    (root / "format.yaml").write_text(MANIFEST.format(name=name), encoding="utf-8")
    return root


def _write_min_pack(tmp_path: Path, name: str = "copy", *, supports=None, labor=None) -> Path:
    """`_make_pack`, plus optional `supports:`/`labor:` appended to the manifest."""
    root = _make_pack(tmp_path, name)
    manifest = root / "format.yaml"
    text = manifest.read_text(encoding="utf-8")
    if supports is not None:
        text += f"supports: [{', '.join(supports)}]\n"
    if labor is not None:
        text += "labor:\n" + "".join(f"  {k}: {v}\n" for k, v in labor.items())
    manifest.write_text(text, encoding="utf-8")
    return root


def test_bundled_pack_loads_whatever_bundled_names_and_caches_it(monkeypatch):
    """bundled_pack() loads whatever BUNDLED names and caches the result —
    proven generically by redirecting it to the demo pack rather than
    asserting facts about whichever pack the plugin bundles today (no test
    may depend on which pack is bundled)."""
    demo = fp.load_pack(LEGACY_DIR)
    monkeypatch.setattr(fp, "bundled_pack", lambda: demo)
    pack = fp.bundled_pack()
    assert pack.name == "legacy_demo"
    assert "job_header" in pack.units             # the units MAP, not the document
    assert "$defs" in pack.schema
    assert "styles" in pack.tokens
    assert fp.bundled_pack() is pack              # cached (the lambda is stable per call)


def test_a_copied_pack_loads_with_its_own_identity(tmp_path):
    pack = fp.load_pack(_make_pack(tmp_path, "mine"))
    assert (pack.name, pack.version) == ("mine", "1")
    assert pack.key != fp.bundled_pack().key


def test_a_directory_without_a_manifest_is_refused(tmp_path):
    with pytest.raises(fp.FormatPackError, match="not a format pack"):
        fp.load_pack(tmp_path)


def test_a_missing_required_file_is_named(tmp_path):
    root = _make_pack(tmp_path)
    (root / "tokens.yaml").unlink()
    with pytest.raises(fp.FormatPackError, match="files.tokens"):
        fp.load_pack(root)


def test_a_file_outside_the_pack_is_refused(tmp_path):
    root = _make_pack(tmp_path)
    shutil.copy(root / "units.yaml", tmp_path / "outside.yaml")
    text = (root / "format.yaml").read_text().replace("units: units.yaml",
                                                     "units: ../outside.yaml")
    (root / "format.yaml").write_text(text)
    with pytest.raises(fp.FormatPackError, match="escapes the pack"):
        fp.load_pack(root)


def test_an_unknown_files_key_is_refused(tmp_path):
    root = _make_pack(tmp_path)
    with (root / "format.yaml").open("a") as f:
        f.write("  plugin: hooks.py\n")
    with pytest.raises(fp.FormatPackError, match="plugin"):
        fp.load_pack(root)


def test_malformed_yaml_is_a_pack_error(tmp_path):
    root = _make_pack(tmp_path)
    (root / "units.yaml").write_text("units: [unclosed\n")
    with pytest.raises(fp.FormatPackError, match="units.yaml"):
        fp.load_pack(root)


def test_a_pack_cannot_construct_python_objects(tmp_path):
    """Decision 2: packs are data, never code."""
    root = _make_pack(tmp_path)
    (root / "units.yaml").write_text("units: !!python/object/apply:os.getcwd []\n")
    with pytest.raises(fp.FormatPackError):
        fp.load_pack(root)


def test_resolution_cli_beats_profile_beats_bundled(tmp_path, monkeypatch):
    cli = _make_pack(tmp_path, "cli")
    prof = _make_pack(tmp_path, "prof")
    profile = Profile(data={"estimating": {"format": str(prof)}})
    assert fp.resolve_pack(cli, profile).name == "cli"
    assert fp.resolve_pack(None, profile).name == "prof"
    # "beats bundled": redirect the bundled pack to the demo pack rather
    # than asserting today's specific bundled name.
    demo = fp.load_pack(LEGACY_DIR)
    monkeypatch.setattr(fp, "bundled_pack", lambda: demo)
    assert fp.resolve_pack(None, Profile(data={})).name == "legacy_demo"
    assert fp.resolve_pack().name == "legacy_demo"


def test_a_named_pack_that_is_missing_never_falls_back(tmp_path):
    """Decision 5."""
    with pytest.raises(fp.FormatPackError):
        fp.resolve_pack(tmp_path / "nope")
    profile = Profile(data={"estimating": {"format": str(tmp_path / "nope")}})
    with pytest.raises(fp.FormatPackError):
        fp.resolve_pack(None, profile)


def test_a_profile_format_path_resolves_against_the_profile_dir(tmp_path):
    from estimating_tools.profiles.loader import load_one

    prof_dir = tmp_path / "org"
    prof_dir.mkdir()
    (prof_dir / "profile.yaml").write_text("estimating:\n  format: packs/mine\n")
    sections = load_one(prof_dir)
    assert sections["estimating"]["format"] == str((prof_dir / "packs" / "mine").resolve())


def test_supports_defaults_to_nothing_and_rejects_unknown_tools(tmp_path):
    root = _make_pack(tmp_path)
    assert fp.load_pack(root).supports == frozenset()
    manifest = root / "format.yaml"
    manifest.write_text(manifest.read_text() +
                         "supports: [summarize, artifact]\n"
                         "labor:\n  crew_factor_default: 1\n")
    assert fp.load_pack(root).supports == frozenset({"summarize", "artifact"})
    manifest.write_text(MANIFEST.format(name="copy") + "supports: [summarize, teleport]\n")
    with pytest.raises(fp.FormatPackError, match="teleport"):
        fp.load_pack(root)
    manifest.write_text(MANIFEST.format(name="copy") + "supports: summarize\n")
    with pytest.raises(fp.FormatPackError, match="supports"):
        fp.load_pack(root)


def test_a_broken_recipes_document_fails_at_load(tmp_path):
    root = _make_pack(tmp_path)
    recipes = root / "recipes.yaml"
    recipes.write_text(recipes.read_text().replace("unit: job_header", "unit: no_such_unit", 1))
    with pytest.raises(fp.FormatPackError, match="no_such_unit"):
        fp.load_pack(root)


def test_a_recipe_position_key_fails_at_load(tmp_path):
    """`position:` on a recipe is parsed by the YAML loader but never acted
    on -- sheet order comes from the estimate config's item order (plus the
    cover, always first) -- so a pack author setting it gets an error, not
    silence."""
    root = _make_pack(tmp_path)
    recipes = root / "recipes.yaml"
    recipes.write_text(recipes.read_text().replace(
        "sheet_name: Bid Summary", "sheet_name: Bid Summary\n    position: 0", 1))
    with pytest.raises(fp.FormatPackError, match="position"):
        fp.load_pack(root)


def test_the_cli_reports_a_broken_recipes_document(tmp_path, capsys):
    from estimating_tools.estimate_spec.cli import main
    root = _make_pack(tmp_path)
    recipes = root / "recipes.yaml"
    recipes.write_text(recipes.read_text().replace("unit: job_header", "unit: no_such_unit", 1))
    sample = LEGACY_DIR / "examples" / "demo-pipeline.estimate.yaml"
    assert main(["build", str(sample), "-o", str(tmp_path / "o.xlsx"), "--format", str(root)]) == 2
    assert "format pack error" in capsys.readouterr().err


def test_pack_defs_may_not_name_a_remote_ref():
    vocab = {"trades": ["X"], "cost_blocks": ["Y"], "slot_pattern": "^[A-Z]$",
             "defs": {"takeoff": {"type": "object"},
                      "spreads": {"type": "array",
                                  "items": {"$ref": "https://example.invalid/evil.json"}}}}
    with pytest.raises(fp.FormatPackError, match=r"\$ref"):
        fp.compose_schema({"a": {"$vocab": "spreads"}}, vocab, [])
    vocab["defs"]["spreads"]["items"]["$ref"] = "#/$defs/takeoff"
    assert fp.compose_schema({"a": {"$vocab": "spreads"}}, vocab, [])["a"]["items"]["$ref"] == "#/$defs/takeoff"


# =============================================================================
# labor: policy data, required of any pack that declares supports: summarize
# =============================================================================

def test_labor_defaults_to_empty(tmp_path):
    root = _write_min_pack(tmp_path)
    assert fp.load_pack(root).labor == {}


def test_pack_declaring_summarize_must_state_crew_factor(tmp_path):
    pack_dir = _write_min_pack(tmp_path, supports=["summarize"], labor=None)
    with pytest.raises(fp.FormatPackError, match="labor.crew_factor_default"):
        fp.load_pack(pack_dir)


def test_crew_factor_default_comes_from_pack(tmp_path):
    pack_dir = _write_min_pack(tmp_path, supports=["summarize"],
                                labor={"crew_factor_default": 1})
    assert fp.load_pack(pack_dir).labor["crew_factor_default"] == 1


def test_a_pack_without_summarize_support_needs_no_labor(tmp_path):
    """A pack that never declares supports: summarize owes no labor policy —
    the demo pack's situation."""
    root = _write_min_pack(tmp_path, supports=["artifact"], labor=None)
    assert fp.load_pack(root).labor == {}


def test_a_pack_declaring_summarize_states_its_own_crew_factor(monkeypatch):
    """Decision 5: the engine's old hardcoded default was 5 — a pack states
    its own policy instead (the alt pack's is 2; the reference pack's was
    1). Proven generically by redirecting the bundled pack to the alt pack
    rather than asserting today's specific bundled pack's value."""
    alt = fp.load_pack(ALT_DIR)
    monkeypatch.setattr(fp, "bundled_pack", lambda: alt)
    assert fp.bundled_pack().labor["crew_factor_default"] == 2


def test_bundled_pack_is_the_fieldbook_pack():
    """The one deliberate exception to 'no test may depend on which pack is
    bundled': this test IS the assertion that the plugin's shipped default
    is the generic fieldbook pack, authored from scratch -- not any org's
    reference pack, and not the retired demo pack, which survives only as the
    frozen legacy_demo test fixture."""
    pack = fp.bundled_pack()
    assert pack.name == "fieldbook"
    assert fp.BUNDLED == fp.ENGINE_DIR / "packs" / "fieldbook"
    assert not (fp.ENGINE_DIR / "packs" / "demo").exists()
    assert "mob_item" not in (pack.recipes or {}).get("recipes", {})


# ---------------------------------------------------------------------------
# the seed blocks every consumer subscripts bare
# ---------------------------------------------------------------------------

def _edit_seed(root: Path, fn) -> Path:
    import yaml

    path = root / "seed.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return root


def test_a_pack_without_seed_scaffold_is_refused_by_name(tmp_path):
    """scaffold.py, compact.py, apply.py and scaffold_save.py all subscript
    `pack.seed["scaffold"]` bare. A pack that loaded without it died later
    with an unnamed KeyError, mid-scaffold, in someone else's code."""
    root = _edit_seed(_make_pack(tmp_path), lambda d: d.pop("scaffold"))
    with pytest.raises(fp.FormatPackError, match=r"copy.*seed\.scaffold is required"):
        fp.load_pack(root)


def test_a_pack_without_seed_takeoff_mapping_is_refused_by_name(tmp_path):
    root = _edit_seed(_make_pack(tmp_path), lambda d: d.pop("takeoff_mapping"))
    with pytest.raises(fp.FormatPackError,
                       match=r"copy.*seed\.takeoff_mapping is required"):
        fp.load_pack(root)


def test_a_pack_with_no_seed_file_at_all_is_refused(tmp_path):
    root = _make_pack(tmp_path)
    (root / "format.yaml").write_text(
        MANIFEST.format(name="copy").replace("  seed: seed.yaml\n", ""),
        encoding="utf-8")
    with pytest.raises(fp.FormatPackError, match=r"files\.seed is required"):
        fp.load_pack(root)


@pytest.mark.parametrize("key", [
    "default_item_recipe", "rate_host_recipe", "rate_host_sheet",
    "rate_host_prefix", "default_prefix", "first_slot",
])
def test_every_scaffold_key_a_consumer_reads_is_required(tmp_path, key):
    root = _edit_seed(_make_pack(tmp_path, key.replace("_", "")),
                      lambda d: d["scaffold"].pop(key))
    with pytest.raises(fp.FormatPackError, match=rf"seed\.scaffold is missing.*{key}"):
        fp.load_pack(root)


def test_seed_scaffold_must_be_a_mapping(tmp_path):
    root = _edit_seed(_make_pack(tmp_path), lambda d: d.update(scaffold="nope"))
    with pytest.raises(fp.FormatPackError, match=r"seed\.scaffold is required"):
        fp.load_pack(root)


def test_seed_takeoff_mapping_must_be_a_mapping(tmp_path):
    root = _edit_seed(_make_pack(tmp_path), lambda d: d.update(takeoff_mapping=[1, 2]))
    with pytest.raises(fp.FormatPackError, match=r"seed\.takeoff_mapping is required"):
        fp.load_pack(root)


# ---------------------------------------------------------------------------
# markup_by_type: required -> seed.scaffold.default_markup must be a mapping
# ---------------------------------------------------------------------------

def _edit_vocab(root: Path, fn) -> Path:
    import yaml

    path = root / "vocabulary.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return root


def _require_markup_by_type(root: Path) -> Path:
    return _edit_vocab(root, lambda d: d.update(markup_by_type="required"))


def test_markup_by_type_required_needs_a_mapping_default_markup(tmp_path):
    """fieldbook's own situation: a pack whose vocabulary requires markup by
    cost type must give `scaffold` something that actually validates -- the
    plain `0` every other pack's skeleton keeps would fail the pack's own
    schema the moment anyone scaffolded a fresh item."""
    root = _require_markup_by_type(_make_pack(tmp_path))     # no default_markup at all
    with pytest.raises(fp.FormatPackError,
                       match=r"copy.*seed\.scaffold\.default_markup must be a mapping"):
        fp.load_pack(root)


def test_markup_by_type_required_refuses_a_non_mapping_default_markup(tmp_path):
    root = _require_markup_by_type(
        _edit_seed(_make_pack(tmp_path), lambda d: d["scaffold"].update(default_markup=0)))
    with pytest.raises(fp.FormatPackError,
                       match=r"seed\.scaffold\.default_markup must be a mapping"):
        fp.load_pack(root)


def test_markup_by_type_required_accepts_a_mapping_default_markup(tmp_path):
    root = _require_markup_by_type(
        _edit_seed(_make_pack(tmp_path),
                  lambda d: d["scaffold"].update(default_markup={"bond_pct": 0})))
    assert fp.load_pack(root).vocabulary["markup_by_type"] == "required"


def test_a_pack_without_markup_by_type_required_owes_no_default_markup(tmp_path):
    """Every other pack (markup_by_type false/true) keeps the plain `0`
    skeleton default -- no default_markup needed at all."""
    root = _make_pack(tmp_path)
    assert fp.load_pack(root).seed["scaffold"].get("default_markup") is None


# ---------------------------------------------------------------------------
# seed.scaffold.first_cost_code, when present, must be a non-empty string
# ---------------------------------------------------------------------------

def test_first_cost_code_if_present_must_be_a_non_empty_string(tmp_path):
    root = _edit_seed(_make_pack(tmp_path), lambda d: d["scaffold"].update(first_cost_code=""))
    with pytest.raises(fp.FormatPackError,
                       match=r"seed\.scaffold\.first_cost_code must be a non-empty string"):
        fp.load_pack(root)


def test_a_non_string_first_cost_code_is_refused(tmp_path):
    root = _edit_seed(_make_pack(tmp_path), lambda d: d["scaffold"].update(first_cost_code=1))
    with pytest.raises(fp.FormatPackError,
                       match=r"seed\.scaffold\.first_cost_code must be a non-empty string"):
        fp.load_pack(root)


def test_a_valid_first_cost_code_is_accepted(tmp_path):
    root = _edit_seed(_make_pack(tmp_path), lambda d: d["scaffold"].update(first_cost_code="01-100"))
    assert fp.load_pack(root).seed["scaffold"]["first_cost_code"] == "01-100"


def test_first_cost_code_is_optional(tmp_path):
    root = _make_pack(tmp_path)
    assert fp.load_pack(root).seed["scaffold"].get("first_cost_code") is None


# ---------------------------------------------------------------------------
# foreman_trade: a summarize concern, not every pack's tax
# ---------------------------------------------------------------------------

def _drop_foreman(root: Path) -> Path:
    import yaml

    path = root / "vocabulary.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc.pop("foreman_trade")
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return root


def test_foreman_trade_is_not_required_of_a_pack_that_never_summarizes(tmp_path):
    """Only summarize.py reads it, and summarize is capability-gated. A pack
    that declares no `supports: summarize` must not be taxed for a key no
    code path will ever consult."""
    pack = fp.load_pack(_drop_foreman(_write_min_pack(tmp_path, supports=[])))
    assert "summarize" not in pack.supports
    assert (pack.vocabulary or {}).get("foreman_trade") is None


def test_foreman_trade_is_required_of_a_pack_declaring_summarize(tmp_path):
    root = _drop_foreman(_write_min_pack(tmp_path, supports=["summarize"],
                                         labor={"crew_factor_default": 1}))
    with pytest.raises(fp.FormatPackError,
                       match=r"foreman_trade.*supports: summarize"):
        fp.load_pack(root)


# ---------------------------------------------------------------------------
# chosen: the difference between a pack someone named and the silent default
# ---------------------------------------------------------------------------

def test_a_pack_loaded_by_path_is_chosen():
    assert fp.load_pack(LEGACY_DIR).chosen is True


def test_the_bundled_fallback_is_not_chosen():
    """`bundled_pack()` is reached only when nothing named a pack, so it is the
    one pack that carries chosen=False — including via `resolve_pack`."""
    assert fp.bundled_pack().chosen is False
    assert fp.resolve_pack(None, Profile(data={})).chosen is False


def test_the_bundled_pack_named_explicitly_is_chosen():
    """--format pointing at the bundled pack is a choice like any other: the
    escape hatch require_chosen's message offers has to actually work."""
    assert fp.resolve_pack(str(fp.BUNDLED), None).chosen is True


def test_a_profile_named_pack_is_chosen():
    profile = Profile(data={"estimating": {"format": str(ALT_DIR)}})
    assert fp.resolve_pack(None, profile).chosen is True


def test_require_chosen_passes_a_named_pack():
    fp.require_chosen(fp.load_pack(LEGACY_DIR), "scaffold")


def test_require_chosen_refuses_the_unchosen_fallback_naming_both_fixes():
    with pytest.raises(fp.FormatPackError) as exc:
        fp.require_chosen(fp.bundled_pack(), "scaffold")
    message = str(exc.value)
    assert message.startswith("scaffold would use the bundled 'fieldbook' pack")
    assert "ESTIMATING_PROFILES" in message and "--format" in message


def test_scaffold_verbs_are_not_supports_entries():
    """The gate for these verbs is require_chosen, not `supports:`. Every pack
    carries the seed they read, so a supports entry would be one every pack
    always sets — and the bundled pack would have to set it too, reopening the
    hazard."""
    assert set(fp._TOOLS) == {"summarize", "artifact"}
    for verb in ("scaffold", "apply-takeoff", "scaffold-save"):
        assert verb not in fp._TOOLS


# ---------------------------------------------------------------------------
# seed.rate_table_trades: a name (labor) or {trade, kind} (fieldbook phase 3b)
# ---------------------------------------------------------------------------

def test_seed_rate_trades_reads_names_and_kinds():
    seed = {"rate_table_trades": ["Laborer", {"trade": "Loader", "kind": "equipment"},
                                  {"trade": "Pipelayer", "kind": "labor"}]}
    assert fp.seed_rate_trades(seed) == [
        {"trade": "Laborer", "kind": "labor"}, {"trade": "Loader", "kind": "equipment"},
        {"trade": "Pipelayer", "kind": "labor"}]
    assert fp.seed_rate_trades({}) == []


@pytest.mark.parametrize("bad", [
    "Laborer",                                    # not a list
    [3],                                          # neither a name nor a mapping
    [""],                                         # a blank name
    [{"kind": "equipment"}],                      # no trade
    [{"trade": "Loader", "kind": "machine"}],     # an unknown kind
    [{"trade": "Loader", "rate": 3}],             # an unknown key
])
def test_a_malformed_seed_rate_table_trades_is_refused(tmp_path, bad):
    root = _edit_seed(_make_pack(tmp_path), lambda d: d.update(rate_table_trades=bad))
    with pytest.raises(fp.FormatPackError, match=r"seed\.rate_table_trades"):
        fp.load_pack(root)


def test_a_seed_equipment_trade_loads(tmp_path):
    root = _edit_seed(_make_pack(tmp_path), lambda d: d["rate_table_trades"].append(
        {"trade": "Loader", "kind": "equipment"}))
    assert fp.seed_rate_trades(fp.load_pack(root).seed)[-1] == {"trade": "Loader",
                                                                "kind": "equipment"}


@pytest.mark.parametrize("bad", [
    "01-100",                                     # not a list
    [{"description": "no code"}],                 # no code
    [{"code": ""}],                               # a blank code
    [{"code": "01-100", "name": "typo"}],         # an unknown key
])
def test_a_malformed_seed_cost_codes_is_refused(tmp_path, bad):
    root = _edit_seed(_make_pack(tmp_path), lambda d: d.update(cost_codes=bad))
    with pytest.raises(fp.FormatPackError, match=r"seed\.cost_codes"):
        fp.load_pack(root)


@pytest.mark.parametrize("bad", ["yes", 1, None])
def test_a_non_boolean_rate_host_is_bid_recipe_is_refused(tmp_path, bad):
    root = _edit_seed(_make_pack(tmp_path),
                      lambda d: d["scaffold"].update(rate_host_is_bid_recipe=bad))
    with pytest.raises(fp.FormatPackError, match=r"seed\.scaffold\.rate_host_is_bid_recipe"):
        fp.load_pack(root)


def test_only_fieldbook_declares_its_rate_host_recipe_a_bid_item_recipe():
    assert fp.load_pack(fp.ENGINE_DIR / "packs" / "fieldbook").seed["scaffold"][
        "rate_host_is_bid_recipe"] is True
    assert "rate_host_is_bid_recipe" not in fp.load_pack(LEGACY_DIR).seed["scaffold"]
