---
name: author-structure-model
description: Author a bespoke structure's BIM (IFC) directly over the bimforge.author kernel when no shipped family fits — build a StructureModel of Elements from primitives/alignment, gate-validate, then emit DXF + IFC + takeoff-map/QTO/STEP. Use when the briefed structure has no registered family (an odd bridge, wall, vault, outfall, or one-off), and the user wants modelled quantities instead of hand math. Triggers include "build the IFC model", "model this structure", "author a bespoke model", "no family fits", "hand-author over bimforge.author", "custom bridge/wall/vault model".
---

# Author a Bespoke Structure Model (`bimforge.author`)

The **majority of real structures have no shipped family** — they are authored
directly over the `bimforge.author` kernel. This is a first-class route, not a
fallback: same gate, same determinism, same IFC-is-the-one-source discipline as
`build-structure`. Reach for this whenever a structure is briefed and
`build-structure`'s family registry has nothing that fits.

If a family DOES fit (`pipe-supports`, `standard-plan`, `bridge-standard`,
`box-culvert`, the barrier/wingwall/headwall families, …), use `build-structure`
instead — a family computes every quantity closed-form and is already gated.
Check first:
```bash
~/.estimating/bin/est-python -c "from bimforge.author.families.registry import available; print(sorted(available()))"
```

## Prerequisites
Requires ezdxf, shapely, ifcopenshell and numpy — all in the base install, as
is the `openpyxl` the QTO workbook needs; run
`~/.estimating/bin/est-bim --help` to confirm. If that command is not found,
see the **Setup** block above.

STEP output additionally needs build123d, the `solids` extra, which the base
install omits. Install it into whichever interpreter runs `est-bim`:

- **Under the plugins**, it is the interpreter they keep under
  `~/.estimating/`, reached only by `~/.estimating/bin/ensure-extra solids`;
  a bare `pip install` would land somewhere else and change nothing here.
- **Installed by pip instead**, it is `pip install "bimforge[solids]"`.

## The kernel, in one paragraph
The **model is the single source of truth**: you build a `StructureModel` of
`Element`s, each carrying parametric geometry, **analytic** quantities (closed
form, feet/pounds), zero-or-more pay-code `classifications`, and a deterministic
GUID. Emitters READ the model — they never compute geometry or quantities. The
gate runs closed-form checks BEFORE anything is written, and re-checks the
written files after.

## Workflow

1. **Confirm the bespoke route.** No family fits (registry above). A structure
   that a family *nearly* fits is usually better served by extending or
   registering a family (entry-point group `bimforge.families`) — but a genuine
   one-off is authored here.

2. **Project context (georeference).** One `ProjectContext` fixes the CRS,
   base point, vertical datum, and the GUID namespace:
   ```python
   from bimforge.author.project import ProjectContext
   ctx = ProjectContext.from_spec({
       "name": "Structure 3",
       "epsg": 2226,
       "base": [E, N, H],
       "guid_ns": "3b7a5c2e-0000-4000-8000-000000000042",
   })
   ```
   Choosing `epsg` + `base` is trap-prone (the ftUS-vs-metre EPSG rescale,
   NGVD29 vs NAVD88) — see the georeferencing reference in build-structure
   (`../build-structure/references/georeferencing.md`). No survey control? Pass
   `allow_local=True` to `emit_ifc` **explicitly** — the kernel refuses a
   silently local IFC (a named drift bug), it will not default to it.
   **IFC4X3 facility tree (opt-in).** Under the default IFC4X3_ADD2 schema, add
   `"facility": {"kind": "bridge", "predefined_type": "GIRDER"}` to get
   IfcSite > IfcBridge > IfcBridgePart instead of a building and storey. Set
   `spatial_part="ABUTMENT"` (or `{"name": "Deck", "predefined_type": "DECK"}`)
   on each `Element` to choose its part. Use kind `site` for terrain. See
   `../build-structure/references/ifc4x3-facility.md`.

3. **Build the model from primitives.** `bimforge.author.primitives` covers the
   vocabulary: `Prism` (extruded ring, holes, per-vertex taper), `SectionPrism`
   / `BatteredWall` (face-derived volumes for battered/mitred runs), `Fill`
   (backfill = gross-minus-cuts boolean), `Bar` / `RebarBuilder` (reinforcing,
   swept-disk directrix), `Plate` / `Bolt` / `Tube` / `ArcBand` /
   `ShapedStiffener` (fabricated steel). Curved members ride an `alignment`
   (compound radii, vertical curves, superelevation) via the sweep engine —
   a swept run refuses a plan kink; a road/bridge turns on a curve, not an
   angle point. **Place, mirror or grade a solid with `Affine`** (or its
   `MirrorX` / `ShearedZ` shorthands). For example,
   `Affine.placed(girder, origin, angle_deg=..., grade=...)` sets a girder on
   two seats. Never edit the `verts` that `body_solids()` returns. `Affine`
   moves the solid's exact form with its mesh, so a `SectionPrism` still ships
   as one `IfcExtrudedAreaSolid` that an engineering team can edit. An edited
   mesh is written as a non-editable triangulated brep.
   ```python
   from bimforge.author.model import Element, StructureModel
   from bimforge.author.primitives import Prism

   model = StructureModel("Structure 3", ctx)
   footing = Prism("footing", base=[...], z_bot=0.0, z_top=2.5, dims_ft=(L, W))
   model.add(Element.from_geometry(
       "footing", footing, ifc_class="IfcFooting", layer="S-CONC-OTLN",
       classifications=["51-2.01"],          # [] = reference geometry, never a pay qty
       quantities={"volume_cf": footing.volume_cf}))
   ```
   **Pay-item excavation is `IfcEarthworksElement`** (ObjectType `EXCAVATION`),
   not `IfcEarthworksCut`: a cut is an `IfcFeatureElementSubtraction` that must
   void a host through `IfcRelVoidsElement`, and an unhosted one is invalid
   IFC. `emit_ifc` rewrites an unhosted `IfcEarthworksCut` to
   `IfcEarthworksElement` with a one-line note on stderr; `Fill` stays
   `IfcEarthworksFill`. Both take off by `GrossVolume` as before.
   `Element.from_geometry` delegates quantities to the geometry object; set them
   explicitly only when the geometry cannot. **Quantities are analytic** —
   never a section-area × length shortcut (wrong by a few percent on battered/
   mitred geometry; integrate the same faces the solid presents).

4. **Stationing / annotation (optional).** `bimforge.author.annotate` puts
   station ticks + labels into the IFC as instanced `IfcAnnotation` (and the
   DXF), sharing the element frame — append them before the gate and emitters
   so both files carry them:
   ```python
   from bimforge.author.annotate import station_annotation
   model.annotations.append(
       station_annotation(align, s0, s1, interval=100.0, origin=ctx))
   ```

5. **State what you expect, and check it.** Register closed-form assertions so
   the gate proves the model, not just its schema:
   ```python
   model.stated_quantities.append(("footing concrete", footing.volume_cf,
                                    L * W * 2.5, 0.01))   # (label, got, want, tol)
   model.checks.append(lambda m: [...])                  # family/script checks -> [msgs]
   ```
   A check that would emit nothing if the model were broken is worse than no
   check — always ask "if this were wrong right now, would this fire?"

6. **Gate FIRST.** Nothing is written until the pre-gate passes:
   ```python
   from bimforge.author import gate
   report = gate.run_pre(model, paycodes)
   if not report.passed:
       raise RuntimeError(report.format("pre"))
   ```
   A failure means the model or the reading is wrong — fix the transcription or
   escalate the ambiguity; do not loosen a check to make it pass.

7. **Emit, then post-verify.** Write the outputs, then re-check the written
   files (mesh-vs-analytic volume, takeoff-map coverage):
   ```python
   from pathlib import Path
   import yaml
   from bimforge.author.emit_ifc import emit_ifc
   from bimforge.author.emit_dxf import emit_dxf
   from bimforge.author.emit_qto import emit_qto

   outputs = {
       "ifc": "CAD/s3.ifc",
       "dxf": "CAD/s3.dxf",
       "takeoff_map": "CAD/s3-takeoff-map.yaml",
       "qto": "CAD/s3-QTO.xlsx",
   }
   takeoff_map = Path(outputs["takeoff_map"])
   takeoff_map.parent.mkdir(parents=True, exist_ok=True)
   takeoff_map.write_text(
       yaml.safe_dump(paycodes.takeoff_map(model.codes_used()), sort_keys=False),
       encoding="utf-8")
   emit_dxf(model, outputs["dxf"])
   emit_ifc(model, outputs["ifc"], paycodes)       # allow_local=True only if no control
   emit_qto(model, outputs["qto"], paycodes)
   post = gate.run_post(model, outputs, paycodes)
   if not post.passed:
       raise RuntimeError(post.format("post"))
   ```
   An unchanged model rebuilds **byte-identical** (stable GUIDs from
   `guid_ns`) — commit-friendly.

8. **Hand off.** Derive the takeoff from the IFC with `bim-to-takeoff` (it reads
   `Qto_BaseQuantities` and the classification references); frame the DXF with
   `draw-structure-sheet`; `show-structure-earth` for a KML check when
   georeferenced. Estimate-layer pushes stay in estimating-core (`push-takeoff`).

## Discipline (same as build-structure)
- **Transcribe-then-verify:** every dimension is a citable transcription
  (`read-station-plans`), never a scaled guess; unknowns go in an `assumptions`
  list WITH a reason.
- **Reference geometry** (existing terrain, context) carries `classifications=[]`
  — no pay code, no Qto — so it can never reach a pay quantity.
- **Determinism is not optional** — a `guid_ns` is required; the same model
  must rebuild identically.

## Related skills
- `build-structure` — the family route; use it whenever a registered family
  fits. It routes here when none does.
- `read-station-plans` — transcribe the parameters this model is built from.
- `bim-to-takeoff` — derive bid quantities from the IFC this produces.
- `dxf-to-bim` — the alternative when the input is a 2D DXF to measure off,
  not a briefed parametric structure.
