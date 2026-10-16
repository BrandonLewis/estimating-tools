---
name: draw-layout-sheet
description: Draw a layout sheet — the chord alignment with station ticks and labels, plus structure markers by station/offset — as DXF, PDF, a QC report, and (when a CRS is known) KML, via the `est-sheets` CLI (bimforge.sheets + bimforge.cad). Use after `draw-control-sheet`/`project-briefing` when the bid needs alignment/stationing geometry drawn from the plans. Writes local files only, under the bid working dir's `Sheets/`.
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Draw a Layout Sheet (est-sheets layout)

Render the bid's alignment as a submittable sheet: a chord centerline on
`C-ROAD-CNTR`, station ticks and labels at a fixed interval, and structure
markers dropped at each briefed structure's station/offset/side. Ground
coordinates stay in the DXF (x = Easting, y = Northing); curves are
annotation only — there is no COGO curve engine in this pipeline, so the
alignment is a sequence of straight chords between computed points.

## Prerequisites
The sheet engine ships inside bimforge, and matplotlib (for PDF/PNG) is in the
base install. Run `est-sheets --help` to confirm; if that
command is not found, see the **Setup** block above.

## Grade discipline

The layout sheet's `--grade` should normally match the control sheet it
builds on (`survey` if the alignment is tied to published control with a
closure check, `approximate` if georeferenced from imagery/plan callouts
with no such tie). `est-sheets layout` will fall back to a `grade:` key in
the alignment YAML if `--grade` is omitted on the command line, but don't
rely on the fallback silently — state the grade explicitly and carry it
through from the control sheet. An `approximate` alignment stamps the same
NOT FOR CONSTRUCTION LAYOUT caveat onto this sheet; never hand it over as
layout-grade geometry. (Canonical grade rule: the `drafting-agent` agent.)

## Workflow

1. **Derive the alignment.** Pull station/northing/easting chord points from
   the plan geometry: use `measure-plans` (calc-bim plugin; calibrate/vectors/trace) when the
   plans give only drawn geometry, or read stated coordinates directly off a
   plan/profile sheet via `pdf-extraction` when a coordinate table exists.
   Curve data (PI, radius, length) is fine to note in your working record,
   but the alignment YAML itself only takes straight chords between stations
   — pick enough intermediate points that the chords track the true
   alignment closely (e.g. every PC/PT and a few points along each curve).

2. **Author `alignment.yaml`** under `<bid_dir>/Sheets/`:
   ```yaml
   name: <alignment name>
   grade: survey  # or approximate — optional here if you pass --grade
   crs_epsg: <EPSG>  # optional
   points:
     - {station: 0.0,    northing: 5000.00, easting: 5000.00}
     - {station: 125.40, northing: 5124.80, easting: 5012.10}
     - {station: 300.00, northing: 5298.50, easting: 5040.00}
   ```
   Stations must strictly increase down the list (at least two points).
   `grade` and `crs_epsg` are optional in the YAML — pass `--grade`/
   `--crs-epsg` on the command line instead, or set them here; a CLI flag
   always overrides the YAML value.

3. **Author `structures.json`** (optional but expected whenever the bid has
   briefed structures along this alignment) — one entry per structure the
   sheet should mark, ids pulled from `Briefing/prompts/*.md` frontmatter:
   ```json
   [
     {"structure_id": "headwall-01", "station": 112.0, "offset_ft": 18.0, "side": "RT"},
     {"structure_id": "culvert-a",  "station": 240.5, "offset_ft": 0.0,  "side": "RT"}
   ]
   ```
   `side` is `RT` or `LT` (looking up-station); omit `offset_ft`/`side` only
   for on-centerline structures (they default to `0.0`/`RT`).

4. **Render the sheet:**
   ```bash
   est-sheets layout <bid_dir>/Sheets/alignment.yaml \
     --structures <bid_dir>/Sheets/structures.json \
     --project "<Project Name>" --grade survey|approximate \
     --title "<Sheet Title>" --out-dir <bid_dir>/Sheets \
     [--tick-interval 100] [--crs-epsg <EPSG>]
   ```
   `--grade` is optional here only in the sense that it falls back to the
   YAML's `grade:` key — always know which grade you're claiming.
   `--tick-interval` (feet) defaults to `100`. The shared presentation/output
   flags (bid number, date, sheet size, scale, PDF/PNG/KML toggles) are the
   same across every `est-sheets` subcommand — see `est-sheets layout --help`
   for them rather than a restated list here. PDF is emitted by default (it
   plots monochrome, CTB-style — the DXF keeps colors); the KML — the
   alignment centerline (a linestring) plus a point per briefed structure —
   is on by default too but only produces a file when a CRS is derivable
   (`--crs-epsg` or the alignment YAML's `crs_epsg:`). Output lands as
   `<slug>.dxf`, `<slug>.pdf`, `<slug>.kml` (when a CRS is known), and
   `qc-<slug>.md` in `--out-dir`, slugged from `--title`.

5. **Verify structure markers against the plans.** Re-check each marked
   structure's station/offset/side against the plan sheet it came from —
   this is the step most likely to hide a transcription error (wrong side,
   swapped station/offset). Confirm marker labels match `Briefing/prompts/
   <structure_id>.md` ids exactly.

6. **Fill in the QC report.** `est-sheets layout` writes `qc-<slug>.md` with
   the grade/CRS/basis header, the alignment point table, and the structure-
   marker table already filled, but leaves the **Checks** section for you:
   record whatever verification you actually did in step 5 (plan cross-
   checks, any closure/tie computations carried over from the control
   sheet). Don't leave the placeholder text in place.

7. **Review with the user.** Show the DXF/PDF (and KML if produced); confirm
   the alignment tracks the plans and the structure markers land where
   expected before treating the sheet as final.

## Notes
- `measure-plans`, `dxf-to-bim`, `bim-to-takeoff`, and `show-structure-earth` ship in this same **calc-bim plugin**. If they are not among your available skills, tell the user to reinstall calc-bim from the estimating-platform marketplace (`/plugin` -> estimating-platform -> calc-bim) and offer to continue with the bundled `est-bim` CLI directly.
- Offsets are measured looking up-station: `RT` is +90° clockwise from the
  chord direction, `LT` is the mirror.
- Re-running with an edited `alignment.yaml`/`structures.json` regenerates
  the DXF/PDF/KML from scratch — treat them as the source of truth and
  re-run the command after every edit.
