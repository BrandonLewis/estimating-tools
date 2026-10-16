"""Generator: render an org-agnostic estimate workbook from the estimate_spec.

Consumes tokens.yaml + units.yaml + recipes.yaml + a validated estimate config
and writes an .xlsx via openpyxl. See README.md for the layer model and the
placeholder mini-language the Resolver implements.

Sheets are laid out first (collecting each sheet's published `exports:`) and
every cell is resolved afterwards, in `write()`. That ordering is what lets
`{ref:SHEET!NAME}` -- the opt-in cross-sheet form of `{ref:NAME}` -- name a
sheet that had not yet been laid out when the referring cell was placed.
"""
from __future__ import annotations

import argparse
import re
import sys
from importlib.metadata import entry_points
from pathlib import Path

import openpyxl
import yaml
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import column_index_from_string, get_column_letter

from estimating_tools.estimate_spec import recipe as R

# Entry-point group a consumer package registers a pre-render config check under
# (#256). Each entry point resolves to `check(config: dict) -> Iterable[str]`.
CONFIG_CHECK_GROUP = "estimating_tools.estimate_spec.config_check"


def run_config_checks(config):
    """Run consumer-registered pre-render config checks (#256).

    A consumer whose policy lives in its own repo (e.g. "every sheet must carry
    a FUEL cost block, else it silently books $0") registers a check under the
    CONFIG_CHECK_GROUP entry-point group. Each check is `check(config)->iterable
    of finding strings`. Advisory ONLY: findings are returned prefixed with the
    check name; a check that raises is reported as a finding, never propagated —
    a broken or absent lint must not break the build. Returns [] when none are
    registered."""
    findings: list[str] = []
    try:
        eps = entry_points(group=CONFIG_CHECK_GROUP)
    except Exception:
        return findings
    for ep in eps:
        try:
            check = ep.load()
            for finding in (check(config) or []):
                findings.append(f"{ep.name}: {finding}")
        except Exception as exc:  # a consumer's check must never break the build
            findings.append(f"{ep.name}: check errored: {exc}")
    return findings

# =============================================================================
# Resolver — substitutes the placeholder mini-language (units.yaml header).
# =============================================================================

_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
_LANDMARK = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*([+-]\s*\d+)?$")
_QUOTED_SHEET = re.compile(r"^'(.*)'$", re.DOTALL)

# The separator that opts a {ref:} into another sheet's namespace. A ref key
# is `INSTANCE.EXPORT` (instance keys may carry [brackets]); none has ever
# contained this character, which is what keeps the syntax purely additive.
SHEET_SEP = "!"
# Excel quotes a sheet name that needs it, and escapes an apostrophe inside
# those quotes by doubling it. `sheet_qualified` doubles; `split_sheet_ref`
# undoubles.
QUOTE = "'"


def quoted_sheet(sheet):
    """A sheet name as a formula must quote it: `Bob's Sheet` -> `'Bob''s Sheet'`.

    Excel escapes an apostrophe inside those quotes by doubling it; anything
    that builds an address out of a sheet name goes through here, so nothing
    can emit the half-escaped form that only fails when the file is opened.
    """
    return f"{QUOTE}{sheet.replace(QUOTE, QUOTE * 2)}{QUOTE}"


def sheet_qualified(sheet, addr):
    """An address as another sheet must spell it: `'Sheet'!$A$1`.

    One spelling for both cross-sheet forms (a declared global with
    `qualify: sheet`, and a `{ref:SHEET!NAME}`), so a pack never has to care
    which of the two produced the address it is reading.

    An apostrophe in the sheet name is doubled -- Excel's own escaping inside
    a quoted sheet reference, and the exact inverse of what `split_sheet_ref`
    unescapes. `Bob's Sheet` therefore round-trips, instead of rendering an
    address that fails only when someone opens the workbook.
    """
    return f"{quoted_sheet(sheet)}{SHEET_SEP}{addr}"


def split_sheet_ref(key):
    """`SHEET!NAME` -> (sheet, name); a key without a separator -> (None, key).

    The split is on the LAST separator: an export name never contains one,
    while a sheet name legally may. The sheet may be written bare or quoted
    (`'Crew Rates'!x`), the way the workbook itself spells it; inside quotes an
    apostrophe is doubled, the inverse of `sheet_qualified`.
    """
    if SHEET_SEP not in key:
        return None, key
    sheet, _, name = key.rpartition(SHEET_SEP)
    m = _QUOTED_SHEET.match(sheet)
    if m:
        sheet = m.group(1).replace(QUOTE * 2, QUOTE)
    return sheet, name


class CrossSheetRefError(R.RecipeError):
    """A `{ref:SHEET!NAME}` names an export no sheet in the workbook published.

    Its own class so the `optional:` escape hatch in `write()` cannot swallow
    it: an unresolvable cross-sheet reference is always an error, never a
    blank cell and never a silent zero.
    """


class Resolver:
    """Resolve {placeholders} in a cell value/formula for one render context.

    Refs always expand to full cell addresses; {r} and {row:NAME} expand to
    integers that the author prefixes with a literal column letter.

    `exports` is the referring sheet's own namespace and is consulted first,
    so every ref a pack can write today resolves exactly as it always has.
    `book_exports` (sheet -> that sheet's namespace) is the whole workbook's
    and backs the opt-in `{ref:SHEET!NAME}` form; `where` and `pack` only
    name the site in an error message.
    """

    def __init__(self, *, params=None, item=None, row=None, landmarks=None,
                 exports=None, globals=None, book_exports=None, where="", pack=None):
        self.params = params or {}
        self.item = item
        self.row = row
        self.book_exports = book_exports
        self.where = where
        self.pack = pack
        self.landmarks = landmarks or {}
        self.exports = exports or {}
        self.globals = dict(globals or {})

    def resolve(self, text):
        """Resolve all placeholders. Non-strings pass through untouched.

        Runs to a fixed point so a parameter that itself contains placeholders
        (e.g. driver = "={ref:takeoff.ftg_cy}") is fully expanded.
        """
        if not isinstance(text, str):
            return text
        cur = text
        for _ in range(10):
            if "{" not in cur:
                break
            nxt = _PLACEHOLDER.sub(self._sub, cur)
            if nxt == cur:
                break
            cur = nxt
        return cur

    def _sub(self, match):
        token = match.group(1).strip()

        if token.startswith("p."):
            name = token[2:]
            if name not in self.params:
                raise KeyError(f"unknown parameter {name!r}")
            return str(self.params[name])

        if token == "it":
            return str(self.item)
        if token.startswith("it."):
            return str(self.item[token[3:]])

        if token == "r" or token.startswith("r-") or token.startswith("r+"):
            if self.row is None:
                raise ValueError("current row {r} used but not set")
            offset = token[1:]
            return str(self.row + (int(offset) if offset else 0))

        if token.startswith("row:"):
            return str(self._landmark(token[4:]))

        if token.startswith("ref:"):
            key = token[4:]
            if key in self.exports:          # this sheet's namespace always wins
                return str(self.exports[key])
            if SHEET_SEP in key:             # opt-in: another sheet's namespace
                return self._cross_sheet(key)
            raise KeyError(f"unknown ref {key!r}")

        if token in self.globals:
            value = self.globals[token]
            if value is None:
                raise ValueError(f"{{{token}}} used but not set")
            return value

        raise ValueError(f"unresolved placeholder {{{token}}}")

    def _cross_sheet(self, key):
        """`{ref:SHEET!NAME}` -> `'SHEET'!<that sheet's exported address>`.

        Resolved against the WHOLE workbook's exports, which is why the
        target sheet may be laid out before or after the referring one: every
        cell is resolved in one pass after all layout is done. Anything that
        does not resolve names itself, its site and its pack and stops the
        build -- see CrossSheetRefError.
        """
        sheet, name = split_sheet_ref(key)
        ref = f"{{ref:{key}}}"
        site = f"{self.where}: " if self.where else ""
        pack = f" in pack {self.pack!r}" if self.pack else ""
        if self.book_exports is None:
            raise CrossSheetRefError(
                f"{site}{ref} reaches across sheets, but no other sheet is in "
                "scope here. A cross-sheet ref belongs in a cell, where it is "
                "resolved against the whole workbook; a unit's `exports:` "
                "template publishes an address on its OWN sheet and cannot "
                "reach across")
        if sheet not in self.book_exports:
            raise CrossSheetRefError(
                f"{site}{ref} names sheet {sheet!r}, which this estimate does "
                f"not lay out{pack} (sheets: {sorted(self.book_exports)}). A "
                "cross-sheet ref names a sheet by the name the estimate config "
                "gives it; for one address published once and read from "
                "everywhere, declare it under `globals:` with scope: workbook "
                "instead of naming the sheet here"
            )
        published = self.book_exports[sheet]
        if name not in published:
            raise CrossSheetRefError(
                f"{site}{ref}: sheet {sheet!r} publishes no export {name!r}"
                f"{pack} (it offers: {sorted(published)}). An export is "
                "published as `INSTANCE.NAME`, where INSTANCE is the recipe "
                "entry's `key:` (the unit name when it has none) and NAME is a "
                "key under that unit's `exports:`"
            )
        return sheet_qualified(sheet, published[name])

    def _landmark(self, expr):
        m = _LANDMARK.match(expr)
        if not m:
            raise ValueError(f"malformed landmark {expr!r}")
        name, offset = m.group(1), m.group(2)
        if name not in self.landmarks:
            raise ValueError(f"unknown landmark {name!r}")
        val = self.landmarks[name]
        if offset:
            val += int(offset.replace(" ", ""))
        return val


# =============================================================================
# StyleFactory — turns a composite style name (+ overrides) into openpyxl style.
# =============================================================================

_RESERVED_CELL_KEYS = {"value", "formula", "style", "optional", "if_ref", "if_param"}


class StyleFactory:
    def __init__(self, tokens):
        self.base = tokens.get("meta", {}).get("base_font", {"name": "Arial", "size": 10})
        self.fills = tokens.get("fills", {})
        self.font_colors = tokens.get("font_colors", {})
        self.font_sizes = tokens.get("font_sizes", {})
        self.borders = tokens.get("borders", {})
        self.number_formats = tokens.get("number_formats", {})
        self.alignments = tokens.get("alignments", {})
        self.styles = tokens.get("styles", {})

    @staticmethod
    def _argb(hex6):
        h = hex6.lstrip("#")
        return h if len(h) == 8 else "FF" + h

    def _size(self, value):
        return self.font_sizes.get(value, value) if isinstance(value, str) else value

    def fill_for(self, token):
        return PatternFill("solid", fgColor=self._argb(self.fills[token]))

    def apply(self, cell, style_name, overrides=None):
        style = dict(self.styles.get(style_name, {}))
        if overrides:
            style.update(overrides)

        color = self._argb(self.font_colors[style["font_color"]]) if "font_color" in style else None
        cell.font = Font(
            name=self.base["name"],
            size=self._size(style.get("size", self.base["size"])),
            bold=bool(style.get("bold", False)),
            italic=bool(style.get("italic", False)),
            color=color,
        )
        if "fill" in style:
            cell.fill = self.fill_for(style["fill"])
        if "border" in style:
            b = self.borders[style["border"]]
            side = Side(style=b["style"])
            cell.border = Border(**{s: side for s in b["sides"]})
        if "align" in style:
            cell.alignment = Alignment(**self.alignments[style["align"]])
        if "number_format" in style:
            nf = style["number_format"]
            cell.number_format = self.number_formats.get(nf, nf)


def _coerce(text):
    """Resolved string -> formula / date / number / text for openpyxl."""
    if not isinstance(text, str):
        return text
    if text.startswith("="):
        return text
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        from datetime import date
        return date(int(m[1]), int(m[2]), int(m[3]))
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    try:
        return float(text)
    except ValueError:
        return text


# =============================================================================
# EstimateBuilder — lays out every sheet (collecting exports), then resolves.
# =============================================================================

class EstimateBuilder:
    def __init__(self, config, pack=None):
        from estimating_tools.estimate_spec.format_pack import bundled_pack

        self.config = config
        self.pack = pack or bundled_pack()
        self.tokens = self.pack.tokens
        self.units = self.pack.units
        self.recipes_doc = self.pack.recipes
        self.recipes = self.recipes_doc["recipes"]
        R.validate_recipes(self.recipes_doc, self.units)
        self.globals_decl = self.recipes_doc.get("globals") or {}
        self.sheet_globals = {}       # sheet -> {name: addr}   (scope: sheet)
        self.book_globals = {}        # name -> addr            (scope: workbook; promoted once)
        self.book_global_origin = {}  # name -> (sheet, unit/key) that promoted it
        self.fill_span = {}           # sheet -> (first col, last col)
        self.styles = StyleFactory(self.tokens)

        self.wb = openpyxl.Workbook()
        self.placements = []          # deferred cell writes
        self.region_fills = []        # (sheet, r1, r2, c1, c2, fill_token)
        self.boxes = []               # (sheet, r1, r2, c1, c2) thick perimeter
        self.merges = []              # (sheet, "A1:F1")
        self.exports = {}             # sheet_name -> {ref_key: address}

    # ---- layout helpers ----------------------------------------------------
    def _exp(self, key, addr):
        self.cur_exports[key] = addr

    def _place_row(self, cells, sheet, row, params, item, landmarks, merge, fill_row,
                   merge_down=0, unit=None):
        for col, cell in cells.items():
            raw = cell["formula"] if "formula" in cell else cell.get("value")
            overrides = {k: v for k, v in cell.items() if k not in _RESERVED_CELL_KEYS}
            self.placements.append(dict(
                sheet=sheet, row=row, col=col, raw=raw, unit=unit,
                style=cell.get("style", "label"), overrides=overrides,
                optional=cell.get("optional", False), if_ref=cell.get("if_ref"),
                if_param=cell.get("if_param"),
                params=params, item=item, landmarks=landmarks,
                globals=dict(self.sheet_globals.get(sheet, {})),   # snapshot, as item_qty was
            ))
        if merge:
            c1, c2 = merge.split(":")
            self.merges.append((sheet, f"{c1}{row}:{c2}{row + merge_down}"))
        if fill_row:
            self.region_fills.append((sheet, row, row, *self._fill_cols(sheet), fill_row))

    def _add_box(self, sheet, r1, r2, span):
        c1, c2 = span.split(":")
        self.boxes.append((sheet, r1, r2, c1, c2))

    def _fill_cols(self, sheet):
        # A `sheet:` target carries no recipe widths, so it keeps this A-H fallback.
        return self.fill_span.get(sheet, ("A", "H"))    # engine fallback for recipes without widths

    def _recipe(self, name, *, item=None):
        """Resolve a named recipe from the pack, or fail loudly naming what's
        missing: the item (when one is known), the recipe name, the pack, and
        what the pack does offer -- never a bare KeyError."""
        try:
            return self.recipes[name]
        except KeyError:
            where = f"item {item['item_no']} ({item['sheet']})" if item is not None else "recipes.cover"
            raise R.RecipeError(
                f"{where}: recipe {name!r} is not in pack {self.pack.name!r} "
                f"(has: {sorted(self.recipes)})"
            ) from None

    def _anchored(self, entry):
        return bool((self.units.get(entry["unit"]) or {}).get("anchor"))

    def _target(self, name):
        """The sheet an entry writes to, created on first use."""
        if name not in self.wb.sheetnames:
            self.wb.create_sheet(name)
        self.exports.setdefault(name, {})
        return name

    def _promote_globals(self, namespace, sheet):
        """Publish declared globals whose export belongs to the instance just laid out."""
        for name, g in self.globals_decl.items():
            if g["export"].split(".", 1)[0] != namespace:
                continue
            addr = (self.cur_exports.get(g["export"], g["default"]) if "default" in g
                    else self.cur_exports[g["export"]])
            if g.get("qualify") == "sheet":
                addr = sheet_qualified(sheet, addr)
            if g.get("scope", "sheet") == "workbook":
                if name in self.book_global_origin:
                    prev_sheet, prev_ns = self.book_global_origin[name]
                    raise R.RecipeError(
                        f"globals.{name}: promoted twice at workbook scope -- "
                        f"first by {prev_ns!r} on sheet {prev_sheet!r}, again by "
                        f"{namespace!r} on sheet {sheet!r}, in pack {self.pack.name!r} "
                        "(a workbook-scope global may be promoted from only one sheet/unit)"
                    )
                self.book_global_origin[name] = (sheet, namespace)
                self.book_globals[name] = addr
            else:
                self.sheet_globals.setdefault(sheet, {})[name] = addr

    def _param_list(self, params, ref):
        return params.get(ref.split(".", 1)[1], []) or []

    @staticmethod
    def _apply_defaults(udef, params):
        merged = dict(params)
        for name, spec in (udef.get("params") or {}).items():
            if isinstance(spec, dict) and "default" in spec and name not in merged:
                merged[name] = spec["default"]
        return merged

    @staticmethod
    def _truthy(params, ref):
        if isinstance(ref, str) and ref.startswith("p."):
            return bool(params.get(ref[2:]))
        return True

    def layout_unit(self, unit_name, sheet, cursor, params, instance_key=None):
        udef = self.units[unit_name]
        params = self._apply_defaults(udef, params)
        landmarks = {}
        anchor = udef.get("anchor")
        local = [anchor["row"]] if anchor else cursor   # anchored units use their own cursor
        start = local[0]

        for rowdef in udef.get("rows", []):
            if "blank" in rowdef:
                local[0] += rowdef["blank"]
                continue
            if "repeat" in rowdef:
                items = self._param_list(params, rowdef["repeat"])
                first = last = None
                for it in items:
                    r = local[0]
                    first = r if first is None else first
                    last = r
                    self._place_row(rowdef["cells"], sheet, r, params, it, landmarks,
                                    rowdef.get("merge"), rowdef.get("fill_row"),
                                    rowdef.get("merge_down", 0), unit=unit_name)
                    local[0] += 1
                if first is not None:
                    if "mark_first" in rowdef:
                        landmarks[rowdef["mark_first"]] = first
                    if "mark_last" in rowdef:
                        landmarks[rowdef["mark_last"]] = last
                continue
            if "when" in rowdef and not self._truthy(params, rowdef["when"]):
                continue
            r = local[0]
            self._place_row(rowdef["cells"], sheet, r, params, None, landmarks,
                            rowdef.get("merge"), rowdef.get("fill_row"),
                            rowdef.get("merge_down", 0), unit=unit_name)
            if "mark" in rowdef:
                landmarks[rowdef["mark"]] = r
            if rowdef.get("box"):
                self._add_box(sheet, r, r, rowdef["box"])
            local[0] += 1

        end = local[0] - 1
        if udef.get("fill_region"):
            self.region_fills.append((sheet, start, end, *self._fill_cols(sheet), udef["fill_region"]))
        if udef.get("box_region"):
            self._add_box(sheet, start, end, udef["box_region"])

        # publish exports under the instance key (singleton = unit name)
        ekey = instance_key or unit_name
        exp_resolver = Resolver(landmarks=landmarks, pack=self.pack.name,
                                where=f"unit {unit_name!r} on sheet {sheet!r} (exports:)")
        for name, tmpl in (udef.get("exports") or {}).items():
            try:
                self.cur_exports[f"{ekey}.{name}"] = exp_resolver.resolve(tmpl)
            except CrossSheetRefError:
                raise      # the one other broad catch: never swallow this one either
            except (KeyError, ValueError):
                pass  # landmark omitted by a `when:` row -> export simply not published
        return landmarks, (start, end)

    # ---- per-sheet build ---------------------------------------------------
    def build_item_sheet(self, item):
        sheet = item["sheet"]
        ws = self.wb.create_sheet(sheet)
        self.cur_exports = self.exports.setdefault(sheet, {})
        recipe = self._recipe(item["recipe"], item=item)
        for col, width in (recipe.get("column_widths") or {}).items():
            ws.column_dimensions[col].width = width

        cols = sorted(recipe.get("column_widths") or {}, key=column_index_from_string)
        if cols:
            self.fill_span[sheet] = (cols[0], cols[-1])

        cursor = [1]
        spans = {}
        scopes = {"item": item, "config": self.config, "span": spans,
                  "exports": self.cur_exports}
        for entry in recipe["units"]:
            if R.is_active(entry, scopes):
                unit = R.concrete_unit(entry, scopes, self.recipes_doc)
                target = self._target(entry.get("sheet", sheet))
                # A unit placed on another sheet publishes into that sheet's
                # namespace (and globals promote from it), never the host's.
                self.cur_exports = self.exports[target]
                try:
                    for key, params in R.instances(entry, scopes):
                        _, span = self.layout_unit(unit, target, cursor, params, instance_key=key)
                        first = spans.get(entry["unit"], (None, None))[0]
                        spans[entry["unit"]] = (span[0] if first is None else first, span[1])
                        self._promote_globals(key or unit, target)
                finally:
                    self.cur_exports = self.exports[sheet]
            if not self._anchored(entry):
                cursor[0] += 1             # one blank row between sections (visual spacing)

    def build_cover(self):
        cover = self._recipe("cover")
        sheet = cover["sheet_name"]
        self.cur_exports = self.exports.setdefault(sheet, {})
        if len(cover["units"]) != 1:
            raise R.RecipeError("recipes.cover: exactly one unit is supported")
        entry = cover["units"][0]
        items = []
        for it in self.config["items"]:
            if it.get("in_summary") is False:
                # A shared-cost sheet: the items that pay for it reach its
                # TOTAL with a cross-sheet ref, so listing it here too would
                # carry every dollar on it into the bid twice. Still rendered
                # and still publishes its total -- only the summary skips it.
                continue
            isheet = it["sheet"]
            grand = self.exports[isheet][cover["item_total_export"]]
            items.append({"sheet_ref": quoted_sheet(isheet),
                          "total_export": "=" + sheet_qualified(isheet, grand)})
        scopes = {"item": {}, "config": self.config, "span": {}, "exports": self.cur_exports}
        (_, params), = R.instances(entry, scopes)
        params["items"] = items                   # engine-supplied: cross-sheet totals
        self.layout_unit(entry["unit"], sheet, [1], params)

    # ---- resolve + write ---------------------------------------------------
    def _ref_published(self, key, sheet):
        """Did `key` get published? Backs `if_ref:`, which takes both forms.

        A bare key asks the referring sheet's own namespace, exactly as it
        always has. A `SHEET!NAME` key asks that sheet's -- the one way a pack
        may deliberately skip a cell whose cross-sheet target is absent,
        instead of having the error swallowed by `optional:`.
        """
        if key in self.exports[sheet]:
            return True
        target, name = split_sheet_ref(key)
        return target is not None and name in self.exports.get(target, {})

    def write(self):
        # region fills first (so cells with no fill keep the band colour)
        for sheet, r1, r2, c1, c2, token in self.region_fills:
            ws = self.wb[sheet]
            fill = self.styles.fill_for(token)
            for r in range(r1, r2 + 1):
                for c in range(column_index_from_string(c1), column_index_from_string(c2) + 1):
                    ws.cell(r, c).fill = fill

        # Every placement is resolved here, after the LAST sheet has been laid
        # out, so `self.exports` is the finished workbook's namespace: a
        # {ref:SHEET!NAME} reads the same whether its target sheet came before
        # or after the referring one. One pass, no ordering rule for a pack
        # author to remember.
        for p in self.placements:
            res = Resolver(params=p["params"], item=p["item"], row=p["row"],
                           landmarks=p["landmarks"], exports=self.exports[p["sheet"]],
                           globals={**{n: None for n in self.globals_decl},
                                    **self.book_globals, **p["globals"]},
                           book_exports=self.exports, pack=self.pack.name,
                           where=(f"sheet {p['sheet']!r} cell {p['col']}{p['row']} "
                                  f"(unit {p['unit']!r})"))
            if p["if_ref"] and not self._ref_published(p["if_ref"], p["sheet"]):
                continue
            if p["if_param"] and p["params"].get(p["if_param"]) is None:
                continue   # render when the param is present (incl. 0); skip only when absent
            try:
                value = res.resolve(p["raw"])
            except CrossSheetRefError:
                raise      # never optional: an unresolvable cross-sheet ref stops the build
            except (KeyError, ValueError):
                if p["optional"]:
                    continue
                raise
            value = _coerce(value)
            if value == "" or value is None:
                if p["optional"]:
                    continue
            ws = self.wb[p["sheet"]]
            cell = ws[f"{p['col']}{p['row']}"]
            cell.value = value
            self.styles.apply(cell, p["style"], p["overrides"])

        # thick perimeter boxes, merged with each cell's existing borders
        thick = Side(style="thick")
        for sheet, r1, r2, c1, c2 in self.boxes:
            ws = self.wb[sheet]
            ci1, ci2 = column_index_from_string(c1), column_index_from_string(c2)
            for r in range(r1, r2 + 1):
                for ci in range(ci1, ci2 + 1):
                    b = ws.cell(r, ci).border
                    ws.cell(r, ci).border = Border(
                        left=thick if ci == ci1 else b.left,
                        right=thick if ci == ci2 else b.right,
                        top=thick if r == r1 else b.top,
                        bottom=thick if r == r2 else b.bottom,
                    )

        for sheet, rng in self.merges:
            try:
                self.wb[sheet].merge_cells(rng)
            except Exception:
                pass

    def run(self):
        self.wb.active.title = self._recipe("cover")["sheet_name"]   # placeholder; cover laid out last
        for item in self.config["items"]:
            self.build_item_sheet(item)
        self.build_cover()
        self.write()
        return self.wb


def generate(config, pack=None, *, stamp=True):
    """Render an estimate workbook (openpyxl Workbook) from a config in a format pack.

    `pack` defaults to the bundled pack. With `stamp`, the workbook carries the
    pack's name and version as the custom property `estimate_format`, so any
    .xlsx traces to the format that produced it.
    """
    from openpyxl.packaging.custom import StringProperty

    from estimating_tools.estimate_spec.validate import validate_cross_references
    validate_cross_references(config)
    builder = EstimateBuilder(config, pack)
    wb = builder.run()
    if stamp:
        wb.custom_doc_props.append(StringProperty(
            name="estimate_format", value=f"{builder.pack.name} {builder.pack.version}"))
    return wb


def build(config_path, out_path=None, pack=None, *, stamp=True, lint=True):
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if lint:
        for finding in run_config_checks(config):
            print(f"lint: {finding}", file=sys.stderr)
    wb = generate(config, pack, stamp=stamp)
    out = out_path or config.get("output") or (Path(config_path).with_suffix(".xlsx"))
    wb.save(out)
    return out


def main(argv=None):
    from estimating_tools.estimate_spec.format_pack import load_pack

    ap = argparse.ArgumentParser(description="Render an estimate workbook from an estimate_spec config.")
    ap.add_argument("config", help="estimate config YAML")
    ap.add_argument("-o", "--output", help="output .xlsx path")
    ap.add_argument("--format", help="format pack directory (default: the bundled pack)")
    ap.add_argument("--no-stamp", action="store_true", help="omit the estimate_format property")
    ap.add_argument("--no-lint", action="store_true",
                    help="skip consumer-registered pre-render config checks (#256)")
    args = ap.parse_args(argv)
    pack = load_pack(args.format) if args.format else None
    print("WROTE:", build(args.config, args.output, pack, stamp=not args.no_stamp, lint=not args.no_lint))
    return 0


if __name__ == "__main__":
    sys.exit(main())
