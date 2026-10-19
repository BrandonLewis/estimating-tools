"""A format pack's `layout_map:` -- where Estimate Navigator finds things.

`validate` checks the section when the pack loads. `resolve` turns it into
workbook-scoped defined names once the workbook is laid out: one name per
table (`est.index`), one per table column (`est.index.cost`) and one per
named cell (`est.direct_total`). Defined names, not cell addresses, because
Excel moves a defined name when the estimator inserts rows.

Pure: no openpyxl here. build.py writes what `resolve` returns.
"""
from __future__ import annotations

import re

LAYOUT_VERSION = 1
TEMPLATES_SHEET = "_templates"
#: The tables a map may declare, and exactly the columns each must name.
TABLE_COLUMNS = {
    "index": ("item_no", "descr", "cost", "link"),
    "checks": ("rule_no", "rule", "item", "status"),
    "codes": ("code", "descr", "listed"),
}
CELLS = ("direct_total",)
TAGS = ("kind", "code_chain")
BLOCK_KEYS = ("item", "head", "body", "end", "sub", "code_col")
TEMPLATE_ROWS = ("crew", "line")
_KEYS = {"version", "tables", "cells", "tags", "blocks", "templates"}
_ROW_MODES = ("each", "after", "span")
_COL = re.compile(r"^[A-Z]{1,3}$")
_ROW_NUMS = re.compile(r"\$?[A-Z]{1,3}\$?([1-9][0-9]*)")


class LayoutMapError(ValueError):
    """A `layout_map:` section that cannot be used."""


def _need(ok: bool, where: str, msg: str) -> None:
    if not ok:
        raise LayoutMapError(f"{where}: layout_map{msg}")


def _is_col(v) -> bool:
    return isinstance(v, str) and bool(_COL.match(v))


def _col_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def validate(raw, where: str) -> dict:
    """`raw` unchanged when it is a usable map; LayoutMapError naming the defect otherwise."""
    _need(isinstance(raw, dict), where, " must be a mapping")
    unknown = sorted(set(raw) - _KEYS)
    _need(not unknown, where, f": unknown keys {unknown}")
    _need(type(raw.get("version")) is int and raw.get("version") == LAYOUT_VERSION,
          where, f".version must be {LAYOUT_VERSION}")

    tables = raw.get("tables")
    _need(isinstance(tables, dict) and "index" in tables, where, ".tables must declare index")
    for name, t in tables.items():
        at = f".tables.{name}"
        _need(name in TABLE_COLUMNS, where, f"{at}: unknown table (known: {sorted(TABLE_COLUMNS)})")
        _need(isinstance(t, dict) and set(t) == {"sheet", "rows", "columns"},
              where, f"{at} needs exactly sheet, rows and columns")
        _need(isinstance(t["sheet"], str) and bool(t["sheet"]), where, f"{at}.sheet must be a sheet name")
        rows = t["rows"]
        _need(isinstance(rows, dict) and len(set(rows) & set(_ROW_MODES)) == 1,
              where, f"{at}.rows needs exactly one of each, after, span")
        _need(set(rows) <= {*_ROW_MODES, "skip"}, where, f"{at}.rows: unknown keys")
        _need("skip" not in rows or ("after" in rows and type(rows["skip"]) is int and rows["skip"] >= 0),
              where, f"{at}.rows.skip goes with after and is a whole number >= 0")
        for mode in _ROW_MODES:
            if mode in rows:
                _need(isinstance(rows[mode], str) and bool(rows[mode]), where, f"{at}.rows.{mode} must be an export key")
        cols = t["columns"]
        _need(isinstance(cols, dict) and set(cols) == set(TABLE_COLUMNS[name]),
              where, f"{at}.columns must be exactly {list(TABLE_COLUMNS[name])}")
        for c, letter in cols.items():
            _need(_is_col(letter), where, f"{at}.columns.{c} must be a column letter")

    cells = raw.get("cells") or {}
    _need(isinstance(cells, dict) and set(cells) <= set(CELLS), where, f".cells may name only {list(CELLS)}")
    for c, ref in cells.items():
        _need(isinstance(ref, str) and "!" in ref, where, f".cells.{c} must be SHEET!EXPORT")

    tags = raw.get("tags")
    _need(isinstance(tags, dict) and set(tags) == set(TAGS) and all(_is_col(v) for v in tags.values()),
          where, f".tags must map exactly {list(TAGS)} to column letters")

    blocks = raw.get("blocks")
    _need(isinstance(blocks, dict) and set(blocks) == set(BLOCK_KEYS)
          and all(isinstance(blocks[k], str) and blocks[k] for k in ("item", "head", "end", "sub"))
          and isinstance(blocks["body"], list) and bool(blocks["body"])
          and all(isinstance(k, str) and k for k in blocks["body"])
          and _is_col(blocks["code_col"]),
          where, f".blocks must map exactly {list(BLOCK_KEYS)} "
                 "(body a non-empty list of non-empty kinds, code_col a letter)")

    tpl = raw.get("templates")
    if tpl is not None:
        _need(isinstance(tpl, dict) and set(tpl) == {"item", "rows", "clear"},
              where, ".templates needs exactly item, rows and clear")
        item = tpl["item"]
        _need(isinstance(item, dict) and isinstance(item.get("recipe"), str) and item.get("recipe"),
              where, ".templates.item must be an item with a recipe")
        _need("sheet" not in item, where, f".templates.item must not name a sheet (it is always {TEMPLATES_SHEET})")
        _need(isinstance(tpl["rows"], dict) and set(tpl["rows"]) == set(TEMPLATE_ROWS)
              and all(isinstance(v, str) and v for v in tpl["rows"].values()),
              where, f".templates.rows must map exactly {list(TEMPLATE_ROWS)} to kinds")
        clear = tpl["clear"]
        _need(isinstance(clear, dict) and all(isinstance(v, list) and all(_is_col(c) for c in v)
                                              for v in clear.values()),
              where, ".templates.clear must map kinds to lists of column letters")
    return raw


def _glob(pattern: str):
    """`cs[*].bid` -> a regex where only `*` is a wildcard (brackets stay literal)."""
    return re.compile("^" + ".*".join(re.escape(p) for p in pattern.split("*")) + "$")


def _rows(addr: str) -> list[int]:
    """The row number(s) an address names, reading only the part after the
    last `!` -- a sheet name that happens to look like a column+row (`AB1`)
    must not be mistaken for one."""
    addr = addr.rsplit("!", 1)[-1]
    return [int(n) for n in _ROW_NUMS.findall(addr)]


def _rows_or_raise(name: str, key: str, addr: str) -> list[int]:
    """`_rows`, but a reference that names no row (a full-column or full-row
    reference, or a bare number) is a layout_map defect, not a crash."""
    nums = _rows(addr)
    if not nums:
        raise LayoutMapError(f"layout_map.tables.{name}: export {key!r} = {addr!r} names no row")
    return nums


def _table_rows(name: str, t: dict, exports: dict, max_row: int):
    """(first, last) rows of a table, or None when its exports are absent."""
    rows = t["rows"]
    if "each" in rows:
        pat = _glob(rows["each"])
        hit_rows = set()
        for key, addr in exports.items():
            if not pat.match(key):
                continue
            nums = _rows_or_raise(name, key, addr)
            if len(set(nums)) > 1:
                raise LayoutMapError(f"layout_map.tables.{name}: export {key!r} = {addr!r} "
                                     "is a range; each needs one row per export")
            hit_rows.add(nums[0])
        if not hit_rows:
            return None
        hits = sorted(hit_rows)
        if hits != list(range(hits[0], hits[-1] + 1)):
            raise LayoutMapError(f"layout_map.tables.{name}: rows {hits} matched by "
                                 f"{rows['each']!r} are not contiguous")
        return hits[0], hits[-1]
    key = rows.get("after") or rows["span"]
    if key not in exports:
        return None
    nums = _rows_or_raise(name, key, exports[key])
    if "span" in rows:
        return min(nums), max(nums)
    first = max(nums) + 1 + rows.get("skip", 0)
    return (first, max_row) if max_row >= first else None


def _instance_pattern(key: str) -> str:
    """A recipe entry's instance key with each `{...}` placeholder as `*`:
    `cs[{it.item_no}]` -> `cs[*]`."""
    return re.sub(r"\{[^{}]*\}", "*", key)


def fit_problems(lm: dict, recipes: dict, units: dict) -> list[str]:
    """What in `lm` the pack (its `recipes` document and `units:` map) cannot
    satisfy, read statically: each `cells:` export, and each table's `each` /
    `after` / `span` anchor, must be an export some book sheet's unit
    publishes under that instance key. Empty when the map fits.

    Static on purpose: `resolve` finds the same defects only once a spec is
    built, and a pack that INHERITS a map (`derived_from`) should be refused
    when it loads, not on an estimator's first build."""
    published: dict = {}
    for sheet in recipes.get("book") or []:
        if not isinstance(sheet, dict):
            continue
        keys = published.setdefault(sheet.get("sheet_name"), set())
        for entry in sheet.get("units") or []:
            if not isinstance(entry, dict) or "unit" not in entry:
                continue
            instance = _instance_pattern(str(entry.get("key") or entry["unit"]))
            for export in ((units.get(entry["unit"]) or {}).get("exports") or {}):
                keys.add(f"{instance}.{export}")

    problems = []

    def need(where: str, sheet: str, key: str) -> None:
        if sheet not in published:
            problems.append(f"{where}: no book sheet {sheet!r}")
        elif not any(_glob(key).match(k) for k in published[sheet]):
            problems.append(f"{where}: sheet {sheet!r} publishes no export {key!r}")

    for name, t in (lm.get("tables") or {}).items():
        for mode in _ROW_MODES:
            if mode in t["rows"]:
                need(f"tables.{name}.rows.{mode}", t["sheet"], t["rows"][mode])
    for cname, ref in (lm.get("cells") or {}).items():
        sheet, _, key = ref.rpartition("!")
        need(f"cells.{cname}", sheet, key)
    return problems


def resolve(lm: dict, exports: dict, max_rows: dict) -> tuple[dict, list]:
    """({defined name: (sheet, absolute ref)}, sorted names of the tables that resolved).

    `exports` is the builder's {sheet: {export key: address}}; `max_rows` is
    {sheet: last used row}. A table whose rows are absent (a spec with no
    cost codes and no tasks lays out no Codes rows) is left out, not an
    error: the stamp lists the tables that resolved and the add-in hides
    the tabs the others would back.
    """
    names: dict = {}
    present: list = []
    for name, t in lm["tables"].items():
        sheet = t["sheet"]
        span = _table_rows(name, t, exports.get(sheet, {}), max_rows.get(sheet, 0))
        if span is None:
            continue
        first, last = span
        letters = sorted(t["columns"].values(), key=_col_index)
        names[f"est.{name}"] = (sheet, f"${letters[0]}${first}:${letters[-1]}${last}")
        for col, letter in t["columns"].items():
            names[f"est.{name}.{col}"] = (sheet, f"${letter}${first}:${letter}${last}")
        present.append(name)
    for cname, ref in (lm.get("cells") or {}).items():
        sheet, _, key = ref.rpartition("!")
        addr = exports.get(sheet, {}).get(key)
        if addr is None:
            raise LayoutMapError(f"layout_map.cells.{cname}: sheet {sheet!r} publishes no export {key!r}")
        names[f"est.{cname}"] = (sheet, addr)
    return names, sorted(present)
