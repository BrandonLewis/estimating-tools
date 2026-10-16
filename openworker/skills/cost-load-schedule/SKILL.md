---
name: cost-load-schedule
description: Cost- and resource-load a project's 4D schedule — spread the BidSheet.ai priced estimate's cost and labor-hours across the schedule tasks (by bid-item code) into a time-phased cash-flow S-curve and manpower histogram, and optionally embed IfcCostSchedule + labor resources into the IFC for job-management handoff. Reads the estimate via the BidSheet.ai MCP; writes local files and (opt-in) the enriched IFC.
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Cost- & Resource-Load a Schedule (5D)

Use this once a project has (a) a confirmed 4D `CanonicalSchedule` whose tasks
carry `bid_item_codes` (from the `stage-model` skill in the **calc-bim** plugin)
and (b) a priced estimate in BidSheet.ai. It answers "how much money goes out, when" (cash-flow S-curve)
and "how many workers each stage needs" (manpower), and — opt-in — writes those
into the IFC so job management's tools (Synchro / P6 / Navisworks) read them.

## Inputs
- The schedule JSON (the `CanonicalSchedule` `stage-model` resolved) and, if
  embedding, the 4D IFC it produced.
- The BidSheet.ai `estimate_id` (or `project_id` → resolve the estimate).

## Sub-scope schedules (GC master schedule in hand)
When the schedule on hand is the GC's **full** project schedule and the
estimate covers only a subcontractor's scope, filter before loading — do not
costload the whole job:

1. Discover the filter key:
   `est-schedule scope <gc-schedule.{xer,xml,mspdi,gw.json,json}>
   --list-resources` (or `--list-codes`), and pick the resource / activity
   code that marks the sub's work.
2. Filter: `est-schedule scope <gc-schedule.xer> --resource <X> -o
   filtered.json [--xlsx tasktable.xlsx]` (or `--activity-code <Y>`). It keeps
   the matched tasks plus their ancestor summaries, and splits predecessors:
   internal ones stay as dependencies; ties to tasks outside the scope are
   preserved in each task's `external_dependencies` (the "External Preds"
   column in the xlsx).
3. **Review the external dependencies with the user.** They represent ties to
   other parties' work — the sub's true float and general-conditions exposure
   (a GC slip on an external pred moves the sub's start). Review them; never
   discard them.
4. Costload the filtered canonical JSON as usual (Workflow below).

## Workflow
1. **Assemble the cost record from BidSheet.ai.** Build the cost record:

   ```
   costs = {bid_item_code: {"cost": <installed cost>, "labor_hours": <hours|null>,
                            "unit_price": <BM unit price>, "unit": "<pay unit>"}}
   ```

   - `mcp__bidmanager__get_estimate_summary(estimate_id)` and/or `mcp__bidmanager__list_estimate_items(estimate_id)`
     for each item's total cost and its bid-item code.
   - Labor-hours per item: sum the **labor** components of the item's assemblies
     (`mcp__bidmanager__list_components` under the item's assembly; a labor component's quantity
     is hours). If an item has no labor breakdown (lump-sum sub), set
     `labor_hours` to `null` — it stays in cash flow but contributes no workers.
   - Record each bid item's `unit_price` and pay `unit` alongside. If one code
     maps to several bid items (the takeoff map's plural `measures:`), both
     fields take `{item_number: value}` objects instead of scalars.
     `est-bim cost5d` ignores these two fields — the same `costs.json` serves
     both embeds.
   Write `costs.json`.
2. **Run the load (analysis):**
   `est-schedule costload --schedule <sched.json> --costs <costs.json>
   [--task-map <map.json>] [--work-hours-per-day 8] [--bucket month|week]
   [--csv <out.csv>] [--xlsx <out.xlsx>]` — stdout is the markdown cash-flow +
   manpower board; show it to the user **verbatim**. `--json` for machine use.
3. **Read the coverage review (stderr).** Unloaded cost (priced items with no
   task — their money is off the curve), items priced without labor (zero
   workers), and unpriced tasks are each listed. Surface them: they are not
   cosmetic — the curve is only as complete as the mapping.
4. **Offer the handoff files.** The CSV/xlsx is the cost-loaded schedule for the
   job-management team.
5. **Embed into the IFC (opt-in).** If the user wants the enriched model, run
   `est-bim cost5d --ifc <4d.ifc> --schedule <sched.json> --costs <costs.json>
   [--work-hours-per-day 8] [--out <5d.ifc>]`. It adds one `IfcCostSchedule`
   (cost per task) and labor resources (`IfcLaborResource` + `IfcResourceTime`)
   assigned to the existing 4D tasks; re-runs replace them by name. Hand the
   `<5d.ifc>` to `show-structure-earth` / the interop path.

   To read a 5D model back (yours, or one received), run
   `est-bim schedule-read --ifc <5d.ifc> --out <sched.json> --costs-out <costs.json>`.
   The costs JSON has four parts:
   - `schedule` is the name of the work schedule the costs were read from;
   - `costs` is the `{code: {cost, labor_hours}}` record, the same shape the
     `--costs` input above takes;
   - `tasks` holds each task's own costs and crew hours, keyed by the task ids
     in `<sched.json>`;
   - `warnings` lists anything that couldn't be read back exactly.

   A model embedded before 0.1.87 records crew hours per task only, so a
   multi-code task's hours are split by cost and listed in `warnings`.
6. **ESTIMATE snapshot (optional).** If the user also wants the bid-time
   quantity-backed schedule, run
   `est-bim estimate5d --ifc <ifc> --map <takeoff_map.yaml> --costs costs.json`.
   It authors an ESTIMATE `IfcCostSchedule` — one parent `IfcCostItem` per bid
   item, one child per element whose `CostQuantities` reference the element's
   own Qto entity — and prints a per-code variance comparing rate × model
   quantity to the BM lump cost. It needs no schedule/4D — it runs on the bare
   takeoff IFC — and the BUDGET schedule from `cost5d` is untouched (the two
   coexist).

## Notes
- The deterministic packages never touch BidSheet.ai; this skill does the MCP
  reads and writes the `costs.json` the CLIs consume.
- Distribution is duration-weighted, uniform per work-day, honoring the
  schedule calendar (see the 5D design spec). Loading curves, earned-value, and
  equipment/material loading are out of scope for v1.
- If BidSheet.ai is unreachable, hand-supply `costs.json` (same shape) — the CLIs
  are offline-only by design.
