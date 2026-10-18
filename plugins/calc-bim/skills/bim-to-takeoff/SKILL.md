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
`~/.estimating/bin/est-bim --help` to confirm. If that command is not found,
see the **Setup** block above.

## Workflow
1. **Confirm the pay basis per cost code.** Start from the shipped
   `takeoff_map.example.yaml` (written by `~/.estimating/bin/est-bim sample --with-configs`).
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
   - **lump sums and stated counts:** a `Count` code whose `unit` is `LS`
     reports quantity **1** however many elements carry the code (they
     still list under the row's `elements`, so the audit and the push see
     what backs the lump sum). To state the pay count of any `Count` code
     outright — the model carries a spare, or the item pays per pair — set
     `count_as: <number>` on the entry (also per `measures:` entry); it
     overrides the element count for LS and EA alike.
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
   ~/.estimating/bin/est-bim takeoff --ifc model.ifc --map <takeoff_map.yaml> \
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
   (`~/.estimating/bin/est-takeoff plan takeoff.json --structure-id <id>` gives a dry-run push
   plan first). Takeoff quantities land on the **estimate layer as structure
   sections** via the BidSheet.ai MCP (`create_structure` /
   `add_structure_section` per the plan output) — official bid-item
   quantities are immutable by convention, and the legacy
   `--target bid-item-quantities` path is forbidden on live bids (BM #984).
   After the takeoff, reconcile it three ways with the `audit-quantities`
   skill in the **estimating-core** plugin.

## Per-element verification workbook (est-bim takeoff-workbook)

When the estimator wants to CHECK the rollup, not just receive it, write
the per-element takeoff workbook from the same IFC(s) and map:

```bash
~/.estimating/bin/est-bim takeoff-workbook --ifc BIM/bridge.ifc --ifc BIM/approach-slabs.ifc \
    --map BIM/bridge-takeoff-map.yaml --official bid_items.json --out Takeoff/takeoff.xlsx
```

`--ifc` repeats for several models; `--official` is optional — a JSON list
of bid items (`[{item_number, quantity | estimated_quantity, description?}]`,
or an object holding that list under `bid_items` / `items` / `bid_frame`,
e.g. the project manifest's frame) that fills the Summary's Official qty;
without it that column is blank. Needs openpyxl (the `xlsx` extra). Under
the plugins it is already installed (`estimating_tools[plugin-core]` carries
it); installed by pip instead, it is `pip install "bimforge[xlsx]"`.

**Elements sheet — one row per element per pay code.** The column order is
the contract (Arial, frozen header, blue = input the reviewer may edit,
black = model value or formula):

| # | Column | What it is |
|---|--------|------------|
| A–I | Structure, Element, Description, IFC class, Facility part, Cost code, Item #, Bid item, Pay unit | identity — structure (the IFC's building/facility name, else the file stem), the element's name and `Description`, its spatial container, the pay code (`(reference)` when unclassified), the map's item number and unit, the bid item's description |
| J | **Qty** | `Count` from Qto (input, blue) |
| K | **#_surfaces** | number of distinct planar faces of the element's tessellation |
| L–N | **L (ft), W (ft), H (ft)** | `Length` / `Width` / `Height` from Qto, in US survey feet (inputs, blue) |
| O | **CY** | formula: `CF (model) / 27` |
| P | **Forming SF** | formula: `Side SF × Form sides + Soffit SF × Form soffit` |
| Q | CF (model) | `GrossVolume` from Qto, in CF |
| R | CF (L×W×H×Qty) | formula: the hand check |
| S | Δ box vs model | formula: `R / Q − 1` — non-zero when the solid is not a box (battered, skewed, voided) |
| T, U | Area SF, Weight LB | `GrossArea` / `GrossWeight` from Qto |
| V–X | Top SF, Soffit SF, Side SF | the SFCA face split of the tessellation (`\|nz\| > 0.85` top/soffit, else side on the true slope) |
| Y, Z | Form sides (1/0), Form soffit (1/0) | inputs (blue), defaulted by IFC class: footings, walls, columns, railings → sides; CIP slabs and beams → sides + soffit; precast, coverings, earthworks, pavements, rebar, proxies, geographic → none |
| AA | Pay qty | formula in the map's pay unit for the code's measure (CY = `CY`, CF, SF = `Area SF`, SY = SF/9, LF = `L × Qty`, EA = `Qty`, LB, TON = LB/2000); a code with plural `measures:` uses its first entry |
| AB, AC | GUID, Model file | provenance |
| AD, AE | Pay measure, Pay measure (model) | the exact Qto measure named by the map and its value in the workbook's feet/pounds domain; net and gross quantities stay distinct |

The pay quantity follows the map's exact measure, including NetVolume,
NetArea, Width, Height, Perimeter and NetWeight. A missing mapped measure
is an error. A Count row in LS, or with `count_as`, contributes its override
once per cost code, regardless of how many elements back it.

**Summary sheet** — one row per cost code (map codes plus any code found in
the models, ordered by item number): Item #, Cost code, Bid item, Pay unit,
Modelled qty (`SUMIFS` of Pay qty by cost code), Official qty (blue input),
Variance, Variance %, Elements (`COUNTIFS`). A large variance is a finding
to resolve against the plans, not a number to tune. **Legend** explains the
colours and formulas; **Sources** lists each IFC with its SHA-256.

Units: IFC metres → US survey feet (1200/3937 m) for lengths, areas and
volumes; kilograms → pounds. The output is byte-deterministic (pinned
docProps and zip dates), so a rebuild of unchanged models is identical and
the workbook can be committed and diffed. A cost code with no map entry
pays nothing and is reported on stderr as a review note.

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
