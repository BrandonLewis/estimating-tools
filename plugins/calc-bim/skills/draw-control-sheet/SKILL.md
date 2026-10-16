---
name: draw-control-sheet
description: Draw a survey-control sheet — point markers, a control table, the basis-of-bearing/coordinates note, and (for approximate-grade work) a NOT FOR CONSTRUCTION LAYOUT caveat — as DXF, PDF, KML, and a QC report, via the `est-sheets` CLI (bimforge.sheets + bimforge.cad). Use after `intake-project`/`project-briefing` when the bid needs a control sheet reconstructed from the plans' survey data. Writes local files only, under the bid working dir's `Sheets/`.
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If `~/.estimating/bin/est-sheets --help` fails, run `python <calc-bim plugin root>/scripts/ensure_tools.py`; it builds the shared runtime and prints one line saying what happened. Then retry.

# Draw a Control Sheet (est-sheets control)

Reconstruct the bid's survey control from the plans and render it as a
submittable sheet: point markers and labels on NCS layers, a control table,
the basis note, and — for `approximate` grade — the not-for-layout caveat,
stamped both on the sheet and in the QC report. Ground coordinates stay in
the DXF (x = Easting, y = Northing); only the KML converts to lon/lat.

## Prerequisites
The sheet engine ships inside bimforge, and matplotlib (for PDF/PNG) is in the
base install. Run `~/.estimating/bin/est-sheets --help` to confirm; if that
command is not found, see the **Setup** block above.

## Grade discipline (read this before touching the CLI)

Every control sheet declares `--grade survey` or `--grade approximate`, and
the choice is a judgment call you make honestly, not a default:

- **`survey`** — the points are tied to published control (a recoverable
  monument, a stated basis of bearing, a closure check you actually ran) with
  residuals inside tolerance (Work-repo practice: closure < 0.02 ft). Only
  claim this grade when you have the tie/closure numbers to back it up.
- **`approximate`** — the points are georeferenced from imagery or plan
  callouts with no tie to published control (Work-repo language: "±30 ft —
  field navigation and takeoff only, NOT FOR CONSTRUCTION LAYOUT"). This is
  the honest default whenever you cannot show a closure check. (Canonical
  grade rule: the `drafting-agent` agent.)

`~/.estimating/bin/est-sheets control` stamps the caveat onto the sheet and into the QC report
automatically when `--grade approximate` is passed — you don't add it by
hand — but the judgment of *which grade to claim* is yours. Never present an
`approximate` sheet as construction-layout-grade control; if a downstream
skill (`draw-layout-sheet`, `draw-structure-sheet`) inherits this project's
grade, an approximate control sheet propagates the same caveat to them.

## Workflow

1. **Find the plans' control/geometric data.** Use the `pdf-extraction`
   skill (estimating-core plugin) on the registered plan sheets to pull any control-point table,
   basis-of-bearing note, benchmark list, and CRS/datum callout. If the plans
   carry no coordinate table — only lettered dimensions or a schematic — fall
   back to the `measure-plans` skill's (calc-bim plugin) calibrate/vectors steps to recover
   coordinates from the drawn geometry (calibration evidence and residual
   feed directly into your grade call).

2. **Reconstruct coordinates.** Where the plans give bearings/distances or
   curve data instead of coordinates, compute northing/easting with
   `bimforge.cad.formats`' COGO helpers (`bearing_to_azimuth`, `forward`, …) —
   there is no COGO engine in this pipeline (v1 design decision: YAGNI); the
   deterministic layer only consumes already-computed points. Judge grade
   honestly at this step: a tie to a recoverable monument with a closure
   check earns `survey`; anything georeferenced from imagery or unstamped
   plan callouts is `approximate`.

3. **Author `control-points.csv`** under `<bid_dir>/Sheets/`. Required
   columns: `point_id,description,northing_ft,easting_ft`. Optional columns
   the schema also understands (Pioneer's PNEZDS+ pattern — points span
   survey control, benchmarks, monuments, and structure workpoints):
   `elevation_ft,station,offset_ft,side,latitude,longitude`. Leave optional
   cells blank when not applicable; don't invent values.

4. **Render the sheet:**
   ```bash
   ~/.estimating/bin/est-sheets control <bid_dir>/Sheets/control-points.csv \
     --project "<Project Name>" --grade survey|approximate \
     --title "<Sheet Title>" --out-dir <bid_dir>/Sheets \
     --crs-epsg <EPSG> --basis "<basis of bearing/coordinates prose>" \
     [--combined-factor <grid-to-ground factor>]
   ```
   `--grade` is required. The shared presentation/output flags (bid number,
   date, sheet size, scale, PDF/PNG/KML toggles) are the same across every
   `est-sheets` subcommand — see `~/.estimating/bin/est-sheets control --help` for them rather
   than a restated list here. PDF and KML are emitted by default (the PDF
   plots monochrome, CTB-style — the DXF itself keeps colors). Output lands
   as `<slug>.dxf`, `<slug>.pdf`, `<slug>.kml`, and `qc-<slug>.md` in
   `--out-dir`, slugged from `--title`.

5. **Fill in the QC report.** `~/.estimating/bin/est-sheets control` writes `qc-<slug>.md` with
   the grade/CRS/basis header and the point table already filled, but leaves
   the **Checks** section for you: record the actual tie checks, closure, and
   residuals you computed in step 2 — the Pioneer `project-control-report.md`
   pattern is the model (CRS/basis header, tie checks with residuals, the
   point table, caveats). Don't leave the placeholder text in place; if you
   ran no closure check, say so plainly rather than implying one occurred.

6. **Review with the user.** Show the DXF/PDF/KML and the filled QC report;
   confirm the grade call and the basis note read correctly before treating
   the sheet as final. Flag explicitly if the sheet is `approximate` and
   therefore not usable for construction layout.

## Notes
- `measure-plans`, `dxf-to-bim`, `bim-to-takeoff`, and `show-structure-earth` ship in this same **calc-bim plugin**. If they are not among your available skills, tell the user to reinstall calc-bim from the estimating-platform marketplace (`/plugin` -> estimating-platform -> calc-bim) and offer to continue with the bundled `est-bim` CLI directly.
- Coordinates stay in ground/published State Plane feet in the DXF and CSV
  (x = Easting, y = Northing); only the KML output converts to lon/lat
  (via each point's own `latitude`/`longitude` if present, else a
  `--crs-epsg` State Plane projection).
- Re-running with an edited CSV regenerates the DXF/PDF/KML/QC report from
  scratch — there's no partial-update mode; treat `control-points.csv` as
  the source of truth and re-run the command after every edit.
