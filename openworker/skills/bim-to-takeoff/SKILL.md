---
name: bim-to-takeoff
description: Turn an IFC model into a BidSheet.ai-ready CanonicalTakeoff by grouping elements by cost code and converting quantities to pay units. Use after authoring or receiving an IFC when the user wants bid-item quantities out of a model. Triggers include "IFC to takeoff", "quantities from the model", "roll up by cost code", "CanonicalTakeoff", "get bid quantities from BIM".
---

# BIM (IFC) → CanonicalTakeoff

Read **any IFC that conforms to the takeoff contract** — classification
references keyed by pay code plus `Qto_*` quantities in SI — group elements
by cost code, sum the pay quantity, convert SI → the commercial pay unit,
and emit a **CanonicalTakeoff** — the exact JSON the estimating-core
`push-takeoff` flow ingests (`estimating_tools.takeoff.model.CanonicalTakeoff`).
`dxf-to-bim` is one producer of conforming IFCs, not the only one: a
parametric generator or a post-processed Revit/Tekla export works the same.
The full contract (entities, recognized quantity names, units, checklist)
is `docs/ifc-takeoff-contract.md` in the estimating-tools repo; the short
version is below.

The deterministic rollup is `bimforge.bim` (`est-bim` CLI).

## Prerequisites
Requires ifcopenshell, which the base install carries; run
`est-bim --help` to confirm. If that command is not found,
see the **Setup** block above.

## Workflow
1. **Confirm the pay basis per cost code.** Start from the shipped
   `takeoff_map.example.yaml` (written by `est-bim sample --with-configs`).
   For each classification code present in the IFC, set:
   - `measure`: which quantity to sum — area (`GrossArea`/`NetArea`),
     volume (`GrossVolume`/`NetVolume`), length (`Length`/`Perimeter`), or `Count`
   - `unit`: the pay unit — auto-converted from SI. The recognized unit set
     per measure lives in `docs/ifc-takeoff-contract.md`'s "Pay-unit
     conversion" table, which GOVERNS — an inline copy here already went
     stale once (it had lost the `SM`/`CM`/`LM` metric aliases), so read the
     contract doc rather than any restated list. A unit that doesn't match
     the measure's dimension raises a config error naming the choices.
   - `item_number` and `schedule` (so rows map onto bid items)
   - **one code paying several bid items:** use `measures:` (plural) — one
     row per entry over the same elements, each with its own
     `measure`/`unit`/`item_number` and optional `description`/`schedule`:
     ```yaml
     "49-3020":
       measures:
         - {measure: Length, unit: LF, item_number: "0055",
            description: 'Furnish 24" CISS Piling'}
         - {measure: Count, unit: EA, item_number: "0056",
            description: 'Drive 24" CISS Pile'}
     ```
     Plural entries are strict: an element lacking that quantity is warned
     and skipped from that row only (no fallback measure).
   Also set `organization_id` (the integer BidSheet.ai org id) and `project_ref`
   at the top.
2. **Run:**
   ```bash
   est-bim takeoff --ifc model.ifc --map <takeoff_map.yaml> \
       --out takeoff.json --csv takeoff.csv
   ```
   It prints a summary table (item, code, description, qty, unit, schedule),
   writes `takeoff.json` (CanonicalTakeoff) and `takeoff.csv`.
3. **Review the "Review" warnings** printed to stderr — any cost code without a
   map entry falls back to natural SI units and is flagged; any element without a
   classification is reported. Fix the layer map or takeoff map rather than
   shipping a wrong unit. If the IFC carries no usable Qtos or classification at
   all (a foreign Tekla/Revit export), flatten it with the `ifc-to-dxf` skill
   and re-enter through `dxf-to-bim`.
4. **Hand off** `takeoff.json` to the estimating-core `push-takeoff` skill
   (`est-takeoff plan takeoff.json --structure-id <id>` gives a dry-run push
   plan first). Takeoff quantities land on the **estimate layer as structure
   sections** via the BidSheet.ai MCP (`mcp__bidmanager__create_structure` /
   `mcp__bidmanager__add_structure_section` per the plan output) — official bid-item
   quantities are immutable by convention, and the legacy
   `--target bid-item-quantities` path is forbidden on live bids (BM #984).
   After the takeoff, reconcile it three ways with the `audit-quantities`
   skill in the **estimating-core** plugin.

## The contract (what a conforming IFC carries)

- Every takeoff element is an `IfcElement` subtype.
- Pay code: an `IfcClassificationReference` per code (`Identification` =
  the code, `Name` = bid-item name, `ReferencedSource` = the
  `IfcClassification` naming the system, e.g. `BidSchedule`), associated to
  its products by one `IfcRelAssociatesClassification`.
- Quantities: an `IfcElementQuantity` per product (via
  `IfcRelDefinesByProperties`) whose member **names** are the interface —
  `GrossArea`/`NetArea` (m²), `GrossVolume`/`NetVolume` (m³),
  `Length`/`Perimeter`/`Width`/`Height` (m), `Count` — all **SI**.
- Section types derive from the IFC class (`IfcSlab`→decks,
  `IfcWall`→walls, name containing `wing`→wing_wall, `IfcFooting`→footing,
  `IfcPile`→pile); unclassified elements are counted and warned, never
  silently dropped.

## Notes
- One row out per cost code — or per `measures:` entry when a code pays
  several bid items (each such row lists the same contributing elements;
  push-takeoff materializes sections per row) — plus an `elements`
  breakdown per row: one entry per IFC element with
  a BidSheet.ai `section_type` (IfcSlab FLOOR → decks, IfcWall → walls — or
  wing_wall when the element's name/source layer suggests a wing wall,
  IfcFooting → footing, IfcPile → pile) and `length_ft`/`width_ft`/`height_ft`
  recovered from the Qto quantities (null where not derivable). Those elements
  become the structure sections in the push plan.
- Without a `--map`, it still runs but emits natural SI units and flags every
  code for review — never a silent wrong unit.
- `kind` is always `"quantity"` in this release; material/structure rows are a
  later concern (consistent with the push-takeoff skill's supported surface).
