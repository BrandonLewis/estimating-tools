"""The HeavyCivil style pack: tokens.yaml + sheets.yaml, merged over the
bundled default.

Resolution: ``--style PATH`` > profile ``estimating.heavycivil_style`` > the
bundled style (the same order fieldbook's ``--format`` uses). An override
directory may hold either file, or both, and either may be partial -- it is
deep-merged over the bundled one (mappings merge, anything else replaces).

``columns.py`` fixes structure. A style may set a column's ``heading`` and
``width``, and ``show: false`` on an optional column only; a key naming a
hidden column, a required column's ``show: false``, or any unknown key is
refused naming the file and the key. Read-back ignores styling entirely.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from estimating_tools.heavycivil import columns as C

BUNDLED = Path(__file__).parent / "style"
_FILES = ("tokens.yaml", "sheets.yaml")
_TOKEN_KEYS = {"meta", "fills", "font_colors", "font_sizes", "borders", "number_formats",
               "alignments", "styles"}
_SHEET_FILE_KEYS = {"meta", "sheets", "columns"}
_SHEET_KEYS = {"tab", "tab_color", "freeze", "print"}
_PRINT_KEYS = {"orientation", "fit_width", "title_rows"}
_COLUMN_KEYS = {"heading", "width", "show"}
_BAD_TAB = re.compile(r"[\[\]:*?/\\]")
_HEX6 = re.compile(r"^[0-9A-Fa-f]{6}$")
_CELL_REF = re.compile(r"^[A-Z]{1,3}[1-9][0-9]*$")
_ORIENTATIONS = ("portrait", "landscape")
#: Excel reserves this sheet name.
_RESERVED_TABS = ("history",)

#: Every style name the sheet writers apply.
REQUIRED_STYLES = frozenset({
    "title", "subtitle", "head", "label", "label_bold", "note", "banner", "group",
    "item_text", "item_money", "item_qty", "activity_text", "activity_money",
    "activity_hours", "crew_head", "crew_money", "input_text", "input_qty", "input_money",
    "input_factor", "input_pct", "input_count", "input_flag", "export_value",
    "export_money", "calc_qty", "calc_money", "calc_rate", "calc_factor", "calc_hours", "calc_text",
    "tag", "status", "status_ok", "status_bad", "section_text", "schedule_bar", "calc_date",
    "export_date", "total_label", "total_money", "input_select", "total_hours",
    "calc_factor_fine", "export_factor_fine"})


class StyleError(ValueError):
    """A style pack is missing, malformed, or touches the fixed structure."""


@dataclass(frozen=True)
class StylePack:
    name: str
    version: str
    tokens: dict
    sheets: dict
    columns: dict
    source: str

    def tab(self, sheet_key):
        return self.sheets[sheet_key]["tab"]

    def column(self, sheet_key, column_key):
        """The merged {heading, width, show} for one column (heading defaults
        to columns.py's)."""
        spec = next(c for c in C.SHEETS[sheet_key] if c.key == column_key)
        merged = {"heading": spec.heading, "width": None, "show": True}
        merged.update(self.columns.get(sheet_key, {}).get(column_key, {}))
        return merged


def deep_merge(base, over):
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for key, value in over.items():
            out[key] = deep_merge(base[key], value) if key in base else copy.deepcopy(value)
        return out
    return copy.deepcopy(over)


def _read(path):
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise StyleError(f"{path}: not valid YAML ({exc})") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise StyleError(f"{path}: must be a mapping")
    return data


def _check_override(name, data):
    allowed = _TOKEN_KEYS if name == "tokens.yaml" else _SHEET_FILE_KEYS
    for key in data:
        if key not in allowed:
            raise StyleError(f"{name}: unknown key {key!r} (allowed: {sorted(allowed)})")
    if name != "sheets.yaml":
        return
    for sheet, conf in (data.get("sheets") or {}).items():
        if sheet not in C.SHEETS:
            raise StyleError(f"sheets.yaml: unknown sheet {sheet!r}")
        for key in conf or {}:
            if key not in _SHEET_KEYS:
                raise StyleError(f"sheets.yaml: sheets.{sheet}.{key} is not a style setting")
        for key in (conf or {}).get("print") or {}:
            if key not in _PRINT_KEYS:
                raise StyleError(f"sheets.yaml: sheets.{sheet}.print.{key} is not a print setting")
    for sheet, cols in (data.get("columns") or {}).items():
        if sheet not in C.SHEETS:
            raise StyleError(f"sheets.yaml: unknown sheet {sheet!r} under columns")
        specs = {c.key: c for c in C.SHEETS[sheet]}
        for key, conf in (cols or {}).items():
            spec = specs.get(key)
            if spec is None or spec.hidden:
                raise StyleError(f"sheets.yaml: columns.{sheet}.{key} is not a styleable column "
                                 "(structure is fixed in code)")
            for setting in conf or {}:
                if setting not in _COLUMN_KEYS:
                    raise StyleError(f"sheets.yaml: columns.{sheet}.{key}.{setting} is not a "
                                     f"column setting (allowed: {sorted(_COLUMN_KEYS)})")
            if (conf or {}).get("show") is False and not spec.optional:
                raise StyleError(f"sheets.yaml: columns.{sheet}.{key} cannot be hidden "
                                 "(only optional columns can)")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_sheet_values(key, conf):
    color = conf.get("tab_color")
    if color is not None and not (isinstance(color, str) and _HEX6.match(color)):
        raise StyleError(f"sheets.yaml: sheets.{key}.tab_color {color!r} is not a 6-digit "
                         "hex colour (e.g. 7A4E12)")
    freeze = conf.get("freeze")
    if isinstance(freeze, str):
        conf["freeze"] = freeze = freeze.upper()  # Excel references are case-insensitive
    if freeze is not None and not (isinstance(freeze, str) and _CELL_REF.match(freeze)):
        raise StyleError(f"sheets.yaml: sheets.{key}.freeze {freeze!r} is not a cell "
                         "reference (e.g. C5)")
    orientation = (conf.get("print") or {}).get("orientation")
    if orientation is not None and orientation not in _ORIENTATIONS:
        raise StyleError(f"sheets.yaml: sheets.{key}.print.orientation {orientation!r} must be "
                         f"one of {list(_ORIENTATIONS)}")


def _check_merged(tokens, sheets):
    tabs = {}
    for key in C.SHEETS:
        conf = (sheets.get("sheets") or {}).get(key) or {}
        tab = conf.get("tab")
        if not isinstance(tab, str) or not tab or len(tab) > 31 or _BAD_TAB.search(tab) \
                or tab.startswith("_") or tab.casefold() in _RESERVED_TABS:
            raise StyleError(f"sheets.yaml: sheets.{key}.tab {tab!r} is not a usable Excel "
                             "tab name (1-31 characters, none of []:*?/\\, not starting with _, "
                             "not History)")
        # Excel tab names are case-insensitive.
        if tab.casefold() in tabs:
            raise StyleError(f"sheets.yaml: tab {tab!r} is used by both "
                             f"{tabs[tab.casefold()]} and {key}")
        tabs[tab.casefold()] = key
        _check_sheet_values(key, conf)
    for sheet, cols in (sheets.get("columns") or {}).items():
        for col, conf in (cols or {}).items():
            width = (conf or {}).get("width")
            if width is not None and not (_is_number(width) and width > 0):
                raise StyleError(f"sheets.yaml: columns.{sheet}.{col}.width {width!r} must be "
                                 "a positive number")
    pools = {"fill": "fills", "font_color": "font_colors", "border": "borders",
             "align": "alignments"}
    for style_name, style in (tokens.get("styles") or {}).items():
        for field, pool in pools.items():
            if field in style and style[field] not in (tokens.get(pool) or {}):
                raise StyleError(f"tokens.yaml: style {style_name!r} names {field} "
                                 f"{style[field]!r}, which is not in {pool}")
    missing = REQUIRED_STYLES - set(tokens.get("styles") or {})
    if missing:
        raise StyleError(f"tokens.yaml: missing styles {sorted(missing)}")


def load_style(path=None) -> StylePack:
    tokens = _read(BUNDLED / "tokens.yaml")
    sheets = _read(BUNDLED / "sheets.yaml")
    source = "bundled"
    if path is not None:
        root = Path(path)
        if not root.is_dir():
            raise StyleError(f"no such style directory: {root}")
        present = [name for name in _FILES if (root / name).exists()]
        if not present:
            raise StyleError(f"{root}: holds neither tokens.yaml nor sheets.yaml")
        for name in present:
            data = _read(root / name)
            _check_override(name, data)
            if name == "tokens.yaml":
                tokens = deep_merge(tokens, data)
            else:
                sheets = deep_merge(sheets, data)
        source = str(root)
    _check_merged(tokens, sheets)
    meta = sheets.get("meta") or tokens.get("meta") or {}
    return StylePack(name=str(meta.get("name", "heavycivil")),
                     version=str(meta.get("version", "1")), tokens=tokens,
                     sheets=sheets["sheets"], columns=sheets.get("columns") or {},
                     source=source)


def resolve_style(cli_path=None, profile=None) -> StylePack:
    if cli_path:
        return load_style(cli_path)
    if profile is not None:
        named = profile.section("estimating").get("heavycivil_style")
        if named:
            return load_style(named)
    return load_style()
