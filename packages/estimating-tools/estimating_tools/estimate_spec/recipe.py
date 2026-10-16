"""Recipe expansion: a recipe entry plus a bid item -> unit instances.

Pure functions, no openpyxl. build.py's layout loop calls these, so the loop
never names a unit. Everything here reads pack DATA; nothing is evaluated.

Expansion-time template tokens (resolved before layout):
    {it.PATH}                 the current for_each element ({it} = the element)
    {item.PATH}               the bid item being laid out
    {config.PATH}             the top-level estimate config
    {span:UNIT.first|last}    first/last row a unit occupied on this sheet
Every other {...} token (ref:, row:, p., r, declared globals) is left verbatim
for the write-time Resolver. Tokens nest, innermost first:
{ref:cost_detail[{it.name}].subtotal} expands {it.name} now and keeps the ref.

A template that is exactly one expansion-time token ("{item.takeoff}") yields
the raw value (dict, list, number or None), not its string form.

Param values, recursively: a string is a template; {from: PATH, default: X}
reads PATH (X when the key is absent); {for_each: PATH, as: V} builds a list;
{sum_existing: [EXPORT, ...]} sums the exports already published on this
sheet; other dicts and lists resolve element-wise.
"""
from __future__ import annotations

import copy
import re

_TOKEN = re.compile(r"\{([^{}]+)\}")
_WHOLE = re.compile(r"^\{([^{}]+)\}$")
_SCOPED = ("it", "item", "config")

ENTRY_KEYS = frozenset({"unit", "when", "variant_from", "variants", "for_each", "key",
                        "params", "instance_defaults", "default_key", "sheet"})
_RESERVED_GLOBALS = frozenset({"p", "it", "item", "config", "r", "row", "ref", "span"})
_GLOBAL_KEYS = frozenset({"export", "default", "scope", "qualify"})


class RecipeError(ValueError):
    """A recipe document or entry cannot be expanded."""


class _Missing:
    def __repr__(self):
        return "MISSING"


MISSING = _Missing()


def get_path(scopes: dict, path: str):
    """Value at `scope.a.b` in `scopes`, or MISSING if any step is absent."""
    head, _, rest = path.partition(".")
    if head not in scopes:
        return MISSING
    val = scopes[head]
    for part in rest.split(".") if rest else ():
        if isinstance(val, dict) and part in val:
            val = val[part]
        else:
            return MISSING
    return val


def _lookup(scopes: dict, token: str):
    if token.startswith("span:"):
        unit, _, end = token[5:].rpartition(".")
        if end not in ("first", "last") or not unit:
            raise RecipeError(f"malformed span token {{{token}}}")
        span = scopes.get("span", {}).get(unit)
        return None if span is None else span[0 if end == "first" else 1]
    head = token.split(".", 1)[0]
    if head not in _SCOPED or head not in scopes:
        return MISSING                     # not ours: the write-time Resolver's
    val = get_path(scopes, token)
    if val is MISSING:
        raise RecipeError(f"{{{token}}}: no such field")
    return val


def expand(template, scopes: dict):
    if not isinstance(template, str):
        return template
    whole = _WHOLE.match(template)
    if whole:
        val = _lookup(scopes, whole.group(1).strip())
        if val is not MISSING:
            return val
    cur = template
    for _ in range(10):
        changed = False

        def sub(m):
            nonlocal changed
            val = _lookup(scopes, m.group(1).strip())
            if val is MISSING:
                return m.group(0)
            changed = True
            return str(val)

        nxt = _TOKEN.sub(sub, cur)
        if not changed:
            return cur
        cur = nxt
    raise RecipeError(f"template does not settle: {template!r}")


def resolve_value(value, scopes: dict):
    if isinstance(value, str):
        return expand(value, scopes)
    if isinstance(value, list):
        return [resolve_value(v, scopes) for v in value]
    if isinstance(value, dict):
        if "from" in value:
            got = get_path(scopes, value["from"])
            return value.get("default") if got is MISSING else got
        if "for_each" in value:
            seq = get_path(scopes, value["for_each"])
            seq = [] if seq is MISSING or seq is None else seq
            return [resolve_value(value["as"], {**scopes, "it": el}) for el in seq]
        if "sum_existing" in value:
            published = scopes.get("exports", {})
            refs = [f"{{ref:{k}}}" for k in value["sum_existing"] if k in published]
            return "=SUM(" + ",".join(refs) + ")"
        return {k: resolve_value(v, scopes) for k, v in value.items()}
    return value


def is_active(entry: dict, scopes: dict) -> bool:
    if "when" not in entry:
        return True
    got = get_path(scopes, entry["when"])
    return got is not MISSING and bool(got)


def concrete_unit(entry: dict, scopes: dict, recipes_doc: dict) -> str:
    if "variant_from" not in entry:
        return entry["unit"]
    kind = get_path(scopes, entry["variant_from"])
    table = recipes_doc.get(entry["variants"]) or {}
    try:
        return table[kind]
    except (KeyError, TypeError):
        raise RecipeError(
            f"{entry['unit']}: {entry['variant_from']} = {kind!r} is not a kind in "
            f"{entry['variants']} {sorted(table)}") from None


def _params(entry: dict, scopes: dict) -> dict:
    params = copy.deepcopy(resolve_value(entry.get("params", {}), scopes))
    if not isinstance(params, dict):
        raise RecipeError(f"{entry['unit']}: params resolved to {type(params).__name__}")
    if "instance_defaults" in entry:
        name = expand(entry["default_key"], scopes)
        for k, v in (entry["instance_defaults"].get(name) or {}).items():
            if params.get(k) is None:
                params[k] = v
    return params


def instances(entry: dict, scopes: dict) -> list:
    """[(export_key_or_None, params)], one per instance the entry produces."""
    if "for_each" not in entry:
        key = expand(entry["key"], scopes) if "key" in entry else None
        return [(key, _params(entry, scopes))]
    seq = get_path(scopes, entry["for_each"])
    out = []
    for el in ([] if seq is MISSING or seq is None else seq):
        s = {**scopes, "it": el}
        out.append((expand(entry["key"], s) if "key" in entry else None, _params(entry, s)))
    return out


def validate_recipes(recipes_doc: dict, units: dict) -> None:
    """Refuse a recipes document the engine cannot render, naming where."""
    for gname, g in (recipes_doc.get("globals") or {}).items():
        if gname in _RESERVED_GLOBALS or not gname.isidentifier():
            raise RecipeError(f"globals.{gname}: name is reserved or not an identifier")
        bad = set(g) - _GLOBAL_KEYS
        if bad or "export" not in g:
            raise RecipeError(f"globals.{gname}: needs 'export', allows {sorted(_GLOBAL_KEYS)}")
        if g.get("scope", "sheet") not in ("sheet", "workbook"):
            raise RecipeError(f"globals.{gname}: scope must be sheet or workbook")
    for rname, recipe in (recipes_doc.get("recipes") or {}).items():
        if "position" in recipe:
            raise RecipeError(
                f"recipes.{rname}: 'position' is not honoured -- sheet order "
                "follows the estimate config's item order (plus the cover, "
                "always first); remove 'position' rather than set something inert"
            )
        for i, entry in enumerate(recipe.get("units") or []):
            where = f"recipes.{rname}[{i}]"
            unknown = set(entry) - ENTRY_KEYS
            if unknown:
                raise RecipeError(f"{where}: unknown keys {sorted(unknown)}")
            if "variant_from" in entry:
                table = recipes_doc.get(entry.get("variants"))
                if not isinstance(table, dict):
                    raise RecipeError(f"{where}: variants table {entry.get('variants')!r} not found")
                for kind, unit in table.items():
                    if unit not in units:
                        raise RecipeError(f"{where}: variant {kind!r} -> unknown unit {unit!r}")
            elif entry.get("unit") not in units:
                raise RecipeError(f"{where}: unknown unit {entry.get('unit')!r}")
            if "instance_defaults" in entry and "default_key" not in entry:
                raise RecipeError(f"{where}: instance_defaults needs default_key")
            if "sheet" in entry and not (units.get(entry.get("unit")) or {}).get("anchor"):
                raise RecipeError(f"{where}: 'sheet' is allowed only on anchored units")
