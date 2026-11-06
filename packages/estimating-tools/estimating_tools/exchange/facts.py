"""One cheap pass over a workbook for detection."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from estimating_tools.exchange.types import BookFacts

#: Defined names every detect may ask for.
DEFAULT_NAMES = ("exchange.stamp", "hc.layout", "est.layout")


def read_facts(path: str | Path, names: Sequence[str] = DEFAULT_NAMES) -> BookFacts:
    """Custom properties, the first cell of each requested defined name, and
    sheet names. Workbook-scoped names only. Never raises: ``error`` is set
    when the book cannot be read."""
    from openpyxl import load_workbook
    from openpyxl.utils.cell import range_boundaries

    path = Path(path)
    facts = BookFacts(path=str(path))
    prefix = f"cannot read {path.name} as a workbook: "
    try:
        wb = load_workbook(path, read_only=True, data_only=False)
    except FileNotFoundError:
        return replace(facts, error=f"no such file: {path}")
    except Exception as exc:  # noqa: BLE001 -- any unreadable file is "no facts"
        return replace(facts, error=prefix + str(exc))
    try:
        props = {p.name: p.value for p in wb.custom_doc_props.props}
        found = {}
        for name in names:
            dn = wb.defined_names.get(name)
            if dn is None:
                continue
            for sheet, ref in dn.destinations:
                if sheet not in wb.sheetnames:
                    continue
                c1, r1, _, _ = range_boundaries(ref.replace("$", ""))
                if c1 is None or r1 is None:  # whole-column or whole-row name
                    continue
                found[name] = wb[sheet].cell(row=r1, column=c1).value
                break
        return replace(facts, properties=props, names=found, sheets=list(wb.sheetnames))
    except Exception as exc:  # noqa: BLE001 -- detection must always get an answer
        return replace(facts, error=prefix + str(exc))
    finally:
        wb.close()
