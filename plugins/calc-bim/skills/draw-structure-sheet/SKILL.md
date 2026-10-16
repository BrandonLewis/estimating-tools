---
name: draw-structure-sheet
description: Frame a structure's takeoff-mapped DXF into a submittable structure sheet — title block + fitted viewport added around the existing geometry, source modelspace untouched — as `<id>.sheet.dxf` plus PDF/PNG and a QC report, via the `est-sheets` CLI (bimforge.sheets + bimforge.cad). Use per briefed structure after its takeoff DXF exists, so the same file that drives the sheet also drives the calc-bim plugin's `dxf-to-bim`/`bim-to-takeoff`. Writes local files only, under the bid working dir's `Sheets/` (and `BIM/` for the source DXF).
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If `~/.estimating/bin/est-sheets --help` fails, run `python <calc-bim plugin root>/scripts/ensure_tools.py`; it builds the shared runtime and prints one line saying what happened. Then retry.

# Draw a Structure Sheet (est-sheets structure)

Frame an existing takeoff-mapped DXF — one drawn on `layer_map.yaml` layers,
ready for `dxf-to-bim` — into a submittable sheet: verify every drawn layer
is BIM-mapped (or a recognized annotation layer), add the bundled title-block
layout with a fitted viewport, and save the result as a **new** file. The
source DXF's modelspace is never rewritten, so it stays the exact input
`dxf-to-bim`/`bim-to-takeoff` consume — one file serves sheet, BIM, and
takeoff.

## Prerequisites
The sheet engine ships inside bimforge, and matplotlib (for PDF/PNG) is in the
base install. Run `~/.estimating/bin/est-sheets --help` to confirm; if that
command is not found, see the **Setup** block above.

## Grade discipline

`--grade` is required for structure sheets, same rule as control: `survey`
when the structure's geometry is tied to published control (or the sheet
carries an honest local-grid basis with recoverable ties — Work-repo
practice allows "no coordinate control anywhere in the plans" cases with a
stated local origin, which is still a defensible `survey`-style claim if the
local grid is internally consistent and documented), `approximate` when it
isn't. `approximate` stamps the NOT FOR CONSTRUCTION LAYOUT caveat into the
sheet's paperspace (not modelspace, so it never perturbs the BIM geometry)
and should match whatever grade the project's control/layout sheets already
carry. Never present an approximate structure sheet as construction-layout
geometry. (Canonical grade rule: the `drafting-agent` agent.)

## Workflow

1. **Read the structure's briefing frontmatter.** Open
   `Briefing/prompts/<structure_id>.md` and extract the frontmatter block by
   its line-anchored `---` delimiters (first line to the next line-anchored
   `---` — never substring-split, the prose below may contain horizontal
   rules). Pull `structure_id`, `cost_codes`, `bid_items`, and `count` — they
   scope what this sheet is for and how many identical units it represents.

2. **Produce the takeoff-mapped DXF.** If it doesn't already exist, use the
   `measure-plans` skill to calibrate the relevant plan sheet, extract
   vectors, trace the structure's geometry, and measure it against the
   project's `layer_map.yaml` — saving the result into
   `<bid_dir>/BIM/<structure_id>.dxf`. A hand-drawn DXF is acceptable too, as
   long as it follows the same layer-map contract (closed LWPOLYLINE for
   `area` features, open for `linear`, `INSERT` for `count`;
   `$INSUNITS=FT`). This file is the one both this sheet and
   `dxf-to-bim`/`bim-to-takeoff` will consume — don't create a separate
   "sheet" drawing.

3. **Frame it into a sheet:**
   ```bash
   ~/.estimating/bin/est-sheets structure <bid_dir>/BIM/<structure_id>.dxf \
     --layer-map <bid_dir>/Takeoff/layer_map.yaml \
     --project "<Project Name>" --grade survey|approximate \
     --title "<STRUCTURE NAME>" --out-dir <bid_dir>/Sheets \
     [--crs-epsg <EPSG>]
   ```
   `--layer-map` and `--grade` are both required. The command reads every
   layer actually used in the source DXF's modelspace and rejects the run
   (nonzero exit, no output written) if any layer isn't in the layer map's
   `layers:` block and isn't a recognized annotation layer
   (`C-ANNO-TEXT`, `S-ANNO-SYMB`, `DEFPOINTS`, `0`) — that failure means the
   sheet would not be BIM-ready and the layer map (or the drawing) needs
   fixing before re-running, not a flag to work around. The shared
   presentation/output flags (bid number, date, sheet size, scale, PDF/PNG
   toggles) are the same across every `est-sheets` subcommand — see
   `~/.estimating/bin/est-sheets structure --help` for them rather than a restated list here.
   PDF is emitted by default (it plots monochrome, CTB-style — the DXF keeps
   colors). Structure sheets have no `--kml` option (they rarely have a
   derivable CRS). Output is `<slug>.sheet.dxf` (note the `.sheet.dxf`
   suffix, distinct from the source `<structure_id>.dxf`) plus `qc-<slug>.md`
   in `--out-dir`, slugged from `--title`.

4. **Verify the framed sheet.** Open the `.sheet.dxf` and confirm the
   viewport frames the structure's full extents, the title block fields read
   correctly (project, structure name, scale, grade caveat if approximate),
   and — critically — that modelspace geometry is unchanged from the source
   file (the command guarantees this, but a visual spot-check catches a
   wrong `--layer-map` path before it reaches `dxf-to-bim`).

5. **Fill in the QC report.** `~/.estimating/bin/est-sheets structure` writes `qc-<slug>.md`
   with the grade/CRS/basis header and a summary of the source DXF (filename,
   layers used, entity count) already filled, but leaves the **Checks**
   section for you: record whatever BIM-readiness verification you actually
   did in step 4. Don't leave the placeholder text in place.

6. **Note the shared-file relationship to the user:** the source DXF in
   `BIM/` is untouched and remains the `dxf-to-bim` input; the sheet in
   `Sheets/` is a separate framed copy for review/submittal. Sheet, BIM, and
   takeoff for this structure all trace to the same modelspace geometry —
   if the structure's geometry changes, re-run `measure-plans` (or hand-edit
   the source DXF) and re-run this command, `dxf-to-bim`, and
   `bim-to-takeoff` together so all three stay consistent.

## Notes
- `measure-plans`, `dxf-to-bim`, `bim-to-takeoff`, and `show-structure-earth` ship in this same **calc-bim plugin**. If they are not among your available skills, tell the user to reinstall calc-bim from the estimating-platform marketplace (`/plugin` -> estimating-platform -> calc-bim) and offer to continue with the bundled `est-bim` CLI directly.
- The grade caveat, when present, is stamped into the sheet's *paperspace*
  near the border — never into modelspace — so the BIM source of truth is
  byte-for-byte the same geometry a reviewer sees framed on the sheet.
- Coordinates may be local grid (per Work-repo practice, e.g. "West headwall
  invert pinned at local N 5000, E 5000") when the plans carry no site-wide
  control; state that plainly in the sheet title/notes rather than implying
  State Plane coordinates that don't exist.
