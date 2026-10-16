# IFC4X3 facility tree (`project.facility`, `spatial_part(s)`)

Without a `facility`, every structure is written as a building tree:
`IfcProject > IfcSite > IfcBuilding > IfcBuildingStorey > products`. IFC4X3
has a proper infrastructure decomposition, and 4X3-aware viewers (Bonsai,
BIMcollab, Solibri) navigate by it:

```
IfcSite
 +- IfcBridge                  (or IfcRoad / IfcRailway / IfcMarineFacility / IfcFacility)
 |   +- IfcBridgePart ABUTMENT (one per distinct spatial_part)
 |   |   +- contained elements
 |   +- unparted elements are contained in the facility itself
 +- terrain (kind: site) is contained directly in the IfcSite
```

**It is opt-in and IFC4X3-only.** IFC4X3_ADD2 is the default schema; a spec
that sets `schema: IFC4` (for Navisworks, Revit or a browser viewer, which
open IFC4X3 as an empty model) gets no facility tree: under IFC4,
`project.facility` is ignored with a note on stderr and
the output is byte-identical to a spec without it. Under IFC4X3 without a
facility, you get the building tree, as before.

## Spec keys

```yaml
project:
  name: "Br 39-0063"
  schema: IFC4X3_ADD2                 # the default; IFC4 drops the tree
  facility:
    kind: bridge                      # bridge | road | railway | marine | facility | site
    name: "Mariposa Creek Bridge"     # optional; defaults to the structure name
    predefined_type: GIRDER           # optional; IfcBridgeTypeEnum etc.

spatial_parts:                        # optional; spec top level AND/OR paycodes.yaml
  - {match: "(?i)abut", part: ABUTMENT}
  - {match: "(?i)deck|girder|barrier", part: {name: Deck, predefined_type: DECK}}
  - {match: "(?i)pier 1", part: "Pier 1", ifc_class: IfcColumn}
```

- `kind` picks the classes: `bridge` gives IfcBridge/IfcBridgePart, `road`
  gives IfcRoad/IfcRoadPart, `railway` gives IfcRailway/IfcRailwayPart,
  `marine` gives IfcMarineFacility/IfcMarinePart, and `facility` gives a
  generic IfcFacility/IfcFacilityPartCommon (utilities, drainage).
- `site` creates no facility. The structure's products are contained directly
  in the IfcSite. Use it for terrain and other geographic context.
- **Predefined types.** A value in the class's enumeration is used as is.
  Any other value becomes `USERDEFINED`, with the value in `ObjectType`.
  - A part's type is its explicit `predefined_type`. Without one, the part's
    *name* is used when it is an enum value: `ABUTMENT`, `DECK`, `PIER`,
    `SUPERSTRUCTURE`, `SUBSTRUCTURE`, `FOUNDATION`, ... for bridge parts;
    `CARRIAGEWAY`, `SHOULDER`, `SIDEWALK`, ... for road parts.
  - Otherwise the type is `USERDEFINED` and `ObjectType` holds the name, so
    `"Abut 1"` gives `USERDEFINED` / `Abut 1`.
- A part may also carry `usage_type` (LATERAL | LONGITUDINAL | REGION |
  VERTICAL). IFC4X3 makes `IfcFacilityPart.UsageType` mandatory, so a part
  without one is written `NOTDEFINED`.
- **`spatial_parts:` rules** work like paycodes `rules:`: the first rule whose
  regex matches the element name (and `ifc_class`, if given) wins.
  - They only fill elements that do not already have a part.
  - The spec's rules are applied before the paycodes' rules, so they take
    precedence.
- **Bespoke models** (`author-structure-model`) set the part on the element
  instead: `Element(..., spatial_part="ABUTMENT")` or
  `spatial_part={"name": "Deck", "predefined_type": "DECK"}`. To apply a
  rule list in Python, use `bimforge.author.spatial.apply_spatial_parts(model,
  parse_rules([...]))`.
- **Assemblies.** An `IfcElementAssembly` is contained in its members' part.
  An assembly whose members span parts is refused, because one assembly has
  one container.

## Combined and federated models

- `emit_combined_ifc` makes each model its own facility under the shared
  IfcSite, using that model's ctx.facility. A model with no facility still
  gets its own building and storey.
- `bimforge.author.federate` handles 4X3 sources written with a facility tree
  as follows:
  - **Facility subtree.** The facility, its parts, their aggregation and the
    containment are carried whole and hung under the target IfcSite.
  - **`site` sources.** The products of a `site`-kind source are contained in
    the target IfcSite.
  - **Building/storey trees.** Anything a 4X3 source holds in a building or
    storey tree still goes to a per-source storey.
  - **Mixed schemas are refused** (`MixedSchemaError`). This applies to IFC4
    and IFC4X3 sources together, and to sources whose schema differs from
    the federation ctx's.
  - **IFC4 sources** keep the per-source storey behaviour.
  - **GlobalIds** are namespaced per source, as they always were. Federation
    output is byte-deterministic.

## Gate

The post-emit spatial-chain gate also checks these points:

- Every product's container chain reaches the IfcSite.
- Every facility hangs off the site, and every part hangs off a facility.
- No part is empty.
- A 4X3 file with a facility tree passes `ifcopenshell.validate`.
