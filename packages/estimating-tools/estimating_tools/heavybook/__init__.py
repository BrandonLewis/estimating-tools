"""HeavyBook estimate workbook (#1486 sub-project 2; renamed from HeavyCivil on
2026-10-31, roadmap row 1.2).

Rendered straight from BidSheet.ai's ``get_estimate_workbook`` payload: one
outlined Cost Report, live formulas that reproduce BidSheet.ai's cost rules,
and a hidden id + ``v`` on every editable row so read-back can turn edits into
``apply_estimate_workbook_changes`` ops. See
docs/superpowers/specs/2026-10-20-heavycivil-workbook-render-design.md.
"""
from __future__ import annotations

FORMAT_NAME = "heavybook"
#: The pack's version: 2 is the template pack (step 4). Books built by the
#: code writers stamp version 1 and keep reading (``pack.HeavyBookPack``).
FORMAT_VERSION = "2"
#: Stamp values a reader accepts: books built before the rename say
#: ``heavycivil`` in ``_wb!A1`` and in the ``estimate_format`` property.
ACCEPTED_FORMATS = frozenset({"heavybook", "heavycivil"})
