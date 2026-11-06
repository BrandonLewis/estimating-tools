"""Cache formula VALUES into a workbook via Excel COM (#202).

A live-formula workbook stores formulas, not results, until Excel evaluates
them; a consumer that only reads cached values (or a PDF/print step) needs
them realized. This drives Excel to recalculate and save.

Windows-only, and deliberately ``DispatchEx``: plain ``Dispatch`` attaches to
the estimator's already-open Excel instance and can discard their unsaved work
(a trap learned the hard way). Absent pywin32/Excel, raises a clean error
rather than a bare ImportError.

Builds that must not fail for want of Excel use
:func:`estimating_tools.xlsx_recalc.recalculate` instead (#370): it picks an
engine (this one in a child process, Excel through PowerShell COM, or
LibreOffice), works on a temp copy, and reports "no engine" rather than
raising.
"""
from __future__ import annotations

from pathlib import Path


class ExcelUnavailable(RuntimeError):
    """pywin32 or Excel is missing: Excel never started (nothing to clean up)."""


def _excel_pid(excel) -> int | None:
    try:
        import win32process
        return int(win32process.GetWindowThreadProcessId(excel.Hwnd)[1])
    except Exception:                                # noqa: BLE001 - best effort
        return None


def recalculate(path: str, *, report_pid=None) -> None:
    """Open ``path`` in a private Excel, full-rebuild, save, close.

    ``report_pid``: called with the private Excel's process id as soon as it
    starts, so a caller that times out can kill exactly that process."""
    try:
        import win32com.client as com
    except ImportError as exc:                      # pragma: no cover - env
        raise ExcelUnavailable(
            "recalculate needs pywin32 + Excel (Windows only); install "
            "pywin32, or open the workbook in Excel once to cache values"
        ) from exc
    if com is None:                                 # test/stubbed environment
        raise ExcelUnavailable(
            "recalculate needs pywin32 + Excel (Windows only)")

    try:
        excel = com.DispatchEx("Excel.Application")  # never Dispatch
    except Exception as exc:                         # COM error: Excel absent
        raise ExcelUnavailable(
            "recalculate needs Microsoft Excel installed and COM-registered "
            "(Windows only); open the workbook in Excel once to cache values"
        ) from exc
    try:
        if report_pid is not None:
            report_pid(_excel_pid(excel))
        excel.Visible = False
        excel.DisplayAlerts = False
        wb = excel.Workbooks.Open(str(Path(path).resolve()))
        wb.Application.CalculateFullRebuild()
        wb.Save()
        wb.Close(SaveChanges=False)
    finally:
        excel.Quit()
