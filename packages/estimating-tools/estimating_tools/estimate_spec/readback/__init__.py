"""Read an edited fieldbook workbook back into its estimate spec (fieldbook phase 4).

Estimators edit the workbook -- type inputs, copy and paste rows and whole
task blocks -- and `read_back` turns those edits into an updated spec plus a
report: new tasks, rows and rates; changed inputs; deleted rows; resources
with no rate; formula cells typed over (ignored); untagged rows (listed,
never guessed). `est-estimate read-back` is the CLI. A workbook built with a
pack that declares `derived_from: fieldbook` (an org fork that keeps the grid)
is read the same way, against that pack.

Modules: `layout` (what the reader knows of the pack's grid), `sheets` (read
each sheet into plain rows), `values` (cell <-> spec value comparisons),
`merge` (rows into the spec, recording each difference), `reader` (refusals
and orchestration), `report` (Markdown), `spec_io` (round-trip YAML for the
CLI's --write; not imported here, so read_back needs no ruamel.yaml).
"""
from estimating_tools.estimate_spec.readback.merge import Findings
from estimating_tools.estimate_spec.readback.reader import (
    ReadBack, ReadBackRefused, fieldbook_pack, load_workbook, read_back)
from estimating_tools.estimate_spec.readback.report import render_report

__all__ = ["Findings", "ReadBack", "ReadBackRefused", "fieldbook_pack", "load_workbook",
           "read_back", "render_report"]
