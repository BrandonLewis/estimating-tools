# The `est-bim takeoff` IFC Contract

**Audience:** anyone authoring an IFC that `bimforge.bim.ifc_takeoff`
(`est-bim takeoff`) should roll up into a `CanonicalTakeoff` — a parametric
generator, a Revit/Tekla export post-processor, a hand-built script.
`dxf2bim` is **one producer** of conforming IFCs, not the only one. This
contract is what the consumer reads; nothing here depends on how the IFC
was made. (Issue #88 EP-10: previously this surface was one parenthesis in
a module docstring and otherwise reverse-engineerable only from a shipped
artifact.)

Verified against `ifc_takeoff.py` as of 0.1.21.

## The one-paragraph version

`est-bim takeoff` walks every `IfcElement`, reads its **classification
code** (that's the pay-item key) and its **Qto quantity values** (SI), sums
the chosen quantity per code across elements, converts to the commercial
pay unit from the takeoff map, and emits one `CanonicalTakeoff` row per
code — or per `measures:` entry when one code pays several bid items. An
element with no classification code is counted and reported, never
silently dropped.

## What the consumer reads, entity by entity

1. **Elements:** `model.by_type("IfcElement")` — anything that is an
   element subtype participates; spatial structure, types, and annotations
   are ignored.
2. **Classification (the pay-item key):** on each element, EVERY
   `IfcRelAssociatesClassification` in `HasAssociations` whose
   `RelatingClassification` is an `IfcClassificationReference`:
   - `Identification` → the **code** rows key on (e.g. a Caltrans bid item
     code, a MasterFormat section — any string; leading zeros preserved),
   - `Name` → the row's default description,
   - `ReferencedSource` → the `IfcClassification` (or parent reference)
     whose `Name` is the classification **system** (`BidSchedule`,
     `MasterFormat`, …). The system is carried but not keyed on.
   An element may carry several codes and contributes to each under that
   code's own `measure` — heavy-civil pay structures require it (furnish by
   the foot AND drive by the each off one physical pile; issue #106). The
   same code associated twice counts once. Before 0.1.33 only the FIRST
   reference was read — a silent pay-item gap on multi-classified files.
   (Elements without a code are tallied into a single "N element(s) had no
   classification code" warning; a map-declared code that produced no rows
   gets its own warning.)
3. **Quantities:** every quantity set reachable through
   `IfcRelDefinesByProperties` (any `IfcElementQuantity`, typically named
   `Qto_*BaseQuantities`) is flattened into one `{name: value}` dict per
   element. **Member names are the contract** — the consumer keys on:

   | Quantity name | Dimension | SI base after scaling |
   |---|---|---|
   | `GrossArea`, `NetArea` | area | m² |
   | `GrossVolume`, `NetVolume` | volume | m³ |
   | `Length`, `Perimeter`, `Width`, `Height` | length | m |
   | `Count` | count | each |
   | `GrossWeight`, `NetWeight`, `Weight` | mass | kg |

   (`Weight` — no prefix — is `Qto_ReinforcingElementBaseQuantities`' name
   for it; `est-rebar`'s `add_reinforcing_bars` authors that set, with
   `Weight` as the mark total consistent with `Count`.)

   Values are read in the file's **declared units** and scaled to SI base
   on the way in (issue #109; before 0.1.34 raw values were assumed SI —
   a millimetre-unit file inflated 1000×). Each dimension scales by its
   OWN declared unit: length by `LENGTHUNIT`, area by `AREAUNIT`, volume
   by `VOLUMEUNIT` (0.1.88 and earlier squared and cubed the length unit,
   so the common mm / m² / m³ assignment — ifcopenshell's default, Revit's
   metric export — read 10 m³ as 1e-8 m³). Only an undeclared area or
   volume unit falls back to the length unit squared or cubed. A quantity
   that names its own `Unit` is read in that unit, whatever the project
   declares. Mass scales by the declared `MASSUNIT` (commonly GRAM — IFC's
   SI mass unit; kg when none is declared). Conversion-based units (feet,
   cubic yards) are read through their own `ConversionFactor`. Pay-unit
   conversion
   (CY/SF/LF/EA/LBS/CWT/TON) happens only on the way out. Weight (issue
   #108) is **opt-in** via a declared `measure:` — it never participates in
   the natural-preference fallback, so pre-0.1.34 maps keep their behavior.
   Unrecognized quantity names are ignored harmlessly (and pass through
   unscaled).
4. **Element breakdown (feeds BidManager structures):** each row carries an
   `elements[]` entry per contributing element:
   `{name, section_type, count, length_ft, width_ft, height_ft}` — the
   dimensions recovered from `Length`/`Width`/`Height` Qto values (feet,
   null when absent), `count` from `Count` (default 1). `section_type`
   derives from the IFC class: `IfcSlab`→`decks`, `IfcWall`→`walls`
   (**name containing `wing` → `wing_wall`** — dxf2bim embeds the source
   layer in `Name`, and name matching is the only wing-wall signal),
   `IfcFooting`→`footing`, `IfcPile`→`pile`, anything else → the
   lowercased class name without the `Ifc` prefix.

## Measure selection

- **Map entry with `measure:` (singular):** that quantity name is
  preferred; if an element lacks it, the natural preference order applies:
  `Count` → `GrossVolume` → `NetVolume` → `GrossArea` → `NetArea` →
  `Length`. An element with none of these is warned and skipped.
- **Map entry with `measures:` (plural):** each entry is **strict** — only
  its named measure is summed; an element lacking that quantity is warned
  (`… lacks <measure> — skipped from that row`) and still counts toward
  the code's other entries. No fallback.
- **No map entry:** natural preference order, natural SI unit
  (`M2`/`M3`/`M`/`EA`), no item number — plus a warning so the gap is
  visible.

## Pay-unit conversion (SI → commercial)

area: `M2`/`SM`, `SF`, `SY` · volume: `M3`/`CM`, `CY`, `CF` · length:
`M`/`LM`, `LF`/`FT`, `YD` · count: `EA`/`EACH`, `LS`. A unit that doesn't
match the measure's dimension raises a config error naming the choices.
A `Count` row paid `LS` reports quantity 1 whatever its element count (the
elements still list); `count_as: <number>` on a map entry (or a `measures:`
entry) states the quantity of any `Count` row outright.

## The takeoff map

```yaml
organization_id: 123          # BidManager org id (int; 0 placeholder)
project_ref: "bridge-pilot"
defaults:
  schedule: "A"

codes:
  # singular — one code, one bid item
  "510120":
    measure: GrossVolume      # optional; natural preference when absent
    unit: CY
    item_number: "0040"
    schedule: "A"             # falls back to defaults.schedule

  # plural — one code, several bid items over the same elements
  # (the issue #88 case: CISS piling furnished by the foot, driven each)
  "49-3020":
    schedule: "A"             # code-level default for the entries
    measures:
      - measure: Length
        unit: LF
        item_number: "0055"
        description: 'Furnish 24" CISS Piling'
      - measure: Count
        unit: EA
        item_number: "0056"
        description: 'Drive 24" CISS Pile'
```

Per-entry keys: `measure` (required, from the table above), `unit`,
`item_number`, `description` (default: the classification reference's
`Name`), `schedule` (entry → code level → `defaults.schedule`).
`measure` and `measures` on the same code is an error. With `measures:`,
each row's `elements[]` lists the same contributing elements — truthful
duplication; `push-takeoff` materializes sections per row.

The map now has **two consumers**: `est-bim takeoff` (quantity rows) and
`est-bim estimate5d` (a quantity-backed ESTIMATE `IfcCostSchedule` whose
`CostQuantities` reference the elements' own Qto entities — see the
`estimate5d` module docstring for the authoring contract). Both validate the
map identically (`normalize_map`). estimate5d additionally requires an
explicit `measure` per priced entry — the natural-preference fallback is a
takeoff-only convenience.

## Minimal conforming IFC checklist

- [ ] IFC4 (IFC2X3/IFC4X3 also open), project length unit **metres**
- [ ] One `IfcClassification` naming your system (e.g. `BidSchedule`)
- [ ] One `IfcClassificationReference` per pay code
      (`Identification` = code, `Name` = bid-item name,
      `ReferencedSource` = the classification)
- [ ] One `IfcRelAssociatesClassification` per code listing its products
- [ ] Per product, an `IfcElementQuantity` (via
      `IfcRelDefinesByProperties`) whose members use the recognized
      quantity names above, in SI
- [ ] Product classes chosen so `section_type` derives correctly
      (walls named `*wing*` for wing walls)

Then: `est-bim takeoff --ifc model.ifc --map takeoff_map.yaml --out takeoff.json`
and hand the JSON to the estimating-core `push-takeoff` flow.

## Modelled elements and the estimate model (BidSheet.ai round trip)

Two further consumers read the same conforming IFC per **element**, keyed by
`GlobalId`, rather than per pay code:

- `est-bim model-elements` (`bimforge.bim.model_elements`) plans BidSheet.ai's
  `upsert_modelled_elements` payload. Each element sends its GlobalId, name,
  IFC class and element type (subtype-aware: `IfcWallStandardCase` is a wall)
  and its quantities, converted into each key's unit. By default only the
  classes BidSheet.ai types (`IfcFooting`, `IfcWall`, `IfcSlab`, `IfcColumn`,
  `IfcPile`, `IfcEarthworksCut`, `IfcEarthworksFill`) and classified elements
  are sent; beams, members, plates, courses and pavements are skipped even
  when classified, and the rest is skipped with its class (`--all-elements`
  sends both as generic). Reinforcement, terrain and virtual elements are
  never sent, nor an element that aggregates parts which are sent, nor one
  whose GlobalId is malformed or repeats an earlier one (the first is kept):

  | Element | Key | Qto quantity (first present) |
  |---|---|---|
  | `IfcEarthworksCut`, or `IfcEarthworksElement` with ObjectType `EXCAVATION` | `excavation_cy` | `UndisturbedVolume`, `NetVolume`, `GrossVolume` |
  | `IfcEarthworksFill` | `backfill_cy` | `CompactedVolume`, `NetVolume`, `GrossVolume` |
  | any other element | `concrete_cy` | `NetVolume`, `GrossVolume` |
  | `IfcPile` | `pile_lf` | `Length` |
  | concrete types, opt-in | `form_contact_sf` | the quantity `--form-area` names |

  A loose (swelled) volume is never used as the in-place measure. No standard
  Qto carries a formwork area, and a wall's `NetSideArea` is one face only, so
  the formed area is sent only when the producer names its quantity. An element
  with none of these quantities is still sent, with `quantities: {}`, so a
  re-import clears the values an earlier one stored; one with a NaN or infinite
  quantity is skipped instead. Pay items are keyed off the element's
  classification codes (see "What the consumer reads" above); a code several
  estimate items share pays none (`--schedule` narrows them to one schedule).
  `--takeoff` (or `--takeoff-id N`) plans the same entries for
  `upsert_modelled_elements(takeoff_id=...)`, a named project takeoff
  (BidSheet.ai #1486 slice 7): no entry carries `pay_items`, because a takeoff
  has none. Element selection, GlobalId checks and unit conversion are
  unchanged.
- `est-bim estimate-model` (`bimforge.bim.estimate_model5d`) writes the
  estimate back into the IFC as tasks, cost items and crews (see the module
  docstring). It links them to elements by GlobalId. Task finishes are
  inclusive (BidSheet.ai's `finish_date`; its `end_date` is exclusive). It
  replaces only the schedules it marked (`BidSheet_EstimateModel`) and refuses
  a same-named schedule another tool wrote.
