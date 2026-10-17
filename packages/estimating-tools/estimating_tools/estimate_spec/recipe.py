"""Recipe expansion: a recipe entry plus a bid item -> unit instances.

Pure functions, no openpyxl. build.py's layout loop calls these, so the loop
never names a unit. Everything here reads pack DATA; nothing is evaluated.

Expansion-time template tokens (resolved before layout):
    {it.PATH}                 the current for_each element ({it} = the element)
    {item.PATH}               the bid item being laid out
    {config.PATH}             the top-level estimate config
    {book.PATH}                workbook-level scope on a book sheet; book.items = the bid items it lists
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
_SCOPED = ("it", "item", "config", "book")

ENTRY_KEYS = frozenset({"unit", "when", "variant_from", "variants", "for_each", "key",
                        "params", "instance_defaults", "default_key", "sheet"})
_RESERVED_GLOBALS = frozenset({"p", "it", "item", "config", "r", "row", "ref", "span", "book"})
_GLOBAL_KEYS = frozenset({"export", "default", "scope", "qualify"})
#: Keys a `book:` entry's sheet mapping may carry.
BOOK_SHEET_KEYS = frozenset({"sheet_name", "position", "column_widths", "units",
                             "hidden", "hidden_columns"})
#: Where a book sheet lands relative to the item sheets.
BOOK_POSITIONS = ("before_items", "after_items")
#: Excel's own sheet-title limit and the characters it refuses in one.
_SHEET_NAME_MAX = 31
_SHEET_NAME_BAD_CHARS = frozenset("[]:*?/\\")
_COLUMN_LETTER_RE = re.compile(r"^[A-Z]{1,3}$")
#: Excel's rightmost real column, XFD. `_COLUMN_LETTER_RE` alone accepts any
#: 1-3 letter string (up to "ZZZ" = 18278), which overshoots XFD (16384) --
#: _column_index + this bound close that gap.
_MAX_COLUMN_INDEX = 16384


def _column_index(col: str) -> int:
    """Column letter(s) -> 1-based index (A=1, Z=26, AA=27, ..., XFD=16384).

    A pure reimplementation of ``openpyxl.utils.column_index_from_string``'s
    bijective base-26 conversion -- this module stays free of an openpyxl
    import (see module docstring); only called on a string that already
    matched `_COLUMN_LETTER_RE`, so every character is an uppercase letter.
    """
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


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


def _check_entry(entry: dict, where: str, recipes_doc: dict, units: dict) -> None:
    """The checks a single recipe/book-sheet units[] entry must pass."""
    if not isinstance(entry, dict):
        raise RecipeError(f"{where}: must be a mapping, got {entry!r}")
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


def _check_sheet_name(name, where: str) -> None:
    """A book sheet_name must be a legal Excel worksheet title: a non-empty
    string of at most 31 characters, free of the handful of characters
    Excel refuses in a sheet name ([ ] : * ? / \\)."""
    if not isinstance(name, str) or not name:
        raise RecipeError(f"{where}: sheet_name must be a non-empty string")
    if len(name) > _SHEET_NAME_MAX:
        raise RecipeError(
            f"{where}: sheet_name {name!r} is {len(name)} characters, longer "
            f"than Excel's {_SHEET_NAME_MAX}-character limit")
    bad = sorted(_SHEET_NAME_BAD_CHARS & set(name))
    if bad:
        raise RecipeError(
            f"{where}: sheet_name {name!r} contains {bad}, which Excel does "
            "not allow in a sheet name")


def _check_column_widths(widths, where: str) -> None:
    if widths is None:
        return
    if not isinstance(widths, dict):
        raise RecipeError(f"{where}: column_widths must be a mapping, got {widths!r}")
    for col, width in widths.items():
        if not isinstance(col, str) or not _COLUMN_LETTER_RE.match(col):
            raise RecipeError(
                f"{where}: column_widths key {col!r} must be a column letter (A-ZZZ)")
        if _column_index(col) > _MAX_COLUMN_INDEX:
            raise RecipeError(
                f"{where}: column_widths key {col!r} is past Excel's last column, XFD")
        if isinstance(width, bool) or not isinstance(width, (int, float)):
            raise RecipeError(
                f"{where}: column_widths[{col!r}] must be a number, got {width!r}")


def _check_hidden_columns(value, where: str) -> None:
    if not isinstance(value, list) or not all(
            isinstance(c, str) and _COLUMN_LETTER_RE.match(c) for c in value):
        raise RecipeError(f"{where}: hidden_columns must be a list of column letters, got {value!r}")
    for col in value:
        if _column_index(col) > _MAX_COLUMN_INDEX:
            raise RecipeError(
                f"{where}: hidden_columns entry {col!r} is past Excel's last column, XFD")


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
            _check_entry(entry, f"recipes.{rname}[{i}]", recipes_doc, units)
        if "hidden_columns" in recipe:
            _check_hidden_columns(recipe["hidden_columns"], f"recipes.{rname}")

    book = recipes_doc.get("book")
    if book is None:
        return
    if "cover" in (recipes_doc.get("recipes") or {}):
        raise RecipeError("book: a pack declares either recipes.cover or book, not both")
    if not isinstance(book, list) or not book:
        raise RecipeError("book: must be a non-empty list of sheets")
    names = set()
    for i, sheet in enumerate(book):
        where = f"book[{i}]"
        if not isinstance(sheet, dict):
            raise RecipeError(f"{where}: must be a mapping")
        unknown = set(sheet) - BOOK_SHEET_KEYS
        if unknown:
            raise RecipeError(f"{where}: unknown keys {sorted(unknown)}")
        name = sheet.get("sheet_name")
        _check_sheet_name(name, where)
        # Excel (and openpyxl) treat sheet names case-insensitively -- 'Front'
        # and 'FRONT' are the same sheet to it, so they have to be to us too.
        if name.casefold() in names:
            raise RecipeError(f"{where}: needs a unique sheet_name")
        names.add(name.casefold())
        if sheet.get("position") not in BOOK_POSITIONS:
            raise RecipeError(f"{where}: position must be one of {list(BOOK_POSITIONS)}")
        _check_column_widths(sheet.get("column_widths"), where)
        if "hidden_columns" in sheet:
            _check_hidden_columns(sheet["hidden_columns"], where)
        if "hidden" in sheet and not isinstance(sheet["hidden"], bool):
            raise RecipeError(f"{where}: hidden must be true or false")
        units_list = sheet.get("units", [])
        if not isinstance(units_list, list):
            raise RecipeError(f"{where}.units: must be a list, got {units_list!r}")
        for j, entry in enumerate(units_list):
            _check_entry(entry, f"{where}.units[{j}]", recipes_doc, units)
            if "sheet" in entry:
                raise RecipeError(f"{where}.units[{j}]: 'sheet' is not allowed on a book sheet")
