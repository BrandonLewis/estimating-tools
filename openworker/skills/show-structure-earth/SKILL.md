---
name: show-structure-earth
description: Convert a georeferenced IFC (structure model) into a KMZ that opens in Google Earth on the web, and view it there. Use when the user wants to "see the structure in Google Earth", "fly to the model", or otherwise view a BIM model in its real-world geographic context. Triggers include "show me this in Google Earth", "IFC to KMZ", "put the model on the map", "3D view of the structure".
---

# Show a Structure in Google Earth (IFC → KMZ)

Turn a georeferenced IFC (typically `dxf-to-bim` output) into a KMZ and place it
in Google Earth at the structure's real-world location. By default the KMZ is
**Google Earth web** KML: one placemark of polygons per element, in folders by
pay item, as `doc.kml` inside the zip. Earth for web and mobile cannot import a
KML `<Model>` ("Unsupported element: Model"), and Google Earth Pro (desktop),
the only viewer that draws one, is deprecated, so the old COLLADA package is
opt-in (`--collada`).

## Prerequisites
Requires ifcopenshell and pyproj — the same base install as `dxf-to-bim`; run
`est-bim --help` to confirm. If that command is not found,
see the **Setup** block above.

The IFC must be **georeferenced** (an `IfcMapConversion` + `IfcProjectedCRS`,
set via the `dxf-to-bim` layer map's `georeference.crs_epsg` or `zone:`), and
must have been authored with **est-bim >= 0.1.11**. Earlier versions wrote a
broken georeference (base coordinates subtracted without unit conversion);
`est-bim kmz` detects and rejects those models with a clear error rather than
placing them somewhere wrong — regenerate the IFC with a current est-bim if
you hit it.

## Workflow
1. **Confirm the IFC is georeferenced.** If it came from `dxf-to-bim`, check
   that its layer map set `georeference.crs_epsg` or `georeference.zone`. If
   you're not sure, just run the command below — a non-georeferenced IFC (or
   one with an invalid Scale) fails with a message naming the problem rather
   than silently producing a useless KMZ.
2. **Convert:**
   ```bash
   est-bim kmz <model.ifc> --out <bid_dir>/Sheets/<structure>.kmz        --geoid-shift-m <metres> [--omit "<regex>"]
   ```
   `--out` defaults to the IFC's path with a `.kmz` suffix when omitted.
   `--geoid-shift-m` is the NAVD88 → EGM96 separation (see the vertical-datum
   note below); without it the model floats or sinks by a few decimetres.
   `--omit` leaves reference-only elements out by name, e.g. an existing-ground
   mesh (`--omit "^existing-grade"`), which would z-fight Earth's own terrain.
   The command prints placemarks, vertices and dropped degenerate triangles.
   It refuses a model over Earth web's import limits (250,000 vertices,
   10,000 placemarks); re-run with `--massing` (one block per element) or
   `--omit` if that happens.
3. **Hand it to the user.** In Google Earth web: **Projects → New project →
   Import KML file from computer**. No further conversion needed.
4. **Only if the user is on Google Earth Pro and wants the smoother COLLADA
   model**, add `--collada`. That KMZ does **not** open in Earth web.
5. **If the user wants Cesium instead**, re-run with `--gltf`:
   ```bash
   est-bim kmz <model.ifc> --gltf --out <bid_dir>/Sheets/<structure>.glb
   ```
   This writes **only** a `.glb` (no KMZ is produced in this mode) — the
   roadmap escape hatch for Cesium/other glTF viewers, not a second delivery
   format for Google Earth.

## Notes — placement honesty
- **The default (web) KMZ reprojects every vertex** through the
  `IfcMapConversion` to WGS84. The `--collada` KMZ instead places the whole
  structure at one `<Location>` (the base point) with heading 0, which is fine
  at structure scale but is not survey-grade per-element geolocation.
  (Canonical grade rule: the `drafting-agent` agent.)
- **Approximate-grade coordinates mean approximate placement.** If the
  source DXF/plans carried assumed, sketch, or otherwise un-tied coordinates
  rather than a real survey control point, say so plainly when handing the
  KMZ to the user — the pin in Google Earth is only as good as the
  georeference that produced it. Do not present the placement as
  survey-accurate when the underlying coordinates were approximate.
- With `--collada`, the `.dae`'s geometry is in the model's local metres,
  anchored at the MapConversion base, which is why one anchor point suffices.
- **Vertical datum: project elevations are orthometric (NAVD88-class);
  Google Earth's absolute altitudes are heights above the EGM96 geoid — a
  different geoid model than NAVD88.** The gap is their local separation —
  typically within ~1 m in the continental US. Pass it as
  `--geoid-shift-m`; derive it once with
  `bimforge.terrain.datum.geoid_shift_m` (it needs the PROJ geoid grids:
  set `PROJ_NETWORK=ON` the first time) and pin the value. pyproj silently
  null-transforms heights when the grids are missing, so a shift of exactly 0
  is a red flag, not an answer.
