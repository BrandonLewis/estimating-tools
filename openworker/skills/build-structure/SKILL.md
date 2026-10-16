---
name: build-structure
description: Build a parametric structure model — spec YAML in, gate-validated DXF + IFC + takeoff-map (+ QTO/STEP) out, via `est-bim build` (bimforge.author). Use whenever a briefed structure needs modelled quantities instead of hand math: if a shipped family fits (pipe supports, standard-plan walls, box culvert, bridge, barriers, headwall/wingwall) run it; if none fits, this skill hands off to `author-structure-model` for the bespoke path — an unmatched structure stays in BIM, it does not fall back to hand math. Triggers include "build the IFC model", "build the structure model", "model project X's structures", "make the bridge/wall/culvert model", "parametric takeoff", "reconcile IFC quantities", "est-bim build", "run the family".
---

# Build Structure (`est-bim build`)

Turn a transcribed parameter spec into gate-validated CAD/BIM/takeoff
outputs. The family computes every quantity closed-form; the validation gate
runs FIRST and nothing is written if any check fails; the emitted IFC is the
ONE source the takeoff is derived from (`bim-to-takeoff`).

## Prerequisites
Requires ezdxf, shapely, ifcopenshell and numpy — all in the base install; run
`est-bim --help` to confirm. If that command is not found,
see the **Setup** block above.

STEP output additionally needs build123d, the `solids` extra, which the base
install omits. Install it into whichever interpreter runs `est-bim`:

- **Under the plugins**, it is the interpreter they keep under
  `~/.estimating/`, reached only by `ensure-extra solids`;
  a bare `pip install` would land somewhere else and change nothing here.
- **Installed by pip instead**, it is `pip install "bimforge[solids]"`.

## Workflow
1. **Pick the family — run this FIRST, before concluding a structure is unmodelled.**
   `python -c "from bimforge.author.families.registry import available; print(sorted(available()))"`

   The 14 shipped families, by what they model:

   | | |
   |---|---|
   | bridge | `bridge-standard`, `approach-slab` |
   | barriers & rail | `concrete-barrier-842`, `concrete-barrier-732sw`, `tubular-handrail` |
   | culverts & headwalls | `box-culvert`, `culvert-headwall`, `culvert-wingwall`, `pipe-headwall`, `headwall-926` |
   | walls | `standard-plan` |
   | other | `pipe-supports`, `spillway`, `demo-box` (try-it fixture) |

   That command is the authority, and `tests/test_skill_family_list.py` fails if
   this table and `available()` disagree — so the table is current, but the command
   is still what to trust after a plugin bump. An earlier version of this step
   listed 8 of 14, and a session read the list instead of running the command,
   concluded there was no modelling route at all, and hand-briefed a bespoke
   build — when seven families covered MOST of that bridge and EVERY minor
   structure on the job.

   Partial coverage is the normal case, not a failure of either route. A family
   models what it models: `bridge-standard` has no piles, pile caps/footings,
   flared columns, width flare or wingwalls, so those parts are authored bespoke
   or federated in beside the family's output. Do not stretch a family over
   geometry it does not support, and do not abandon families because one part of a
   structure needs bespoke work.

   **Also check the consumer repo's own family directory.** Bid-side packages can
   register through the entry-point group `bimforge.families`, but a consumer repo
   may instead keep families as loose modules discovered only by its own builder
   (e.g. a `bimforge_families/` directory whose `build.py` scans itself). Those
   never appear in `available()`, and they are often exactly the pile, pile-cap,
   wingwall and station/profile placement code `bridge-standard` lacks. Grep the
   consumer repo for `FAMILIES` before deciding nothing fits.
   A structure matching NO family is NOT out of scope: author it directly over
   `bimforge.author` with the **`author-structure-model`** skill (same gate,
   same determinism, same IFC-is-the-one-source discipline) — a first-class
   route, not a failure, and never a reason to fall back to hand math.
2. **Author the spec** (`<structure>.spec.yaml` in the bid working dir):
   ```yaml
   family: pipe-supports
   params: { ... }          # family-specific; EVERY dimension cites its sheet
   paycodes: ./paycodes.yaml
   outputs: {dxf: CAD/x.dxf, ifc: CAD/x.ifc,
             takeoff_map: CAD/x-takeoff-map.yaml, qto: CAD/x-QTO.xlsx,
             step: null}
   project: {name: "...", epsg: 2226, base: [E, N, H], guid_ns: "<uuid4>"}
   # schema defaults to IFC4X3_ADD2; `project.schema: IFC4` for a viewer that
   # cannot read 4X3. Optional, 4X3 only: a bridge/road facility tree:
   #   project.facility: {kind: bridge, name: "...", predefined_type: GIRDER}
   #   spatial_parts: [{match: "(?i)abut", part: ABUTMENT}, ...]
   ```
   Transcribe-then-verify discipline: params are a CITABLE TRANSCRIPTION
   (`read-station-plans` skill), never scaled guesses. Dimensions the sheets
   do not give go in the family's `assumptions` list WITH a reason — the gate
   refuses a bare one. No survey control on the set? You must set
   `outputs.ifc_allow_local: true` explicitly; the kernel refuses a silently
   local IFC. Choosing `epsg` + `base` (projected CRS, vertical datum,
   base-point-at-monument) is trap-prone — the ftUS-vs-metre EPSG rescale, NGVD29
   vs NAVD88 — so see the georeferencing reference
   (`references/georeferencing.md`): State Plane zones, VERTCON/geoid via
   `bimforge.terrain.datum`, and the common EPSG pitfalls.
   **Bridge/road navigation tree (opt-in).** Under the default IFC4X3_ADD2,
   `project.facility` writes IfcSite > IfcBridge/IfcRoad/... > parts instead of
   IfcBuilding > IfcBuildingStorey. Elements are placed in parts
   (ABUTMENT/DECK/...) by `spatial_parts:` rules. A `schema: IFC4` spec
   ignores it. See `references/ifc4x3-facility.md`.
3. **Gate first:** `est-bim build <spec.yaml> --check-only`. Every failure
   prints together. A failure means the SPEC or the reading is wrong —
   fix the transcription or escalate the ambiguity to the human; do not
   loosen a check to make it pass.
4. **Build:** `est-bim build <spec.yaml>`. Writes DXF + IFC + generated
   takeoff map (+ QTO workbook, + STEP with the `[solids]` extra), then
   post-verifies the written files (mesh-vs-analytic volumes, takeoff-map
   coverage) and DELETES them on failure.
5. **Verify + hand off.** Derive the takeoff from the IFC with
   `bim-to-takeoff` (uses the generated map); frame the DXF into a sheet
   with `draw-structure-sheet`; `show-structure-earth` for a KML check when
   georeferenced. Estimate-layer pushes stay in estimating-core
   (`push-takeoff`).

## Site-context terrain (bimforge.terrain)

Attach USGS 3DEP existing ground to a model with
`bimforge.terrain.attach_terrain` (sources: `dem` 1 m raster, `lpc` lidar
bare-earth). Judgment rules, hard-won on a live bridge bid:

- **Two independent sources before trusting either.** Grid the DEM and the
  lidar identically and compare (the source arc tied them to RMSE 0.070 m)
  — the terrain instance of measure-plans' "≥2 independent source types
  agree" calibration discipline.
- **CRS comes from the data's own header, never the filename.** A
  filename-guessed CRS silently shifts the whole terrain; lidar tiles are
  read via `las.header.parse_crs()` with compound-CRS unwrap.
- **Let the boolean prove the classification.** Carving cuts into the
  terrain SOLID makes above-terrain digs (future embankment fill) no-ops
  by geometry — what gets removed is exactly existing-ground dig. Use the
  reported removed volume as a check, not a pay quantity.
- **Terrain is reference geometry** — no pay code, no Qto, SurveyGrade
  False; provenance (source, work-unit vintage, quality level, applied
  datum shift) rides the element as `Pset_BimforgeTerrain`.
- **Heavy deps are optional.** Pillow/laspy/trimesh degrade with a logged
  message; they are the `terrain` extra, installed the same way `solids` is
  (see Prerequisites). A failed
  carve falls back to the open surface — the build never hard-fails on a
  missing optional capability.

## Notes
- The takeoff map is GENERATED from paycodes.yaml — never hand-edit it;
  change the paycodes table and rebuild.
- Declared Qto comes from the faces of the emitted solid, not from a
  section-area × centreline-length shortcut — that shortcut is wrong by a
  few percent on battered/mitred geometry (mitred corners overlap, batter
  varies the section). The kernel's `BatteredWall`/`SectionPrism`
  primitives carry face-derived volumes by construction; hand math that
  checks a Qto must integrate the same faces.
- **Curved structures follow an alignment, not a chopped polyline.** A
  section swept along a traverse (compound radii, vertical curves,
  superelevation, camber) is one solid whose declared volume is the
  closed-form Pappus integral, gate-checked against the faceted loft —
  `bridge-standard` is the worked case. Straight/kinked runs still belong
  to `SectionPrism`/`BatteredWall`; a swept run REFUSES a plan kink,
  because a road or bridge turns on a curve, not an angle point.
- Deterministic outputs: an unchanged spec rebuilds byte-identical files
  (stable GUIDs from `project.guid_ns`) — commit-friendly.
- `demo-box` is the neutral try-it family:
  `est-bim build $(python -c "import bimforge.author, pathlib; print(pathlib.Path(bimforge.author.__file__).parent / 'examples' / 'demo-box.spec.yaml')") --check-only`.

## Related skills
- `author-structure-model` — the bespoke route: hand-author a `StructureModel`
  over `bimforge.author` when no registered family fits. Same gate and
  determinism; use it instead of hand math for any unmatched structure.
- `read-station-plans` — transcribe the citable parameters a spec is built from.
- `bim-to-takeoff` — derive bid quantities from the emitted IFC.
- `draw-structure-sheet` / `show-structure-earth` — sheet framing and the KML
  georeference check.
