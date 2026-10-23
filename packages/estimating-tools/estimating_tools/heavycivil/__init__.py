"""HeavyCivil estimate workbook (#1486 sub-project 2).

A second estimate workbook alongside fieldbook, rendered straight from
BidSheet.ai's ``get_estimate_workbook`` payload rather than from a spec YAML:
one outlined Cost Report, live formulas that reproduce BidSheet.ai's cost
rules, and a hidden id + ``v`` on every editable row so a later read-back
(sub-project 3) can turn edits into ``apply_estimate_workbook_changes`` ops.
See docs/superpowers/specs/2026-10-20-heavycivil-workbook-render-design.md.
"""
from __future__ import annotations

FORMAT_NAME = "heavycivil"
FORMAT_VERSION = "1"
