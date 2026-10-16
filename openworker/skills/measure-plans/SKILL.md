---
name: measure-plans
description: Measure quantities directly off vector PDF plan sheets with CAD precision. Use when the bid set is a PDF (no CAD files) and the user wants takeoff geometry from the plan sheets. Auto-calibrates from geometric evidence (station ticks, grids, scale bars) plus vision hints you author from the rendered lettering — flattened signed sets included — then extracts vector linework and closed regions, snaps traced geometry onto the vectors, cross-checks every measurement against the lettered dimensions, and emits the takeoff-mapped DXF that dxf-to-bim consumes. Triggers include "measure the plans", "takeoff from the PDF", "scale off the sheet", "trace the plan sheet", "PDF to DXF measurement".
---

# Measure PDF Plan Sheets (est-bim calibrate / vectors / measure)

Agency plan sets are plotted from CAD — a vector PDF's paths ARE the
geometry. This workflow recovers them: calibrate the sheet's page→world
transform from pooled evidence, dump the linework and closed regions as a
tracing surface, trace (or pick regions for) the features you care about,
snap every vertex onto the extracted vectors, and cross-check the result
against the engineer's own lettering. The output is the same takeoff-mapped
DXF the `dxf-to-bim` skill consumes — one pipeline, new front door.

Signed bid sets are routinely FLATTENED: every letter is vector outlines and
the PDF has no text layer. est-bim stays deterministic and never reads
pixels — **you** are the vision. You render the sheet, read the lettering,
and write a hints file; the code validates your readings against the vector
geometry and only accepts a scale when independent sources agree. Vision
proposes, vectors confirm.

## Prerequisites
Requires pymupdf, ezdxf, shapely and friends — all in the base install;
run `est-bim --help` to confirm. If that command is not
found, see the **Setup** block above.

## Workflow

1. **Render the sheet and read it.**
   ```bash
   est-bim calibrate --pdf plans.pdf --sheet 13 --render sheet13.png --dpi 150
   ```
   The command prints the pt-per-pixel factor (72/dpi) and, if calibration
   cannot auto-accept yet, exits 2 with a machine-readable evidence report —
   that is normal on the first pass. Look at the PNG: identify the view
   zones (PLAN, ELEVATION, TYPICAL SECTION — each has its own scale), and
   READ the lettering: dimension strings, scale notes, station labels.

2. **Write the hints file** — what the flattened lettering says and roughly
   where (visual page points = pixel coords x the printed pt-per-pixel):
   ```yaml
   frame: visual
   zone_hints:
     - zone: plan                 # optional; omit to match by location
       kind: dimension
       text: "45'-0\""
       near_pt: [471.6, 208.0]    # near the dimension line it letters
     - kind: station_label
       text: "106+00"
       near_pt: [613.7, 461.4]    # near its station tick
     - kind: scale_note
       text: "1/8\" = 1'-0\""     # title blocks lie; half weight, never
       near_pt: [482.8, 784.1]    # accepted alone
   ```
   Dimension hints pair with nearby vector segments; station-label pairs
   anchor to detected tick crossings; scale notes only corroborate.

3. **Calibrate:**
   ```bash
   est-bim calibrate --pdf plans.pdf --sheet 13 --hints hints.yaml \
     [--zone name:x0,y0,x1,y1] [--evidence evidence.json] --out calib/sheet-13.yaml
   ```
   Evidence is pooled per zone from station ticks, grid lines, scale bars
   (pure vector — immune to flattening), live text dimensions (when a text
   layer survives), and your hints. A zone auto-accepts only when >=2
   independent source types agree within 0.5% and at least one is a measured
   value — geometric spacings alone are hypotheses ({1, 5, 10, 20, 25, 50,
   100} ft) and never self-confirm. This is what catches half-size plots:
   a 12x18 print of a 24x36 sheet halves the true scale, the lettered scale
   note is then CONTRADICTED in the output, and the accepted value comes
   from ticks + your dimension readings.
   - **Exit 2** means no consensus: the evidence report lists every
     candidate and cluster — see which value your hints confirmed, add the
     missing hint, and re-run. If it exits 2 twice with hints supplied, some
     sheets genuinely offer only ONE independent source (their own
     lettering); confirm the hint-cluster value with a human, then pass it
     explicitly as `--ft-per-pt` (the calibration records it as manual).
   - Multi-scale sheets need `--zone` per view (unrotated page points);
     never calibrate a full page that mixes 1/8" and 1/4" views.

4. **Extract the tracing surface (+ regions):**
   ```bash
   est-bim vectors --pdf plans.pdf --sheet 13 --calib calib/sheet-13.yaml \
     --classes classes.yaml --regions --regions-json regions.json --out vectors.dxf
   ```
   Paths land in world feet, one layer per style class: `V-<CLASS>` when
   `--classes` maps the legend's dash patterns (see
   `plansheet/classes.example.yaml`), else `V-SOLID` / `V-DASH-<hash>`.
   `--regions` polygonizes the linework into closed faces on
   `V-REGION-<class>` layers, sorted by area with centroids and SY in the
   JSON — prefer picking region faces (and summing adjacent faces split by
   interior lines) over re-tracing boundaries. Hatch-symbol curves are
   excluded automatically.

5. **Trace.** Reading the render and the regions JSON, write `traces.json`
   in world feet:
   ```json
   {"layers": {"S-DECK": [{"closed": true, "points": [[38.8, 24.0], [83.8, 24.0], [83.8, 54.0], [38.8, 54.0]]}],
               "S-PILE": [{"points": [[45.2, 39.1]]}]}}
   ```
   Points only need to be eyeball-close (within the snap tolerance, default
   0.15 ft) — snapping supplies the precision. Every layer must exist in the
   project's `layer_map.yaml`; `count` layers take exactly one point per
   trace. With multiple zones, each trace carries a `"zone"` key.

6. **Measure + QC:**
   ```bash
   est-bim measure --pdf plans.pdf --sheet 13 --calib calib/sheet-13.yaml \
     --traces traces.json --layer-map layer_map.yaml --hints hints.yaml \
     --out structure.dxf --sidecar prov.json --report qc.md
   ```
   Every vertex snaps to the nearest extracted vector endpoint/segment
   within `--tol`. Unsnapped vertices exit nonzero — re-trace them or
   consciously pass `--allow-unsnapped`. The cross-check compares each
   measured entity against the lettered dimensions near it (live text, or
   your dimension hints on flattened sheets): OK within `--qc-tol` (default
   0.5%), REVIEW above it, UNVERIFIED when nothing lettered is close.
   REVIEW rows set `"confidence": "review"` in the sidecar and block the
   takeoff from being called high-confidence; UNVERIFIED entities are
   listed, never dropped. Give the user the qc.md table — it is the
   bid-day credibility artifact.

7. **Hand off.** `structure.dxf` is in world feet (`dxf_length_unit: ft`):
   feed it to the `dxf-to-bim` skill to author the IFC, then
   `bim-to-takeoff` for quantities. Report the calibration method and
   sources, residuals, contradicted hints, and the QC counts — quantities
   inherit the calibration confidence of their zone.

## Contours off a flattened sheet (est-bim contours / contour-surface)

Agency CONTOUR GRADING sheets draw existing topo and proposed grading as
different pen styles on one page; a signed set is flattened (no text
layer) but the linework is exact CAD geometry. The discipline:

- **The pen table IS the layer table.** Select contours by `grey[@width]`
  pen style (`est-bim contours --profile` first to see what pens the
  sheet actually uses) — never by proximity or guesswork.
- **Anchors are read visually.** Contour labels are outlined glyphs, not
  text: elevations come from a human-read anchors file, and every contour
  records its tier — `lettered` (carries a read label) or `inferred`
  (`--propagate`, off by default: an unlabelled contour gets the one value
  every label and `--role` pen role allow it, and only when interpolating
  between the lettered contours either side agrees within the snap
  tolerance). Never present inferred elevations as lettered.
- **Contours that do not reconcile are findings, not noise.** Redrawing is
  plan verification. `contour-surface` reports every conflict between
  labels (both kept — the report names the one label whose removal would
  reconcile the rest, when there is one), contours that cross or touch, and
  labels that attach to nothing, each with the neighbour paths behind it.
  Classify every finding — plan issue, extraction artefact, or a real wall
  or grade break — before calling the surface good; `--strict` exits 2
  while any remain. Leave `--merge-gap` off unless the sheet breaks its
  contours at the labels.
  Pass `--review-dir DIR --pdf plans.pdf` for an overlay crop of every
  finding (the traced lines drawn over the sheet with their ids and values)
  and look at each before classifying it.
- **Spot elevations are the scorecard, never TIN vertices.** By default
  they are held out and score the TIN (`--spots`); the RMSE is the
  surface's credibility number and rides its provenance into the model.
  `--spot-pins` also makes them a consistency check: a spot that
  contradicts a label or a run of contours becomes a `conflict` finding,
  and the spots narrow the ranges reported in `lines.csv` and the report.
  It never adds a contour to the TIN — only labels make a contour
  assignable, so flat ground the labels leave open stays open — and it
  withdraws an assigned contour that a spot contradicts; with
  `--propagate` the scorecard is then leave-one-out.
- The result is `grade: approximate` terrain like every other
  reconstructed surface — the canonical grade rule (drafting-agent)
  applies unchanged.

## Notes
- Views are assumed axis-aligned to the sheet (rotation from the page's
  /Rotate only); zones and alignments are explicit, never auto-detected.
- Slope-face quantities: a plan footprint understates sloped work. When the
  details show material following a 2:1 slope, correct the plan area by
  sec(atan(1/2)) ≈ 1.118 and add what the details show at terminations
  (toe keys, edge steps) — measure the detail, don't assume.
- Raster (scanned) sheets have no vector paths — this workflow does not
  apply to them; say so rather than eyeballing.
