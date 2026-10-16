"""Format packs: the data that decides what an estimate workbook looks like.

A pack is a directory holding a `format.yaml` manifest and the documents it
names: units (structure), tokens (style), recipes (composition), vocabulary
(what is permitted — trades, cost blocks, takeoff/spreads shapes) and seed
(what a fresh spec starts with, and how apply-takeoff routes geometry). All
five are required: scaffold, apply-takeoff and compact subscript the seed's
`scaffold` and `takeoff_mapping` blocks bare, so a pack missing either is
refused by name at load rather than dying on a KeyError mid-run. The
plugin's own schema skeleton (mechanism + `{"$vocab": KEY}` markers) is composed with the
pack's vocabulary at load time into `FormatPack.schema`; a pack never ships
its own schema file.

Packs are DATA, never code: every document is read with yaml.safe_load or
json.loads, and nothing a pack names is imported or executed.

Resolution, in precedence order: an explicit path (`--format`), the org
profile's `estimating.format`, then the bundled pack. A pack that is named but
missing or invalid is an error — never a silent fall back to another format.

That third step is the only one nobody asked for, so a pack records whether it
was CHOSEN: `load_pack` is always someone naming a path, `resolve_pack`'s
final fallback is not. `require_chosen` is how the verbs that write a
pack-shaped artifact from non-spec inputs refuse to do it against a pack the
environment picked by default. See `require_chosen` for why that gate is not
`supports:`.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field as dataclass_field
from functools import lru_cache
from pathlib import Path

import yaml

ENGINE_DIR = Path(__file__).resolve().parent
BUNDLED = ENGINE_DIR / "packs" / "demo"
SKELETON = ENGINE_DIR / "schema" / "skeleton.schema.json"
MANIFEST = "format.yaml"
_REQUIRED = ("units", "tokens", "recipes", "vocabulary", "seed")
_OPTIONAL = ()
#: Vocabulary keys every pack must carry. `foreman_trade` is NOT here: only
#: summarize.py reads it, and summarize is capability-gated, so requiring it
#: of every pack taxes packs that will never be summarized. It is required of
#: a pack declaring `supports: [summarize]` instead — see `_SUMMARIZE_VOCAB`.
_VOCAB_KEYS = ("trades", "cost_blocks", "slot_pattern", "defs")
#: Vocabulary keys a pack must carry to declare `supports: summarize`.
_SUMMARIZE_VOCAB = ("foreman_trade",)
#: `seed.scaffold` keys the scaffold / apply-takeoff / compact verbs subscript
#: bare. Validated at load so a third-party pack is refused by name rather
#: than dying on an unnamed KeyError halfway through a scaffold.
_SCAFFOLD_KEYS = ("default_item_recipe", "rate_host_recipe", "rate_host_sheet",
                  "rate_host_prefix", "default_prefix", "first_slot")
#: The two `_SCAFFOLD_KEYS` that must name a recipe the pack actually defines.
_SCAFFOLD_RECIPE_KEYS = ("default_item_recipe", "rate_host_recipe")
# Tools that need shapes BEYOND the universal pack contract, which a pack opts
# into with `supports:`; every other pack is refused. The bar is a promise the
# loader can check: `summarize` owes `vocabulary.foreman_trade` and
# `labor.crew_factor_default` (both enforced below), `artifact` owes its
# cost-detail layout.
#
# scaffold / apply-takeoff / scaffold-save are deliberately NOT here. They need
# only `seed.scaffold` and `seed.takeoff_mapping`, which every pack must carry
# (see the seed checks in `load_pack`), so every valid pack structurally
# supports them and a `supports:` entry would be one every pack always sets.
# Their hazard is a different one — an unchosen pack — and `require_chosen` is
# what addresses it.
_TOOLS = ("summarize", "artifact")


class FormatPackError(ValueError):
    """A format pack is missing, malformed, or unsafe."""


@lru_cache(maxsize=1)
def _skeleton() -> dict:
    return json.loads(SKELETON.read_text(encoding="utf-8"))


def _local_refs_only(node, where: str = "defs") -> None:
    """Pack-supplied schema may only $ref within the composed document."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and not (isinstance(v, str) and v.startswith("#")):
                raise FormatPackError(f"vocabulary {where}: $ref {v!r} is not local (must start with '#')")
            _local_refs_only(v, f"{where}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _local_refs_only(v, f"{where}[{i}]")


def compose_schema(skeleton: dict, vocabulary: dict, recipe_names: list) -> dict:
    """Fill every {"$vocab": KEY} marker in the plugin skeleton from the pack."""
    _local_refs_only(vocabulary.get("defs") or {})
    render = {
        "recipes": {"enum": list(recipe_names)},
        "trades": {"enum": list(vocabulary["trades"])},
        "cost_blocks": {"enum": list(vocabulary["cost_blocks"])},
        "slot": {"type": "string", "pattern": vocabulary["slot_pattern"]},
        "item_rules": list(vocabulary.get("item_rules") or []),
        "takeoff": vocabulary["defs"]["takeoff"],
        "spreads": vocabulary["defs"]["spreads"],
        # A pack that defines no defs.rebar_spread simply does not permit the
        # field: `False` is a valid JSON Schema (draft 2020-12) that no
        # instance can ever satisfy, matching the old additionalProperties
        # rejection every pack got before this marker existed.
        "rebar_spread": (vocabulary.get("defs") or {}).get("rebar_spread", False),
        # Unlike rebar_spread, `schedule` is documentation-only -- no render
        # path reads it -- so a pack that supplies no defs.schedule still
        # gets a plain object accepted (never narrower than that): its detail
        # is org-shaped, but permitting *a* schedule is generic.
        "schedule": (vocabulary.get("defs") or {}).get("schedule", {"type": "object"}),
    }

    def fill(node):
        if isinstance(node, dict):
            if set(node) == {"$vocab"}:
                key = node["$vocab"]
                if key not in render:
                    raise FormatPackError(f"skeleton names unknown vocabulary {key!r}")
                return copy.deepcopy(render[key])
            out = {}
            for k, v in node.items():
                v = fill(v)
                if k == "allOf" and v == []:
                    continue                  # an empty allOf is not valid JSON Schema
                out[k] = v
            return out
        if isinstance(node, list):
            return [fill(v) for v in node]
        return node

    return fill(skeleton)


@dataclass(frozen=True, eq=False)
class FormatPack:
    root: Path
    name: str
    version: str
    units: dict            # the `units:` map from units.yaml
    tokens: dict
    recipes: dict          # the whole recipes.yaml document
    schema: dict
    vocabulary: dict | None = None
    seed: dict | None = None
    supports: frozenset = frozenset()     # extra tools from _TOOLS this pack opts into
    labor: dict = dataclass_field(default_factory=dict)   # org labor policy, e.g. crew_factor_default
    #: True when a caller NAMED this pack — `--format`, the org profile's
    #: `estimating.format`, or a direct `load_pack(path)`. False only for the
    #: bundled pack reached as `resolve_pack`'s last-resort default.
    chosen: bool = True

    @property
    def key(self) -> tuple[str, str, str]:
        """Stable identity for caches (the dataclass hashes by object identity)."""
        return (str(self.root), self.name, self.version)


def _read(path: Path, what: str):
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise FormatPackError(f"{path} ({what}): {exc}") from exc


def load_pack(root, *, chosen: bool = True) -> FormatPack:
    """Load and check the pack at `root`. Raises FormatPackError on any defect.

    `chosen=False` marks a pack nothing named — only `bundled_pack()` passes it.
    """
    root = Path(root).resolve()
    manifest = root / MANIFEST
    if not manifest.is_file():
        raise FormatPackError(f"{root}: not a format pack (no {MANIFEST})")
    meta = _read(manifest, "manifest")
    if not isinstance(meta, dict):
        raise FormatPackError(f"{manifest}: must be a mapping")
    for required_field in ("name", "version"):
        if meta.get(required_field) in (None, ""):
            raise FormatPackError(f"{manifest}: missing '{required_field}'")
    supports = meta.get("supports") or []
    if not isinstance(supports, list):
        raise FormatPackError(f"{manifest}: 'supports' must be a list")
    bad = sorted(str(t) for t in supports if t not in _TOOLS)
    if bad:
        raise FormatPackError(f"{manifest}: unknown supports {bad} (allowed: {list(_TOOLS)})")
    labor = meta.get("labor") or {}
    if not isinstance(labor, dict):
        raise FormatPackError(f"{manifest}: 'labor' must be a mapping")
    if "summarize" in supports and "crew_factor_default" not in labor:
        raise FormatPackError(
            f"{manifest}: pack '{meta.get('name')}' declares supports: summarize "
            "but no labor.crew_factor_default")
    files = meta.get("files") or {}
    unknown = sorted(set(files) - set(_REQUIRED) - set(_OPTIONAL))
    if unknown:
        raise FormatPackError(f"{manifest}: unknown files entries {unknown}")

    docs: dict = {}
    for key in _REQUIRED + _OPTIONAL:
        rel = files.get(key)
        if rel is None:
            raise FormatPackError(f"{manifest}: files.{key} is required")
        path = (root / rel).resolve()
        if not path.is_relative_to(root):
            raise FormatPackError(f"{manifest}: files.{key} escapes the pack ({rel})")
        if not path.is_file():
            raise FormatPackError(f"{manifest}: files.{key} -> {rel} not found")
        docs[key] = _read(path, f"files.{key}")

    units = docs["units"]
    if not isinstance(units, dict) or not isinstance(units.get("units"), dict):
        raise FormatPackError(f"{root}: files.units has no 'units' mapping")
    recipes = docs["recipes"]
    if not isinstance(recipes, dict) or not isinstance(recipes.get("recipes"), dict):
        raise FormatPackError(f"{root}: files.recipes has no 'recipes' mapping")

    vocab = docs["vocabulary"]
    if not isinstance(vocab, dict):
        raise FormatPackError(f"{root}: files.vocabulary must be a mapping")
    needed = _VOCAB_KEYS + (_SUMMARIZE_VOCAB if "summarize" in supports else ())
    missing = [k for k in needed if k not in vocab]
    if missing or not {"takeoff", "spreads"} <= set(vocab.get("defs") or {}):
        why = missing or ["defs.takeoff/spreads"]
        because = (" (required because it declares supports: summarize)"
                   if missing and set(missing) <= set(_SUMMARIZE_VOCAB) else "")
        raise FormatPackError(
            f"{root}: pack '{meta.get('name')}' vocabulary is missing {why}{because}")
    from estimating_tools.estimate_spec.recipe import RecipeError, validate_recipes
    try:
        validate_recipes(recipes, units["units"])
    except RecipeError as exc:
        raise FormatPackError(f"{root}: files.recipes: {exc}") from exc
    recipe_names = [k for k in recipes["recipes"] if k != "cover"]

    # seed.scaffold and seed.takeoff_mapping are REQUIRED, not merely checked
    # when present. scaffold.py, apply.py, compact.py and scaffold_save.py all
    # subscript them bare, so a pack without them loaded cleanly and then died
    # with an unnamed KeyError partway through someone's scaffold. Refuse at
    # load instead, naming the pack and what is missing.
    seed = docs["seed"]
    if not isinstance(seed, dict):
        raise FormatPackError(
            f"{root}: pack '{meta.get('name')}' files.seed must be a mapping")
    scaffold = seed.get("scaffold")
    if not isinstance(scaffold, dict):
        raise FormatPackError(
            f"{root}: pack '{meta.get('name')}' seed.scaffold is required and "
            f"must be a mapping (keys: {list(_SCAFFOLD_KEYS)})")
    absent = [k for k in _SCAFFOLD_KEYS if not scaffold.get(k)]
    if absent:
        raise FormatPackError(
            f"{root}: pack '{meta.get('name')}' seed.scaffold is missing {absent}")
    for key in _SCAFFOLD_RECIPE_KEYS:
        name = scaffold[key]
        if name not in recipe_names:
            raise FormatPackError(
                f"{root}: pack '{meta.get('name')}' seed.scaffold.{key} "
                f"names unknown recipe {name!r}")
    placeholder = scaffold.get("placeholder_takeoff")
    if placeholder is not None:
        kind = placeholder.get("kind") if isinstance(placeholder, dict) else None
        allowed = vocab["defs"]["takeoff"]["properties"]["kind"]["enum"]
        if kind not in allowed:
            raise FormatPackError(
                f"{root}: pack '{meta.get('name')}' "
                f"seed.scaffold.placeholder_takeoff.kind {kind!r} not in {allowed}")

    takeoff_mapping = seed.get("takeoff_mapping")
    if not isinstance(takeoff_mapping, dict):
        raise FormatPackError(
            f"{root}: pack '{meta.get('name')}' seed.takeoff_mapping is required "
            "and must be a mapping (keys: ['kind', 'line_fields', 'section_types'])")
    kind = takeoff_mapping.get("kind")
    allowed = vocab["defs"]["takeoff"]["properties"]["kind"]["enum"]
    if kind not in allowed:
        raise FormatPackError(
            f"{root}: pack '{meta.get('name')}' "
            f"seed.takeoff_mapping.kind {kind!r} not in {allowed}")
    line_fields = takeoff_mapping.get("line_fields")
    if not isinstance(line_fields, list) or not line_fields or \
            not all(isinstance(f, str) for f in line_fields):
        raise FormatPackError(
            f"{root}: pack '{meta.get('name')}' "
            f"seed.takeoff_mapping.line_fields must be a non-empty list of strings")
    section_types = takeoff_mapping.get("section_types")
    if not isinstance(section_types, dict) or not section_types:
        raise FormatPackError(
            f"{root}: pack '{meta.get('name')}' "
            f"seed.takeoff_mapping.section_types must be a non-empty mapping")
    field_set = set(line_fields)
    for stype, entry in section_types.items():
        if not isinstance(entry, dict) or "cy" not in entry or "cf" not in entry:
            raise FormatPackError(
                f"{root}: pack '{meta.get('name')}' "
                f"seed.takeoff_mapping.section_types.{stype} needs 'cy' and 'cf'")
        for key in ("cy", "cf"):
            if entry[key] not in field_set:
                raise FormatPackError(
                    f"{root}: pack '{meta.get('name')}' "
                    f"seed.takeoff_mapping.section_types.{stype}.{key} "
                    f"{entry[key]!r} not in line_fields")

    schema = compose_schema(_skeleton(), vocab, recipe_names)

    return FormatPack(root=root, name=str(meta["name"]), version=str(meta["version"]),
                      units=units["units"], tokens=docs["tokens"], recipes=recipes,
                      schema=schema, vocabulary=vocab,
                      seed=docs["seed"], supports=frozenset(supports), labor=labor,
                      chosen=chosen)


def require_support(pack: FormatPack, tool: str) -> None:
    """Refuse a pack that does not declare `tool` in its `supports:` list."""
    if tool not in pack.supports:
        raise FormatPackError(f"pack '{pack.name}' does not support {tool}")


def require_chosen(pack: FormatPack, verb: str) -> None:
    """Refuse a pack nothing named, for a `verb` that writes from non-spec input.

    Not a `supports:` question. Every valid pack can be scaffolded against —
    the loader requires the `seed.scaffold` and `seed.takeoff_mapping` these
    verbs read. The hazard is that `resolve_pack`'s last step is silent: on a
    machine with no ESTIMATING_PROFILES, `scaffold` and `scaffold-save` take
    their shapes from a pack the estimator never picked, and neither verb has
    a spec of the org's own to be checked against. `build` does not need this
    gate — its schema IS the pack's vocabulary, so a foreign spec is refused
    by name.
    """
    if not pack.chosen:
        raise FormatPackError(
            f"{verb} would use the bundled '{pack.name}' pack, which nothing "
            "named. Its recipes, sheet prefixes and takeoff routing are not "
            "your org's, and this verb writes a file, so the mistake would "
            "surface later as a spec that will not build. Set "
            "ESTIMATING_PROFILES to your org profile, or pass --format PATH "
            "(the bundled pack's own path works, if you meant it).")


@lru_cache(maxsize=1)
def bundled_pack() -> FormatPack:
    """The fallback pack. `chosen=False`: reaching it means nobody named one."""
    return load_pack(BUNDLED, chosen=False)


def resolve_pack(cli_path=None, profile=None) -> FormatPack:
    """`--format PATH` > profile `estimating.format` > the bundled pack."""
    if cli_path:
        return load_pack(cli_path)
    if profile is not None:
        named = profile.section("estimating").get("format")
        if named:
            return load_pack(named)
    return bundled_pack()
