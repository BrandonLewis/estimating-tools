"""calcbook — shared writer for styled, live-formula calculator workbooks (#202).

`estimating_tools.excel` reads workbooks; this writes them. It lifts the
plumbing every Work calculator re-derived — the yellow estimator-input cell, a
styled header / key-value / section helper, the RATES override-column pattern,
the PERT formula, byte-reproducible zip pinning, and the ``--recalc`` COM
helper — into one org-agnostic library so calculators carry only their domain
math. Prereq for graduating the Tools calculators to calc-* plugins (#207).
"""
# The formula API is pure strings — importable in a base install. The writer
# needs openpyxl (the optional `excel`/`plugin-core` extra), so its names load
# lazily (PEP 562): `import estimating_tools.calcbook.formula` — or using only
# pert/override/cell_ref — never pulls openpyxl in.
from estimating_tools.calcbook.formula import cell_ref, override, pert

_WRITER_NAMES = frozenset({
    "new_workbook", "save", "header", "section", "kv", "mark_input",
    "set_widths", "rate_table", "INPUT_FILL", "HEADER_FILL", "HEADER_FONT",
    "TITLE_FONT", "BOLD_FONT", "NOTE_FONT",
})
_RECALC_NAMES = frozenset({"recalculate"})

__all__ = [
    "cell_ref", "pert", "override",
    *sorted(_WRITER_NAMES), *sorted(_RECALC_NAMES),
]


def __getattr__(name):
    if name in _WRITER_NAMES:
        from estimating_tools.calcbook import writer
        return getattr(writer, name)
    if name in _RECALC_NAMES:
        from estimating_tools.calcbook import recalc
        return getattr(recalc, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
