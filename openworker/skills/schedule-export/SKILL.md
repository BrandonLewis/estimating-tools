---
name: schedule-export
description: Convert a Gantt schedule spreadsheet into GanttWarrior JSON — WBS, durations, holidays, and work-day calculations.
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Schedule Export to GanttWarrior

Use this when asked to turn a spreadsheet schedule into GanttWarrior-importable
JSON.

## Workflow
1. Confirm the Gantt xlsx has the expected WBS/duration columns.
2. Convert:
   ```bash
   est-gantt <path/to/gantt.xlsx> -d <output_dir>
   ```
   (run `est-gantt --help` for exact flags).
3. Import the JSON into GanttWarrior and verify task count, dependencies, and
   computed work days.

## Notes
- Holiday handling and work-day math are deterministic in
  `estimating_tools.schedule.gantt_to_ganttwarrior`.
- **The `Predecessors` column is documented but never read.** `est-gantt` also
  ignores any Start/End date columns and the cost columns — every computed date
  derives from WBS nesting plus `Offset` alone. Dependency logic encoded in
  `Predecessors` yields plausible-looking but wrong dates, with no error or
  warning. Instead: drive sequencing with offsets, or keep the source schedule
  file canonical and bring it in through the `est-schedule` importers rather
  than round-tripping dependencies through this spreadsheet.
