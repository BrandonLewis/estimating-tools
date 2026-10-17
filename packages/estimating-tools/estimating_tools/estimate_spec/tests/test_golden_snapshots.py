"""Golden snapshots: no engine change may alter a pack that did not opt in.

Captured BEFORE the fieldbook engine work (phase 1, task 1). Regenerate only
for a deliberate, reviewed output change: UPDATE_GOLDEN=1 pytest <this file>.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import format_pack as fp
from estimating_tools.estimate_spec.tests._snapshot import snapshot

HERE = Path(__file__).resolve().parent
PACKS = HERE / "fixtures" / "packs"
GOLDEN_DIR = HERE / "fixtures" / "golden"
CASES = {
    "legacy_demo": PACKS / "legacy_demo" / "examples" / "demo-pipeline.estimate.yaml",
    "alt": PACKS / "alt" / "examples" / "sample.estimate.yaml",
}
# Sheets that are not per-bid-item sheets in legacy_demo's output (cover,
# setup, and the rate library) -- everything else is a "2 - ..."/"3 - ..."
# per-item sheet that must carry real layout (a merge or a set width).
NON_ITEM_SHEETS = {"Bid Summary", "SETUP", "Rates"}


def _build(name):
    spec = yaml.safe_load(CASES[name].read_text(encoding="utf-8"))
    return B.generate(spec, fp.load_pack(PACKS / name))


@pytest.mark.parametrize("name", sorted(CASES))
def test_fixture_pack_output_is_unchanged(name):
    # No `default=str`: an unexpected (non-JSON-native) type coming out of
    # the snapshot should fail loudly here rather than get silently
    # stringified away.
    got = json.loads(json.dumps(snapshot(_build(name))))
    golden = GOLDEN_DIR / f"{name}.snapshot.json"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    assert got == json.loads(golden.read_text(encoding="utf-8"))


def test_legacy_golden_item_sheets_have_merges_or_widths():
    """A wholesale drop of merges/widths from the snapshot must not be able
    to regenerate a golden that silently accepts it: every per-bid-item
    sheet in the real demo output does carry at least one of each."""
    golden = json.loads((GOLDEN_DIR / "legacy_demo.snapshot.json").read_text(encoding="utf-8"))
    item_sheets = {name: s for name, s in golden["sheets"].items() if name not in NON_ITEM_SHEETS}
    assert item_sheets, "expected at least one per-bid-item sheet in legacy_demo"
    for name, s in item_sheets.items():
        assert s["merges"] or s["widths"], f"{name!r} has neither a merge nor a set column width"


# ---------------------------------------------------------------------------
# Anti-vacuous check: a table of single-dimension mutations, each of which
# must be visible in the snapshot. If any of these passed without changing
# the snapshot, the golden comparison above would be proving nothing for
# that dimension of style.
# ---------------------------------------------------------------------------

def _font_mutation(**changes):
    def mutate(wb):
        c = wb["Bid Summary"]["A2"]
        f = c.font
        kwargs = dict(name=f.name, sz=f.sz, b=f.b, i=f.i, color=f.color, u=f.u, strike=f.strike,
                      vertAlign=f.vertAlign)
        kwargs.update(changes)
        c.font = Font(**kwargs)
    return mutate


def _border_mutation(*, style=None, color=None):
    def mutate(wb):
        c = wb["Bid Summary"]["A2"]
        side = Side(style=style if style is not None else c.border.top.style,
                    color=color if color is not None else c.border.top.color)
        c.border = Border(top=side, bottom=side)
    return mutate


def _alignment_mutation(**changes):
    def mutate(wb):
        c = wb["Bid Summary"]["A2"]
        a = c.alignment
        kwargs = dict(horizontal=a.horizontal, vertical=a.vertical, wrapText=a.wrapText,
                      indent=a.indent, shrinkToFit=a.shrinkToFit, textRotation=a.textRotation)
        kwargs.update(changes)
        c.alignment = Alignment(**kwargs)
    return mutate


def _protection_mutation(**changes):
    def mutate(wb):
        c = wb["Bid Summary"]["A2"]
        p = c.protection
        kwargs = dict(locked=p.locked, hidden=p.hidden)
        kwargs.update(changes)
        c.protection = Protection(**kwargs)
    return mutate


def _fill_mutation(wb):
    wb["Bid Summary"]["A2"].fill = PatternFill("solid", fgColor="FF123456")


def _number_format_mutation(wb):
    wb["Bid Summary"]["A2"].number_format = "0.00"


def _add_merge_mutation(wb):
    wb["Rates"].merge_cells("A1:B1")


def _column_width_mutation(wb):
    wb["SETUP"].column_dimensions["A"].width = 40.0


def _row_height_mutation(wb):
    wb["Rates"].row_dimensions[2].height = 30.0


def _freeze_panes_mutation(wb):
    wb["Rates"].freeze_panes = "A2"


def _hide_sheet_mutation(wb):
    wb["Rates"].sheet_state = "hidden"


def _hide_a_column_mutation(wb):
    setattr(wb["SETUP"].column_dimensions["A"], "hidden", True)


def _protect_sheet_mutation(wb):
    wb["Rates"].protection.sheet = True


def _reorder_sheets_mutation(wb):
    wb.move_sheet("Rates", offset=-1)


def _add_conditional_rule(ws):
    rule = CellIsRule(operator="greaterThan", formula=["5"],
                       fill=PatternFill(start_color="FFFFFF00", end_color="FFFFFF00", fill_type="solid"))
    ws.conditional_formatting.add("A1:A6", rule)


def _add_conditional_rule_mutation(wb):
    _add_conditional_rule(wb["Rates"])


def _change_conditional_rule_fill_setup(wb):
    _add_conditional_rule(wb["Rates"])


def _change_conditional_rule_fill_mutation(wb):
    ws = wb["Rates"]
    for cf in ws.conditional_formatting:
        for rule in cf.rules:
            rule.dxf.fill = PatternFill(start_color="FF00B050", end_color="FF00B050", fill_type="solid")


def _noop(wb):
    pass


# (id, setup, mutate) -- setup runs before the "before" snapshot (for cases
# that need a pre-existing feature to change, rather than add); mutate runs
# after it, and must change the snapshot relative to the post-setup state.
MUTATIONS = [
    ("font-bold", _noop, _font_mutation(b=False)),  # baseline cell is bold=True
    ("font-size", _noop, _font_mutation(sz=72)),
    ("font-colour", _noop, _font_mutation(color="FF00FF00")),
    ("font-underline", _noop, _font_mutation(u="single")),
    ("fill", _noop, _fill_mutation),
    ("border-style", _noop, _border_mutation(style="thin")),
    ("border-colour", _noop, _border_mutation(color="FFFF0000")),
    ("number-format", _noop, _number_format_mutation),
    ("alignment-horizontal", _noop, _alignment_mutation(horizontal="right")),
    ("alignment-vertical", _noop, _alignment_mutation(vertical="center")),
    ("alignment-wrap-text", _noop, _alignment_mutation(wrapText=True)),
    ("locked", _noop, _protection_mutation(locked=False)),
    ("hidden", _noop, _protection_mutation(hidden=True)),
    ("add-a-merge", _noop, _add_merge_mutation),
    ("column-width", _noop, _column_width_mutation),
    ("add-conditional-rule", _noop, _add_conditional_rule_mutation),
    ("conditional-rule-fill", _change_conditional_rule_fill_setup, _change_conditional_rule_fill_mutation),
    ("protect-a-sheet", _noop, _protect_sheet_mutation),
    ("reorder-sheets", _noop, _reorder_sheets_mutation),
    ("row-height", _noop, _row_height_mutation),
    ("freeze-panes", _noop, _freeze_panes_mutation),
    ("hide-a-sheet", _noop, _hide_sheet_mutation),
    ("hide-a-column", _noop, _hide_a_column_mutation),
]


@pytest.mark.parametrize("name, setup, mutate", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_snapshot_detects_single_dimension_change(name, setup, mutate):
    """If any of these passed without the snapshot changing, the golden
    comparison would be proving nothing for that dimension."""
    wb = _build("legacy_demo")
    setup(wb)
    before = snapshot(wb)
    assert all(s["cells"] for s in before["sheets"].values())
    mutate(wb)
    assert snapshot(wb) != before
