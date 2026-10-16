"""Cache formula VALUES into a workbook via Excel COM (#202).

A live-formula workbook stores formulas, not results, until Excel evaluates
them; a consumer that only reads cached values (or a PDF/print step) needs
them realized. This drives Excel to recalculate and save.

Windows-only, and deliberately ``DispatchEx``: plain ``Dispatch`` attaches to
the estimator's already-open Excel instance and can discard their unsaved work
(a trap learned the hard way). Absent pywin32/Excel, raises a clean error
rather than a bare ImportError.
"""
from __future__ import annotations

from pathlib import Path


def recalculate(path: str) -> None:
    """Open ``path`` in a private Excel, full-rebuild, save, close."""
    try:
        import win32com.client as com
    except ImportError as exc:                      # pragma: no cover - env
        raise RuntimeError(
            "recalculate needs pywin32 + Excel (Windows only); install "
            "pywin32, or open the workbook in Excel once to cache values"
        ) from exc
    if com is None:                                 # test/stubbed environment
        raise RuntimeError(
            "recalculate needs pywin32 + Excel (Windows only)")

    try:
        excel = com.DispatchEx("Excel.Application")  # never Dispatch
    except Exception as exc:                         # COM error: Excel absent
        raise RuntimeError(
            "recalculate needs Microsoft Excel installed and COM-registered "
            "(Windows only); open the workbook in Excel once to cache values"
        ) from exc
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(str(Path(path).resolve()))
        wb.Application.CalculateFullRebuild()
        wb.Save()
        wb.Close(SaveChanges=False)
    finally:
        excel.Quit()
