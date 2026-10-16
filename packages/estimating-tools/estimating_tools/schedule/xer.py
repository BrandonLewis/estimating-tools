"""Primavera P6 .xer → Excel: the shared reader + output profiles (#204).

Collapses four hand-rolled converters onto one reader (now
``bimforge.bim.xer``) — parse the
tab-delimited ``%T``/``%F``/``%R`` dump, build WBS name-paths, convert P6
duration/float hours to work-days — feeding two output profiles:

  ``dump``    a full human-readable workbook (Activities / WBS / Relationships,
              plus a raw sheet per remaining non-empty table): browse a P6
              export without opening P6.
  ``bridge``  a formatted per-selector deliverable (title/subtitle banner;
              Activity ID / Name / Stage / Orig. Dur (wd) / Start / Finish /
              Total Float (wd); LOE/summary rows highlighted). Sheet selectors,
              titles and stage rules are CALLER config (org data), never baked.

The import-tasks / activity-code-filter need is already met by
``est-schedule scope`` (filter → 9-column Task Table, external preds preserved),
so this module deliberately does not duplicate it. ``est-schedule xer`` wires
the CLI. Both writers are byte-deterministic (double-build equal) via the
shared ``xlsx_determinism`` normalizer.
"""
from __future__ import annotations

from datetime import date  # noqa: F401  (part of the re-exported reader API)
from pathlib import Path

# The reader half moved to bimforge.bim.xer (so bimforge's own schedule
# importers can parse a P6 export standalone); re-exported here so the Excel
# profiles below and every existing import keep one reader.
from bimforge.bim.xer import (  # noqa: F401  (re-export)
    _DATE_SOURCES, _SUMMARY_TYPES, _XER_WORKDAY_HR, _require_positive_hpd,
    hours_to_workdays, is_summary, parse_tables, read_tables, wbs_paths,
    xer_date, xer_date_obj,
)


# ---------------------------------------------------------------------------
# xlsx helpers (shared styling / determinism)
# ---------------------------------------------------------------------------

def _new_workbook():
    from openpyxl import Workbook

    from estimating_tools.xlsx_determinism import BUILD_STAMP
    wb = Workbook()
    wb.properties.created = wb.properties.modified = BUILD_STAMP
    wb.remove(wb.active)
    return wb


def _save(wb, path: str) -> str:
    from estimating_tools.xlsx_determinism import normalize_xlsx
    wb.save(path)
    normalize_xlsx(path)         # pin docProps + zip-member timestamps
    return path


def _style_header(ws):
    from openpyxl.styles import Alignment, Font, PatternFill
    fill = PatternFill("solid", fgColor="1F4E78")
    font = Font(color="FFFFFF", bold=True)
    for cell in ws[1]:
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"


def _autosize(ws, max_w: int = 60) -> None:
    widths: dict[str, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            ln = len(str(cell.value))
            if ln > widths.get(cell.column_letter, 0):
                widths[cell.column_letter] = ln
    for col, w in widths.items():
        ws.column_dimensions[col].width = min(max(w + 2, 8), max_w)


# ---------------------------------------------------------------------------
# dump profile
# ---------------------------------------------------------------------------

_STATUS = {"TK_NotStart": "Not Started", "TK_Active": "In Progress",
           "TK_Complete": "Completed"}
_TYPE = {"TT_Task": "Task Dependent", "TT_Rsrc": "Resource Dependent",
         "TT_Mile": "Start Milestone", "TT_FinMile": "Finish Milestone",
         "TT_LOE": "Level of Effort", "TT_WBS": "WBS Summary"}
_RELTYPE = {"PR_FS": "FS", "PR_SS": "SS", "PR_FF": "FF", "PR_SF": "SF"}


def _sanitize_sheet_name(name: str, used: set[str]) -> str:
    for ch in r"[]:*?/\\":
        name = name.replace(ch, "_")
    name = name[:31] or "Sheet"
    base, n = name, 1
    while name in used:
        suffix = f"_{n}"
        name = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(name)
    return name


def write_dump(tables: dict[str, list[dict]], path: str, *,
               hours_per_day: float = _XER_WORKDAY_HR, raw: bool = True) -> str:
    """Full human-readable workbook of a P6 export (byte-deterministic).

    Activities / WBS / Relationships summary sheets, and — when ``raw`` — a
    verbatim sheet per remaining non-empty source table so nothing in the
    export is hidden.
    """
    _require_positive_hpd(hours_per_day)
    wb = _new_workbook()
    paths = wbs_paths(tables)
    tasks = tables.get("TASK", [])

    ws = wb.create_sheet("Activities")
    ws.append(["Activity ID", "Activity Name", "WBS", "Status",
               "Orig Dur (d)", "Rem Dur (d)", "Start", "Finish",
               "Total Float (d)", "Free Float (d)",
               "Actual Start", "Actual Finish", "Type"])
    for t in tasks:
        start = (t.get("act_start_date") or t.get("early_start_date")
                 or t.get("target_start_date") or "")
        finish = (t.get("act_end_date") or t.get("early_end_date")
                  or t.get("target_end_date") or "")
        ws.append([
            t.get("task_code", ""), t.get("task_name", ""),
            paths.get(t.get("wbs_id", ""), ""),
            _STATUS.get(t.get("status_code", ""), t.get("status_code", "")),
            hours_to_workdays(t.get("target_drtn_hr_cnt"), hours_per_day),
            hours_to_workdays(t.get("remain_drtn_hr_cnt"), hours_per_day),
            xer_date(start), xer_date(finish),
            hours_to_workdays(t.get("total_float_hr_cnt"), hours_per_day),
            hours_to_workdays(t.get("free_float_hr_cnt"), hours_per_day),
            xer_date(t.get("act_start_date")), xer_date(t.get("act_end_date")),
            _TYPE.get(t.get("task_type", ""), t.get("task_type", "")),
        ])
    _style_header(ws)
    _autosize(ws)

    ws = wb.create_sheet("WBS")
    ws.append(["WBS Code", "WBS Name", "Full Path"])
    for r in tables.get("PROJWBS", []):
        ws.append([r.get("wbs_short_name", ""), r.get("wbs_name", ""),
                   paths.get(r.get("wbs_id", ""), "")])
    _style_header(ws)
    _autosize(ws)

    by_id = {t.get("task_id"): t for t in tasks}
    ws = wb.create_sheet("Relationships")
    ws.append(["Predecessor ID", "Predecessor Name", "Successor ID",
               "Successor Name", "Rel Type", "Lag (d)"])
    for r in tables.get("TASKPRED", []):
        pred = by_id.get(r.get("pred_task_id"), {})
        succ = by_id.get(r.get("task_id"), {})
        ws.append([
            pred.get("task_code", r.get("pred_task_id", "")),
            pred.get("task_name", ""),
            succ.get("task_code", r.get("task_id", "")),
            succ.get("task_name", ""),
            _RELTYPE.get(r.get("pred_type", ""), r.get("pred_type", "")),
            hours_to_workdays(r.get("lag_hr_cnt"), hours_per_day),
        ])
    _style_header(ws)
    _autosize(ws)

    if raw:
        used = {"Activities", "WBS", "Relationships"}
        for name, rows in tables.items():
            if not rows:
                continue
            sheet = _sanitize_sheet_name(name, used)
            ws = wb.create_sheet(sheet)
            headers = list(rows[0].keys())
            ws.append(headers)
            for r in rows:
                ws.append([r.get(h, "") for h in headers])
            _style_header(ws)
            _autosize(ws)

    return _save(wb, path)


# ---------------------------------------------------------------------------
# bridge profile
# ---------------------------------------------------------------------------

_BRIDGE_HEADERS = ["Activity ID", "Activity Name", "Stage / WBS",
                   "Orig. Duration (wd)", "Start", "Finish",
                   "Total Float (wd)"]
_BRIDGE_WIDTHS = {"A": 13, "B": 58, "C": 26, "D": 16, "E": 13, "F": 13,
                  "G": 16}
_DATE_FMT = "mm/dd/yy;@"


def _code_suffix(code: str) -> tuple[int, object]:
    """Sort key for an activity code's numeric suffix; ``.SUM`` sorts first."""
    _, _, suffix = code.partition(".")
    if suffix.upper() == "SUM":
        return (0, 0)
    try:
        return (1, int(suffix))
    except ValueError:
        return (2, suffix)


def _code_num(code: str):
    _, _, suffix = code.partition(".")
    try:
        return int(suffix)
    except ValueError:
        return None


def _selector(sheet: dict):
    """A predicate on a task dict from a sheet's selector config.

    ``code_prefixes`` (list) or ``code_prefix`` (str) selects by the code's
    dotted prefix; an optional ``code_range`` [lo, hi] further bounds the
    numeric suffix (inclusive).
    """
    prefixes = set(_sheet_prefixes(sheet))
    rng = sheet.get("code_range")

    def match(t: dict) -> bool:
        code = t.get("task_code", "")
        if code.partition(".")[0] not in prefixes:
            return False
        if rng:
            n = _code_num(code)
            if n is None or not (rng[0] <= n <= rng[1]):
                return False
        return True

    return match


def _stage_label(task: dict, path: str, sheet: dict, rules: list[dict]) -> str:
    if is_summary(task):
        return "Summary"
    if sheet.get("stage"):
        return sheet["stage"]
    hay = path.lower()
    for rule in rules:
        needle = (rule.get("contains") or "").lower()
        if needle and needle in hay:
            return rule.get("label", "")
    return path.split(" > ")[-1] if path else ""


def _sheet_prefixes(sheet: dict) -> list[str]:
    """The sheet's code prefixes as a validated non-empty list of strings.

    ``code_prefixes`` must be a list (a bare string like ``"PPOB"`` would
    silently become a set of characters and select nothing); ``code_prefix``
    is the scalar form.
    """
    prefixes = sheet.get("code_prefixes")
    if prefixes is None and sheet.get("code_prefix"):
        prefixes = [sheet["code_prefix"]]
    if isinstance(prefixes, str):
        raise ValueError(
            f"bridge sheet {sheet.get('title', '?')!r}: code_prefixes must be "
            "a list of strings (use code_prefix for a single prefix)")
    if not prefixes or not all(isinstance(p, str) and p for p in prefixes):
        raise ValueError(
            f"bridge sheet {sheet.get('title', '?')!r} needs a selector "
            "(code_prefixes: non-empty list / code_prefix: string)")
    return list(prefixes)


def _validate_bridge_config(config: dict) -> None:
    if not isinstance(config, dict) or not config.get("title"):
        raise ValueError("bridge config needs a 'title'")
    sheets = config.get("sheets")
    if not isinstance(sheets, list) or not sheets:
        raise ValueError("bridge config needs a non-empty 'sheets' list")
    ds = config.get("date_source", "target")
    if ds not in _DATE_SOURCES:
        raise ValueError(
            f"bridge config date_source {ds!r} must be one of {_DATE_SOURCES}")
    _require_positive_hpd(float(config.get("hours_per_day", _XER_WORKDAY_HR)))
    for s in sheets:
        if not isinstance(s, dict) or not s.get("title"):
            raise ValueError("each bridge sheet needs a 'title'")
        _sheet_prefixes(s)                 # raises on a bad/absent selector


def write_bridge(tables: dict[str, list[dict]], path: str,
                 config: dict) -> str:
    """Formatted per-selector bridge/deliverable workbook (byte-deterministic).

    ``config`` = ``{title, hours_per_day?, date_source?, stage_rules?,
    sheets: [{title, subtitle?, code_prefixes|code_prefix, code_range?,
    stage?}]}``. All selectors/titles/stage rules are caller-supplied (org
    data): the mechanism carries none.
    """
    from openpyxl.styles import Alignment, Font, PatternFill
    _validate_bridge_config(config)

    hpd = float(config.get("hours_per_day", _XER_WORKDAY_HR))
    rules = config.get("stage_rules", [])
    ds = config.get("date_source", "target")
    start_key, end_key = {
        "target": ("target_start_date", "target_end_date"),
        "early": ("early_start_date", "early_end_date"),
        "actual": ("act_start_date", "act_end_date"),
    }.get(ds, ("target_start_date", "target_end_date"))

    hdr_fill = PatternFill("solid", fgColor="1F4E78")
    sum_fill = PatternFill("solid", fgColor="FFFF00")
    hdr_font = Font(bold=True, color="FFFFFF")
    sum_font = Font(bold=True)
    body_font = Font()
    ctr = Alignment(horizontal="center")
    left = Alignment(horizontal="left")

    wb = _new_workbook()
    paths = wbs_paths(tables)
    tasks = tables.get("TASK", [])

    used: set[str] = set()
    for sheet in config["sheets"]:
        ws = wb.create_sheet(_sanitize_sheet_name(sheet["title"], used))
        for col, w in _BRIDGE_WIDTHS.items():
            ws.column_dimensions[col].width = w
        ws["A1"] = config["title"]
        ws["A1"].font = Font(bold=True, size=12)
        ws.merge_cells("A1:G1")
        if sheet.get("subtitle"):
            ws["A2"] = sheet["subtitle"]
            ws["A2"].font = Font(bold=True, size=11)
            ws.merge_cells("A2:G2")
        for i, h in enumerate(_BRIDGE_HEADERS, start=1):
            c = ws.cell(row=4, column=i, value=h)
            c.fill = hdr_fill
            c.font = hdr_font
            c.alignment = ctr

        match = _selector(sheet)
        picked = sorted((t for t in tasks if match(t)),
                        key=lambda t: (t.get("task_code", "").partition(".")[0],
                                       _code_suffix(t.get("task_code", ""))))
        r = 5
        for t in picked:
            summary = is_summary(t)
            font = sum_font if summary else body_font
            vals = [
                t.get("task_code", ""), t.get("task_name", ""),
                _stage_label(t, paths.get(t.get("wbs_id", ""), ""), sheet,
                             rules),
                hours_to_workdays(t.get("target_drtn_hr_cnt"), hpd, whole=True),
                xer_date_obj(t.get(start_key)), xer_date_obj(t.get(end_key)),
                hours_to_workdays(t.get("total_float_hr_cnt"), hpd, whole=True),
            ]
            for i, v in enumerate(vals, start=1):
                c = ws.cell(row=r, column=i, value=v)
                c.font = font
                c.alignment = left if i == 2 else ctr
                if i in (5, 6):
                    c.number_format = _DATE_FMT
                if summary:
                    c.fill = sum_fill
            r += 1
        ws.freeze_panes = "A5"

    return _save(wb, path)
