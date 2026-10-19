---
name: quantity-takeoff
description: Perform a construction quantity takeoff for flat-measure items — extract stated dimensions from plans, compute length x width style quantities with waste factors, and convert units. For structures work (standard-plan section tables, per-station runs, geometry measured off vector plan sheets) use the calc-bim plugin's measure-plans / bim-to-takeoff instead.
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

> **Scope:** this skill is for flat-measure items (areas, simple volumes,
> lengths with a waste factor). Structures takeoff — sections looked up
> from a standard-plan table by design H, per-station runs, lapped/stepped
> geometry — is NOT length x width: use the **calc-bim plugin**'s
> `measure-plans` skill to measure vector plan sheets and `bim-to-takeoff`
> to roll model quantities into a CanonicalTakeoff, or build a
> table-driven workbook via `build-estimate-workbook` (XLOOKUP into a
> section table, so quantities reflow when a design H changes). A blanket
> waste factor on structural concrete CY is not how that item is priced.

# Quantity Takeoff

Analyze construction documents and perform quantity takeoffs. Use the `pdf-extraction`
skill to pull dimensions from plan PDFs, then compute and organize quantities with
the `estimating_tools.takeoff` package.

## Inputs
- Construction plan or specification documents (PDF or text)
- Unit of measurement (LF, SF, CY, EA, etc.) — inferred from item type if not specified

## Workflow

### 1. Extract Dimensions from Plans

Use the `pdf-extraction` skill to pull dimension data from plan sheets:

```bash
python -m estimating_tools.pdf.extract_text --file "plans.pdf" --pages "1-20"
```

### 2. Identify Items and Calculate Quantities

You are a construction estimator performing quantity takeoffs. Your goal is to:

1. **Read and analyze** the specification or plan document
2. **Identify items** that require quantity takeoffs
3. **Calculate quantities** based on the document dimensions and specifications
4. **Organize by CSI division** when applicable
5. **Apply appropriate units** (infer from item type if not specified)

For programmatic calculations use
`estimating_tools.takeoff.core.calculate_takeoff` (dimension math + material
waste factor, org-profile overrides) — `convert_units` and
`check_dbe_requirements` live beside it, and `est-takeoff convert --help`
covers CLI unit conversions. The functions' docstrings carry the call shapes.

### 3. Organize and Output

```markdown
## Quantity Takeoff Summary

**Project:** [extract from document]
**Date:** [current date]

### Items by Division

#### Division [XX] - [Name]

| Item Description | Quantity | Unit | Notes |
|------------------|----------|------|-------|
| [description]    | [qty]    | [unit] | [assumptions/notes] |

### Assumptions & Clarifications
- [List any assumptions made]
- [Items requiring clarification]

### Summary
- Total items counted: [number]
- Divisions covered: [list]
```

## Output & BidSheet.ai hand-off

Once quantities are organized into rows, **quantity** rows reach BidSheet.ai via
the **`push-takeoff`** skill. It never writes the official bid-item quantity
(BidSheet.ai issue #984): takeoff quantities land on the estimate layer as
structure sections, and where the cost quantity differs from the official
schedule it is set on the estimate item with
`mcp__bidmanager__update_estimate_item(quantity_override=…)`; model quantities are only compared
against the official schedule, read-only. Material and structure rows are not yet
bridged directly; until that support lands, their quantities reach BidSheet.ai the
way any estimate's do — carried into bid items by `push-estimate` (see
`import-estimate` → `push-estimate`). This takeoff table is the source you enter
or reconcile those quantities from.

## Takeoff Process Details

### Document Analysis
- Read the entire specification document
- Identify all measurable items
- Note any assumptions or clarifications needed
- Check for conflicting information

### Quantity Calculation
- Extract dimensions, lengths, areas, or volumes
- Apply appropriate formulas (area = L×W, volume = L×W×H, etc.)
- Waste factors are org convention (profile `estimating.waste_factors`); the built-in table below is only the agnostic fallback
- `calculate_takeoff()` applies material-specific waste factors automatically
- Round to appropriate precision for the unit type

## Waste Factors

Waste is item-dependent org judgment (e.g. footing concrete 15%, walls 10%),
served by the org profile's `estimating.waste_factors` (free-form keys ->
multiplier, e.g. `footing_concrete: 1.15`). `calculate_takeoff()` applies the
profile value when set (`waste_source: "profile"`); otherwise it falls back to
the agnostic defaults below (`waste_source: "default"`) — confirm those with
the estimator before relying on them.

| Material   | Agnostic default (multiplier) |
|------------|-------------------------------|
| concrete   | 1.05 (5%)  |
| asphalt    | 1.03 (3%)  |
| aggregate  | 1.10 (10%) |
| rebar      | 1.08 (8%)  |
| lumber     | 1.15 (15%) |
| pipe       | 1.05 (5%)  |
| default    | 1.05 (5%)  |

## Excavation pay limits

Excavation and backfill volumes are **measured to the payment envelope, not
to the hole you actually dig.** Structural excavation/backfill pay to the
standard-plan pay-limit diagram (e.g. a Caltrans A62C/A62E-class envelope);
on (F) final-pay items the neat plan quantity governs and is never
re-measured. Everything outside the envelope — sloping back a deep bank,
benches, working room, shoring — is unpaid excavation: **price it
deliberately** (hours and equipment); do not assume it disappears into the
excavation unit price. Keep two numbers per dig: the pay volume (envelope /
neat lines) and the cost volume (what the machine actually moves).

For the benched-dig arithmetic use
`estimating_tools.takeoff.earthwork` — `prism_cy` (neat pay prism),
`wedge_cy` (one-face lay-back), and `bench_increment_cy` (the benched pit
prismatoid minus its own neat prism; returning the raw pit double-counts
the pay volume). Full earthwork judgment — mass-grading spec reading,
consolidation-factor mass-haul, rippability, the OSHA Subpart P slope-cap
cross-check — is the `earthwork-takeoff` skill.

## Common Units Reference

- **LF** (Linear Feet): Curb, piping, striping
- **SF** (Square Feet): Pavement, walls, slabs
- **SY** (Square Yards): Paving, surfacing
- **CY** (Cubic Yards): Concrete, excavation, fill
- **CF** (Cubic Feet): Intermediate volume
- **EA** (Each): Signs, fixtures, equipment
- **TON**: Asphalt, aggregate
- **LS** (Lump Sum): Complete systems or assemblies
