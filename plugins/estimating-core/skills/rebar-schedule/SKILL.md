---
name: rebar-schedule
description: Build a bar bending schedule (BBS) with cut lengths and weights from structural drawings, then route the LBS weight into the estimate. Use when the user has rebar drawings/schedules and wants cut lengths, weights, an xlsx BBS, or that weight priced into the estimate. Triggers include "bar bending schedule", "rebar takeoff", "BBS", "rebar weight", "schedule the rebar".
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

# Rebar — Bar Bending Schedule + LBS Takeoff

Turn rebar marks read off structural drawings into a bar bending schedule
(BBS) with cut lengths and weights (`~/.estimating/bin/est-rebar schedule`), review it with the
user, then route the resulting LBS weight into the estimate. `est-rebar` is
deterministic arithmetic; **you** are the drawing reader — every mark you
author must trace back to a sheet.

**Estimating-aid caveat.** Cut lengths use ACI 318-19 standard hook
allowances (`rebar/detailing.py`) and, where development/lap lengths are
needed, the simplified ACI 318-19 Table 25.4.2.3 method (`rebar/develop.py`)
— both conservative-tier, documented assumptions, not a substitute for the
engineer of record's detailing. State this to the user when handing over the
BBS: **design/detailing governs**; this schedule is for pricing.

## Inputs
- Structural drawings or a rebar schedule sheet naming bar marks, sizes,
  counts, leg lengths, and hook types.
- The target `item_number`/`cost_code`/`schedule` the weight should land on
  in the estimate (ask if unclear), and whether this is a live bid (routes
  through `apply-takeoff`) or a scratch/sandbox exercise.

## Workflow

1. **Author the bars YAML from the drawings — agent judgment.** For each
   mark, record:
   - `mark`: the drawing's label (e.g. `"A1"`)
   - `size`: the bar number as an int (e.g. `5` for #5)
   - `count`: a **whole number** of bars for this mark
   - `legs_in`: straight leg lengths in inches, e.g. `[96, 24]`
   - `hooks`: zero or more of `90`, `180`, `stirrup90`, `stirrup135`,
     `stirrup180` (stirrup hooks apply to #3-#8 only) — each adds one hook
     allowance (bend arc + extension) to the cut length
   - `note`: **cite the sheet/detail** this mark came from (e.g.
     `"S-3 detail 4, footing F1 dowels"`) — never invent a mark's geometry
     without a source; if a dimension is illegible or ambiguous, ask the
     user rather than guessing.

   ```yaml
   title: Footing F1 Rebar
   marks:
     - mark: A1
       size: 5
       count: 20
       legs_in: [96, 24]
       hooks: ["90"]
       note: "S-3 detail 4/S-3, footing F1 dowels"
   ```

   Any bad mark (unknown size, invalid hook, fractional count, duplicate
   mark) is rejected with a message naming the offending mark — fix the
   entry and re-run rather than working around it.

2. **Build the schedule (and, when you have a routing target, the takeoff
   row) in one pass:**
   ```bash
   ~/.estimating/bin/est-rebar schedule bars.yaml --out-dir <bid_dir>/Sheets --xlsx \
       --takeoff takeoff.json --organization-id <org_id> \
       [--cost-code <code>] [--item-number <item>] \
       [--schedule <schedule>] [--project-ref <ref>]
   ```
   Always writes `<slug>.md`; `--xlsx` also writes a styled `<slug>.xlsx`
   (clean error if `openpyxl`/the `excel` extra is missing). `--takeoff`
   writes a `CanonicalTakeoff` JSON with **one** quantity row: `unit="LBS"`,
   `quantity = total_weight_lb * 1.08` — the fixed rebar waste factor
   (`WASTE_FACTORS["rebar"]`; there is no CLI override for it), `notes`
   listing every mark rolled into the total. `--organization-id` is required
   whenever `--takeoff` is passed.

3. **Review the BBS with the user before routing anything.** Show the
   markdown table (mark, size, count, legs, hooks, cut length ft, weight lb)
   and the schedule total. Flag any mark whose `note` doesn't cite a
   drawing/detail — that's a sign it was guessed rather than read.

4. **Route the LBS weight into the estimate — do not use push-takeoff's
   default target.** This is the one non-obvious step: the takeoff row
   `est-rebar` emits is a schedule-level LBS total with **no `elements`**
   breakdown (there's no per-element geometry for a bar list — just a
   weight). `push-takeoff`'s default `estimate-structures` target plans
   *structure sections* from `row.elements`; a row with none lands in that
   plan's `unresolved` list with the message "no elements on the row —
   regenerate the takeoff with est-bim >= 0.1.11 (or add elements)" — which
   is **misleading here**: there's nothing to regenerate, the row was never
   meant to carry elements. Route explicitly instead, by one of:

   - **Live estimating (the normal case) — the estimate-spec quantity
     path:**
     ```bash
     ~/.estimating/bin/est-estimate apply-takeoff <bid>.estimate.yaml --takeoff takeoff.json \
         [--force] --report apply-report.md
     ```
     This matches the takeoff row onto a spec item by `(schedule,
     item_number)` (falling back to `cost_code`) and sets that item's `qty`
     to the weight (with waste already applied). Before routing, confirm the
     target item's `uom` is `LBS` — apply-takeoff does not check units, and
     a weight silently landing on a CY line would corrupt the estimate. Because the row has no
     `elements`, only `qty` changes — no geometry rebuild is attempted, which
     is expected for a rebar weight line, not a bug. Show the user
     `apply-report.md` (matched/unchanged/skipped/unmatched) same as
     `build-estimate-workbook`'s apply-takeoff step.
   - **Scratch/sandbox projects only — the legacy bid-item-quantity push,
     WARNING-stamped and forbidden on live bids (BM #984):**
     ```bash
     ~/.estimating/bin/est-takeoff plan takeoff.json --target bid-item-quantities \
         [--existing existing.json] -o plan.json
     ```
     Every plan from this target carries `"WARNING": "writes OFFICIAL agency
     schedule quantities — forbidden on live bids; see BM #984"` (canonical
     rule: the `estimator-agent` agent's BidSheet.ai write safety). Render it
     for review with `render_takeoff_push_plan` (see `push-takeoff`'s Legacy
     target section) and only execute the resulting
     `bulk_update_bid_items`/`bulk_create_bid_items` calls on a
     scratch/sandbox project, with the user's explicit, informed
     confirmation — never on a live bid.

5. **Report** what you built (schedule totals, weight by size) and how you
   routed it (which item/qty changed, or the sandbox plan reviewed) — never
   silently drop the weight after generating the BBS.

## Notes
- `~/.estimating/bin/est-rebar develop --size 5 --fc 4000 [--fy 60000] [--top-bar] [--epoxy]
  [--lightweight] [--lap A|B]` prints ACI development (`ld`) and lap-splice
  lengths for a single bar size — useful for a quick check while authoring
  marks, independent of the schedule command.
- The waste factor (1.08) is baked into the takeoff row's quantity; don't
  apply it again downstream.
- `IfcReinforcingBar` authoring (bar geometry into the IFC) is a separate,
  lower-level capability (`estimating_tools.rebar.ifc.add_reinforcing_bars`)
  — this skill covers pricing (BBS + LBS weight), not IFC modeling.
