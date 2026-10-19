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

from estimating_tools.estimate_spec import layout_map as LM

ENGINE_DIR = Path(__file__).resolve().parent
#: The pack `resolve_pack` falls back to when nothing names one. Fieldbook
#: since phase 3b; the demo pack it replaced survives only as the frozen
#: tests/fixtures/packs/legacy_demo fixture.
BUNDLED = ENGINE_DIR / "packs" / "fieldbook"
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
#: Keys `protect:` may carry. See `FormatPack.protect`.
_PROTECT_KEYS = frozenset({"sheets", "password"})
#: Keys a `seed.cost_codes` entry may carry.
_SEED_CODE_KEYS = frozenset({"code", "description"})
#: Keys a `seed.rate_table_trades` mapping entry may carry.
_SEED_TRADE_KEYS = frozenset({"trade", "kind"})
_RATE_KINDS = ("labor", "equipment")
#: The packs a pack may name in `derived_from:`, by name -> directory. A
#: derived pack keeps its base's layout contract (hidden Q..T tags, row-kind
#: vocabulary, input columns) and, when it declares no `layout_map:` of its
#: own, inherits the base's. Only the bundled fieldbook is a base today.
DERIVABLE = {"fieldbook": BUNDLED}


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


def _markup_schema(markup_by_type) -> dict:
    """The `markup` property: numOrFormula, plus markup_by_type when opted in
    (`true`), or markup_by_type ONLY when required (`"required"` -- a plain
    number/formula markup is refused outright, not just unread)."""
    if markup_by_type == "required":
        return {"$ref": "#/$defs/markup_by_type",
                "description": "Percentages by cost type plus a bond rate -- "
                               "this pack lays out its own markup sheet and "
                               "refuses a plain number/formula markup."}
    if markup_by_type is True:
        return {"oneOf": [{"$ref": "#/$defs/numOrFormula"}, {"$ref": "#/$defs/markup_by_type"}],
                "description": "Bond/markup dollars, a formula such as "
                               "'=E{row:subtotal}*0.10', or (markup_by_type) percentages "
                               "by cost type plus a bond rate."}
    return {"$ref": "#/$defs/numOrFormula",
            "description": "Bond/markup dollars, or a formula such as "
                           "'=E{row:subtotal}*0.10'."}


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
        # Object-form markup (percentages by cost type) is priced only by a
        # pack that lays out its own markup sheet to read them, so a pack opts
        # in with `markup_by_type: true` (also accepting a plain number), or
        # requires it outright with `markup_by_type: required` (refusing a
        # plain number/formula markup). Every other pack keeps the plain
        # number-or-formula markup it has always had.
        "markup": _markup_schema(vocabulary.get("markup_by_type")),
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
    #: Sheet protection the pack asks for: {"sheets": bool, "password": str}.
    #: Empty = no protection, which is every pack's behaviour before fieldbook.
    protect: dict = dataclass_field(default_factory=dict)
    #: True when a caller NAMED this pack — `--format`, the org profile's
    #: `estimating.format`, or a direct `load_pack(path)`. False only for the
    #: bundled pack reached as `resolve_pack`'s last-resort default.
    chosen: bool = True
    #: `strict: true` in the manifest: `build.generate` validates the spec
    #: against this pack's composed `schema` (the same jsonschema check
    #: `scaffold.validate_spec` runs) before laying anything out, instead of
    #: only ever checking cross-references. Opt-in and False by default, so
    #: every pack that doesn't set it keeps building exactly as before.
    strict: bool = False
    #: The `layout_map:` section, validated (see `layout_map.validate`), or
    #: None for a pack that declares none -- `est-estimate build` writes no
    #: defined names/document property/`_templates` sheet for that pack, and
    #: Estimate Navigator falls back to its heuristic reader.
    layout_map: dict | None = None
    #: `derived_from:` in the manifest: the pack (one of `DERIVABLE`) whose
    #: layout contract this pack keeps -- an org fork of fieldbook with its
    #: own name, trades and seed says `derived_from: fieldbook`. None for a
    #: pack that declares nothing. See `readback_family`.
    derived_from: str | None = None

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
    strict = meta.get("strict", False)
    if not isinstance(strict, bool):
        raise FormatPackError(
            f"{manifest}: 'strict' must be true or false "
            f"(got {type(strict).__name__} {strict!r})")
    if "summarize" in supports and "crew_factor_default" not in labor:
        raise FormatPackError(
            f"{manifest}: pack '{meta.get('name')}' declares supports: summarize "
            "but no labor.crew_factor_default")
    protect = meta.get("protect") or {}
    if not isinstance(protect, dict) or set(protect) - _PROTECT_KEYS:
        raise FormatPackError(
            f"{manifest}: 'protect' must be a mapping with keys {sorted(_PROTECT_KEYS)}")
    sheets = protect.get("sheets", False)
    if not isinstance(sheets, bool):
        raise FormatPackError(
            f"{manifest}: protect.sheets must be true/false "
            f"(got {type(sheets).__name__} {sheets!r})")
    password = protect.get("password", "")
    if not isinstance(password, str):
        raise FormatPackError(
            f"{manifest}: protect.password must be a string "
            f"(got {type(password).__name__} {password!r})")
    if password and not sheets:
        raise FormatPackError(
            f"{manifest}: protect.password is set but protect.sheets is not "
            "true -- a password only means something once sheets are protected")
    derived_from = meta.get("derived_from")
    if derived_from is not None:
        if not isinstance(derived_from, str) or not derived_from.strip():
            raise FormatPackError(
                f"{manifest}: derived_from must be a non-empty string naming a pack "
                f"(got {type(derived_from).__name__} {derived_from!r})")
        if derived_from not in DERIVABLE:
            raise FormatPackError(
                f"{manifest}: derived_from {derived_from!r} is not a pack a pack can "
                f"derive from (supported: {sorted(DERIVABLE)})")
    layout_map = None
    if "layout_map" in meta:
        try:
            layout_map = LM.validate(meta["layout_map"], str(manifest))
        except LM.LayoutMapError as exc:
            raise FormatPackError(str(exc)) from None
    elif derived_from is not None:
        # No map of its own: the base's, as this pack's own copy (a caller
        # editing one pack's map must never reach the cached base's).
        layout_map = copy.deepcopy(_base_pack(derived_from).layout_map)
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
    if vocab.get("markup_by_type", False) not in (True, False, "required"):
        raise FormatPackError(
            f"{root}: pack '{meta.get('name')}' vocabulary.markup_by_type must be "
            f"true, false or 'required' (got {vocab['markup_by_type']!r})")
    from estimating_tools.estimate_spec.recipe import RecipeError, validate_recipes
    try:
        validate_recipes(recipes, units["units"])
    except RecipeError as exc:
        raise FormatPackError(f"{root}: files.recipes: {exc}") from exc
    recipe_names = [k for k in recipes["recipes"] if k != "cover"]

    if layout_map is not None and "layout_map" not in meta:
        misfits = LM.fit_problems(layout_map, recipes, units["units"])
        if misfits:
            raise FormatPackError(
                f"{manifest}: layout_map inherited from {derived_from} does not fit this "
                f"pack: {'; '.join(misfits)}; keep {derived_from}'s Cost Summary/Checks/Codes "
                "export names or declare your own layout_map:")

    tpl_recipe = ((layout_map or {}).get("templates") or {}).get("item", {}).get("recipe")
    if tpl_recipe is not None and tpl_recipe not in (recipes.get("recipes") or {}):
        raise FormatPackError(
            f"{manifest}: layout_map.templates.item.recipe {tpl_recipe!r} is not a recipe "
            f"of this pack (recipes: {sorted(recipes.get('recipes') or {})})")

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

    # A pack whose vocabulary requires markup by cost type (markup_by_type:
    # required -- fieldbook's own situation) must give `scaffold` a markup
    # value its OWN schema actually accepts; the plain `0` every other
    # pack's skeleton keeps would fail that pack's own schema the moment
    # anyone scaffolded a fresh item.
    if vocab.get("markup_by_type") == "required":
        default_markup = scaffold.get("default_markup")
        if not isinstance(default_markup, dict):
            raise FormatPackError(
                f"{root}: pack '{meta.get('name')}' declares vocabulary "
                "markup_by_type: required, so seed.scaffold.default_markup must be a "
                f"mapping of percentages by cost type (got "
                f"{type(default_markup).__name__} {default_markup!r})")

    _check_seed_rate_trades(seed, f"{root}: pack '{meta.get('name')}'")
    _check_seed_cost_codes(seed, f"{root}: pack '{meta.get('name')}'")

    if not isinstance(scaffold.get("rate_host_is_bid_recipe", False), bool):
        raise FormatPackError(
            f"{root}: pack '{meta.get('name')}' seed.scaffold.rate_host_is_bid_recipe "
            f"must be true or false (got {scaffold['rate_host_is_bid_recipe']!r})")

    first_cost_code = scaffold.get("first_cost_code")
    if first_cost_code is not None and (
            not isinstance(first_cost_code, str) or not first_cost_code):
        raise FormatPackError(
            f"{root}: pack '{meta.get('name')}' seed.scaffold.first_cost_code must be "
            f"a non-empty string (got {type(first_cost_code).__name__} {first_cost_code!r})")

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
                      protect=protect, chosen=chosen, strict=strict,
                      layout_map=layout_map, derived_from=derived_from)


def _check_seed_rate_trades(seed: dict, who: str) -> None:
    """`seed.rate_table_trades` (optional): each entry a resource name (a
    labor rate row) or `{trade: NAME, kind: labor|equipment}`."""
    if "rate_table_trades" not in seed:
        return
    entries = seed["rate_table_trades"]
    if not isinstance(entries, list):
        raise FormatPackError(f"{who} seed.rate_table_trades must be a list, got {entries!r}")
    for i, entry in enumerate(entries):
        where = f"{who} seed.rate_table_trades[{i}]"
        if isinstance(entry, dict):
            unknown = set(entry) - _SEED_TRADE_KEYS
            if unknown:
                raise FormatPackError(f"{where}: unknown keys {sorted(unknown)} "
                                      f"(allowed: {sorted(_SEED_TRADE_KEYS)})")
            name, kind = entry.get("trade"), entry.get("kind", "labor")
            if kind not in _RATE_KINDS:
                raise FormatPackError(f"{where}: kind must be one of {list(_RATE_KINDS)}, "
                                      f"got {kind!r}")
        else:
            name = entry
        if not isinstance(name, str) or not name:
            raise FormatPackError(
                f"{where}: must be a resource name or {{trade: NAME, kind: labor|equipment}}, "
                f"got {entry!r}")


def _check_seed_cost_codes(seed: dict, who: str) -> None:
    """`seed.cost_codes` (optional): `[{code, description}]`, the org's code
    list. scaffold copies it into a spec's own `cost_codes`, which the schema
    checks, so a malformed seed list is refused here, by name, instead of
    failing every scaffold."""
    if "cost_codes" not in seed:
        return
    codes = seed["cost_codes"]
    if not isinstance(codes, list):
        raise FormatPackError(f"{who} seed.cost_codes must be a list, got {codes!r}")
    for i, entry in enumerate(codes):
        where = f"{who} seed.cost_codes[{i}]"
        if not isinstance(entry, dict) or set(entry) - _SEED_CODE_KEYS:
            raise FormatPackError(f"{where}: must be a mapping with keys "
                                  f"{sorted(_SEED_CODE_KEYS)}, got {entry!r}")
        if not isinstance(entry.get("code"), str) or not entry["code"]:
            raise FormatPackError(f"{where}: code must be non-empty text, got {entry!r}")
        if not isinstance(entry.get("description", ""), str):
            raise FormatPackError(f"{where}: description must be text, got {entry!r}")


def seed_rate_trades(seed: dict | None) -> list[dict]:
    """The seed's rate-table trades as `[{trade, kind}]`: a bare name is a
    labor rate row; `{trade, kind}` names its kind (an equipment rate row).
    Shape-checked at load by `_check_seed_rate_trades`."""
    out = []
    for entry in (seed or {}).get("rate_table_trades") or []:
        if isinstance(entry, dict):
            out.append({"trade": entry["trade"], "kind": entry.get("kind", "labor")})
        else:
            out.append({"trade": entry, "kind": "labor"})
    return out


#: `scaffold_meta.source` and `item_no` of the rate-table host `scaffold`
#: injects when no mobilization item was selected (see scaffold.py).
RATE_HOST_SOURCE = "scaffold:rate_host"
RATE_HOST_ITEM_NO = "RATES"


def is_rate_host(item: dict, pack: FormatPack) -> bool:
    """True when `item` is the pack's rate-table host -- the item that carries
    no reusable bid-item content (scaffold-save skips it; apply-takeoff does
    not list it as unmatched).

    By default every item of `seed.scaffold.rate_host_recipe` is the host: a
    pack whose rate table lives on that recipe's own sheet uses the recipe for
    nothing else (the legacy_demo fixture's `setup`). A pack whose host recipe
    is also an ordinary bid-item recipe -- its rate table lives elsewhere, as
    fieldbook's lives on its Rates book sheet and its host recipe is
    `lump_sum` -- opts in with `seed.scaffold.rate_host_is_bid_recipe: true`;
    then only the scaffold-injected host (`item_no` RATES / `scaffold_meta.
    source` scaffold:rate_host) is, and its lump-sum bid items are not."""
    sc = pack.seed["scaffold"]
    if sc.get("rate_host_is_bid_recipe"):
        meta = item.get("scaffold_meta")
        return (str(item.get("item_no", "")) == RATE_HOST_ITEM_NO
                or (isinstance(meta, dict) and meta.get("source") == RATE_HOST_SOURCE))
    return item.get("recipe") == sc["rate_host_recipe"]


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


@lru_cache(maxsize=None)
def _base_pack(name: str) -> FormatPack:
    """The `DERIVABLE` pack `name`, loaded once. Loaded from its own
    directory, not through `bundled_pack()`, so a derived pack's base never
    follows whatever the bundled fallback is (tests redirect that)."""
    return load_pack(DERIVABLE[name])


def readback_family(pack: FormatPack) -> str:
    """The layout contract `pack`'s workbooks follow: its `derived_from`
    base, or its own name. Read-back reads a workbook by its family -- a
    fork that keeps fieldbook's grid is read the way fieldbook is."""
    return pack.derived_from or pack.name


@lru_cache(maxsize=1)
def bundled_pack() -> FormatPack:
    """The fallback pack. `chosen=False`: reaching it means nobody named one."""
    return load_pack(BUNDLED, chosen=False)


def resolve_pack(cli_path=None, profile=None) -> FormatPack:
    """`--format PATH` > profile `estimating.format` > the bundled pack.

    `--format` also takes a base pack's bare name (`--format fieldbook`, a key
    of `DERIVABLE`) when no such path exists: the bundled directory is not
    somewhere an estimator can be expected to know."""
    if cli_path:
        if not Path(cli_path).exists() and str(cli_path) in DERIVABLE:
            return load_pack(DERIVABLE[str(cli_path)])
        return load_pack(cli_path)
    if profile is not None:
        named = profile.section("estimating").get("format")
        if named:
            return load_pack(named)
    return bundled_pack()
