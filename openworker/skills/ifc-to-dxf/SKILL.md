---
name: ifc-to-dxf
description: Flatten an engineer-supplied (Tekla/Revit) IFC — or one of ours — into a plan-view takeoff DXF via `est-bim ifc2dxf`, so a model with no usable Qtos/classification can enter the DXF-fed takeoff → sheets → estimate spine. Writes local files only.
---

# IFC → DXF (plan-view flatten)

Turn any IFC's element geometry — ours or a foreign Tekla/Revit export — into
the takeoff-mapped-DXF form the rest of the pipeline already consumes: world
coordinates, one closed LWPOLYLINE per element footprint, layers an office
`layer_map.yaml` can be written against. The reverse geometry route: `dxf-to-bim`
goes DXF → IFC; this goes IFC → DXF.

The deterministic pipeline is `bimforge.bim` (`est-bim` CLI).

## Prerequisites
Requires ezdxf, shapely, ifcopenshell and pyproj — all in the base install;
run `est-bim --help` to confirm. If that command is not
found, see the **Setup** block above.

## When to use
- An IFC arrives from outside the pipeline — a Tekla or Revit export handed
  over by an engineer — and it needs to enter takeoff/measurement, but it
  wasn't authored by our `dxf-to-bim` (no guarantee of `Qto_*` quantities or
  our classification scheme).
- The `bim-to-takeoff` skill found no usable quantities on an IFC (missing
  Qtos, no classification): this is the fallback geometry route — flatten
  the shapes to a DXF and re-enter through `dxf-to-bim`.

## Workflow
1. **Run the flatten:**
   ```bash
   est-bim ifc2dxf --ifc model.ifc [--out model.plan.dxf] \
       [--include IfcSlab,IfcFooting] [--exclude IfcRailing] \
       [--simplify-ft 0.05] [--sidecar qc.json]
   ```
   - `--out` defaults to `<ifc stem>.plan.dxf` beside the input.
   - `--include` / `--exclude`: comma-separated IFC class names, `is_a()`
     semantics (subtypes match); exclude wins over include.
   - `--simplify-ft`: optional ring decimation tolerance (shapely
     topology-preserving `simplify`), off by default.
   - `--sidecar`: QC sidecar JSON path (default: `<out>.sidecar.json`).
   It writes the DXF plus a JSON sidecar (per-element layer, GlobalId, Name,
   IFC class, PredefinedType, footprint area, ring/vertex counts, z_min/z_max,
   and the filter params used), and exits nonzero if zero elements produced
   plan-view geometry.
2. **Read the coordinate/georef status off the summary line and sidecar:**
   - **Georeferenced** (the IFC carries an `IfcMapConversion`): the DXF lands
     in real CRS coordinates and `$INSUNITS` follows the CRS's own unit (FT
     for a US-foot State Plane zone, M for metric). The summary prints
     `EPSG:<n> coordinates (<unit>)`.
   - **UNGEOREFERENCED** (the typical Revit/Tekla export — no map
     conversion): the DXF is local model coordinates converted to feet,
     `$INSUNITS=FT`. The summary prints `UNGEOREFERENCED — local model
     coordinates in feet`, loudly — flag this to the estimator before they
     trust absolute positions; only relative geometry (shapes, areas) is
     meaningful.
   - **Invalid georeference** (a present but broken `IfcMapConversion` — zero
     Scale, unparseable CRS) and a **geographic CRS** (lon/lat degrees
     instead of a projected CRS) both raise loud errors rather than silently
     falling back to local feet — the source file needs fixing, not the
     command.
   - The **legacy pre-0.1.11 georef error** (`|model coordinate| > 1e6 m`) can
     also fire on our own old IFCs written before est-bim's georeferencing
     was fixed — regenerate with a current `est-bim dxf2bim` rather than
     working around it here.
3. **Write a `layer_map.yaml`** against the flattened `IFCCLASS[-PREDEFINEDTYPE]`
   layers (e.g. `IFCSLAB-FLOOR`, `IFCFOOTING-PAD`, `IFCWALL`), using the
   sidecar's per-element `z_min`/`z_max` to fill in each entry's `height`.
4. **Round-trip or measure.** Either run `est-bim dxf2bim` against the new
   DXF + layer map to author a conforming IFC (see the `dxf-to-bim` skill),
   or hand the DXF to the PDF/sheet measurement path if that's the surface
   the estimator is working from.

## Known limitations
- **Hole rings** are emitted to the DXF (exterior + each hole as its own
  closed LWPOLYLINE), but `dxf2bim`'s HATCH/ring extraction does not consume
  holes yet — round-tripping a hollow footprint overcounts area until that
  lands.
- **Stacked elements** (e.g. a slab over a footing) overlap in plan view;
  filter by layer when measuring off this DXF rather than treating it as one
  flat drawing.
- **Linear elements** (walls, piles, beams) come back as their footprint
  outline, not a centerline — a wall's DXF shape is its plan-view rectangle,
  not a single line down its axis.

## Notes
- Layers never carry element names or GUIDs (those ride in the QC sidecar) —
  keeps the layer set small and predictable regardless of source-model
  naming conventions.
- `PredefinedType` values of `NOTDEFINED`/`USERDEFINED` are treated as noise
  and dropped from the layer name (just `IFCWALL`, not `IFCWALL-NOTDEFINED`).
