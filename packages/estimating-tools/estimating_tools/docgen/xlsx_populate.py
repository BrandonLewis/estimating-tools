"""Copy an xlsx template and substitute named cells."""
from __future__ import annotations
import shutil
from pathlib import Path
from typing import Mapping

import openpyxl


def populate(src: Path, dest: Path, cells: Mapping[str, object]) -> Path:
    """Copy `src` to `dest`, set `cells` (keyed `"Sheet!A1"`), save.

    Sheet names must not contain `!` — the first `!` is the sheet/address
    separator. Raises `KeyError` if a referenced sheet does not exist, and
    `ValueError` (with file + key context) if a cell address is malformed.
    On any failure, the partial `dest` file is removed.
    """
    src = Path(src)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    try:
        if not cells:
            return dest
        wb = openpyxl.load_workbook(dest)
        for cell_ref, value in cells.items():
            sheet, addr = cell_ref.split("!", 1)
            if sheet not in wb.sheetnames:
                raise KeyError(f"Sheet not found in {dest}: {sheet!r}")
            try:
                wb[sheet][addr] = value
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"Invalid cell address {addr!r} in key {cell_ref!r} for {dest}"
                ) from exc
        wb.save(dest)
        return dest
    except Exception:
        dest.unlink(missing_ok=True)
        raise
