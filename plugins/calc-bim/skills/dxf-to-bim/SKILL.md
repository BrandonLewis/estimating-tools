---
name: dxf-to-bim
description: Author BIM (IFC) from measurements taken directly off 2D DXF plans. Use when the user has a DXF/CAD drawing and wants to turn measured geometry (areas, lengths, counts) into an IFC model with quantities and cost-code classification for estimating or visualization. Triggers include "DXF to BIM", "IFC from plans", "model my takeoff", "measure off the drawing into BIM", "turn CAD into IFC".
---

# DXF → BIM (IFC)

Turn measurements taken off a 2D DXF into a valid, georeferenced IFC model whose
elements carry base quantities (`Qto_*`) and cost-code classifications. Built to
feed an estimating workflow, not just a viewer.

The deterministic pipeline is `bimforge.bim` (`est-bim` CLI).

## Prerequisites
Requires ezdxf, shapely, ifcopenshell and numpy — all in the base install;
run `~/.estimating/bin/est-bim --help` to confirm. If that command is not
found, see the **Setup** block above.

## Workflow
1. **Get the DXF.** Confirm the drawing file and its drawing units
   (mm / cm / m / ft / in). If unknown, inspect with ezdxf or ask the user.
   (No drawing yet? `~/.estimating/bin/est-bim sample --dir demo --with-configs` writes a sample
   plan DXF plus matching example maps so the pipeline runs out of the box.)
2. **Build/confirm the layer map.** Start from the shipped
   `layer_map.example.yaml` (written by `~/.estimating/bin/est-bim sample --with-configs`) and
   edit one entry per DXF layer the user wants modeled. Each entry sets:
   - `ifc_class` (e.g. IfcSlab, IfcWall, IfcColumn, IfcBuildingElementProxy)
   - `feature`: `area` (closed polylines / hatches → Area, Perimeter, Volume),
     `linear` (open polylines / lines → Length + ribbon of `width`), or
     `count` (block INSERTs → one element each, Count = 1)
   - `height` (extrusion / thickness), and for linear, `width`
   - `classification` `{system, code, name}` — **this is the cost-code link**;
     make it match the estimate's coding (Caltrans item code, MasterFormat,
     Uniclass, or the org's own codes)
   - optional `properties` (custom Psets)
   Set `units.dxf_length_unit` and, if the DXF has real survey coordinates,
   `georeference.crs_epsg` so the model round-trips to KML/GIS. Choosing that
   CRS + vertical datum is trap-prone (ftUS-vs-metre EPSG rescale, NGVD29 vs
   NAVD88) — see the georeferencing reference in build-structure
   (`../build-structure/references/georeferencing.md`).
3. **Run the pipeline:**
   ```bash
   ~/.estimating/bin/est-bim dxf2bim --dxf <plans.dxf> --config <layer_map.yaml> --out model.ifc
   ```
   It reports how many features were extracted per layer and writes `model.ifc`.
4. **Verify before trusting it.** Re-open the IFC and check schema validity
   and element counts per class:
   ```bash
   ~/.estimating/bin/est-bim validate model.ifc
   ```
   (exit 0 prints the per-class count table + `schema issues: 0`; exit 1 means
   schema issues or an unreadable file — fix before proceeding.)
   Report the per-layer counts and any skipped entities (printed to stderr) to
   the user; never silently drop geometry.
5. **Hand off.** The IFC is now input to the `bim-to-takeoff` skill (quantities →
   bid items) and/or a viewer (Bonsai, FreeCAD BIM).

## Notes
- Linear runs are drawn as a buffered ribbon for visibility; the stored
  **Length is the exact centerline** (the ribbon is cosmetic).
- Schema defaults to **IFC4X3_ADD2**, the civil schema (alignments, the
  facility tree, earthworks classes). Navisworks, Revit, Solibri, BIMcollab
  and most browser viewers cannot open IFC4X3 at all — they show an empty
  model and raise no error, which nobody can tell from a broken export. When
  the file is going to one of those, set `schema: IFC4` and say so;
  `~/.estimating/bin/est-bim build` prints a note whenever it has to downgrade a 4X3-only
  class (e.g. `IfcEarthworksFill`) to fit IFC4.
- Hatches with island holes: switch to IfcOpenShell's arbitrary-profile-with-voids
  API (extension point noted in `bimforge/bim/dxf2bim.py`).

## Related skills
- `ifc-to-dxf` — the reverse geometry route: flattens any IFC (ours or a
  foreign Tekla/Revit export) back into a plan-view DXF, for models that
  arrive without a DXF origin.
