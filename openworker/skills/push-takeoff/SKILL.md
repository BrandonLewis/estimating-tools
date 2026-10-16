---
name: push-takeoff
description: Push a completed quantity takeoff into BidSheet.ai — takeoff quantities land on the ESTIMATE layer as structure sections (mcp__bidmanager__create_structure/mcp__bidmanager__add_structure_section), never on official bid-item quantities, via the BidSheet.ai MCP. Model quantities are surfaced as a read-only advisory check; the legacy bid-item-quantity target is forbidden on live bids (BM issue 984).
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

> **On OpenWorker:** the `artifact-editor` server is not shipped in this build, so its tools are absent. Skip the `mcp__artifact-editor__open_artifact_editor` branch below and go straight to the `to_editable_html` page path. If the session has `send_file` (a messaging persona), hand the written `.artifact.html` to the user with it.

> **Display contract:** Show `render` output to the user **verbatim in a fenced code block** — never reformat it, add/remove columns, or substitute your own table; `parse` depends on the exact shape. If the `mcp__artifact-editor__open_artifact_editor` tool (artifact-editor server) is available, ALSO call it — `mcp__artifact-editor__open_artifact_editor(markdown=<rendered, verbatim>, title="<title>", editable=<false for read-only plan renders>)` — and tell the user to edit in the inline panel and click **Save & send to chat**; their edits arrive as a chat message. In the terminal, the same tool instead opens the editor in the user's web browser and returns the saved block directly in the tool result — parse and push it when it returns (Save = the user's consent). If the wait expires, call `mcp__artifact-editor__collect_artifact_edits` after the user says they've saved. If the tool is missing or errors, show the live page built by:
>
> ```python
> from estimating_tools.artifacts_html import to_editable_html
> page = to_editable_html(rendered, title="<title>")
> ```
>
> Prefer the host's native artifact mechanism (present `page` as a live HTML artifact); if the host only renders files, write it to `<slug>.artifact.html` (named after the artifact so successive renders don't overwrite each other). For editable artifacts, point the user at the page's **Copy edited artifact** button; for read-only plan renders, pass `editable=False` (the page has no button). Run `parse` only on text the user provides — the Save message, the pasted export, or their edited block — never on your own restatement of it.

# Push a Takeoff into BidSheet.ai

Use this after `quantity-takeoff` (or the calc-bim plugin's `bim-to-takeoff`) to load a measured
takeoff into a BidSheet.ai project. Requires the BidSheet.ai MCP connected.
For the workbook leg of the same CanonicalTakeoff — measured quantities and
geometry onto a local `*.estimate.yaml` — use `est-estimate apply-takeoff`
(see the build-estimate-workbook skill); the BM structures push and the
workbook application are siblings fed by the same file. Before pushing,
`est-takeoff audit --strict` (the `audit-quantities` skill) verifies the
takeoff against the model and estimate.

**Where takeoff quantities go — the iron rule.** `ProjectBidItem.quantity` is
the OFFICIAL agency schedule quantity (a single field, also displayed by
estimate items). It is **immutable by convention** — writing takeoff
quantities there corrupted a live bid schedule (BidSheet.ai issue #984,
2026-08). Takeoff quantities therefore land on the **estimate layer as
Structures**: each takeoff element becomes a structure section whose
`dimensions` (lowercase `length`/`width`/`height` keys, in FEET) drive the
Structures grid's CY computation. Model quantities are only ever *compared*
against the official schedule as a read-only advisory. (Canonical
statement: the `estimator-agent` agent's BidSheet.ai write safety section.)

## Inputs
- A `CanonicalTakeoff` JSON: `{organization_id, project_ref?, rows:[TakeoffRow]}`
  where a quantity row has `{description, kind:"quantity", quantity, unit,
  item_number?, cost_code?, schedule?, elements?}`. `elements` is the
  per-element breakdown (`{name, section_type, count, length_ft, width_ft,
  height_ft}`) — `bim-to-takeoff` emits it; hand-built takeoffs should too.
- The target `project_id` and the estimate the structures belong to. Confirm
  with the user if unknown.
- A structure id (`--structure-id`, else the takeoff's `project_ref` is used).

## Workflow
1. **Build the plan deterministically:**
   `est-takeoff plan takeoff.json --structure-id <id>` (or call
   `plan_takeoff_push(CanonicalTakeoff, structure_id=...)` in-process; the
   default target is `estimate-structures`). The plan has `structure_plans`,
   `advisory_quantity_check`, `unresolved`, `unsupported` — and **no**
   quantity writes.
2. **Review the plan with the user** before writing: show each planned
   structure (item_number, schedule, structure_id, its sections with
   section_type / custom_name / dimensions), the advisory quantity rows, and
   every `unresolved` row (rows without `elements` cannot plan sections —
   regenerate the takeoff with est-bim >= 0.1.11 or add elements).
3. **Resolve the estimate item** each structure hangs off:
   `mcp__bidmanager__list_estimate_items(estimate_id)` and match by the plan entry's
   `item_number`/`schedule`. Confirm ambiguous matches with the user.
4. **Apply structures:** for each entry in `structure_plans`, call
   `mcp__bidmanager__create_structure(estimate_item_id, structure_id=entry["structure_id"],
   sections=entry["sections"], dimensions=...)` — each section becomes an
   assembly with its `concrete_section_type` and a `dimensions` JSON whose
   lowercase `length`/`width`/`height` keys (FEET) drive the grid's CY math.
   Append further sections with `mcp__bidmanager__add_structure_section` (pass
   `allow_duplicate` for repeated section types, `custom_name` for e.g.
   "Wing Wall A1 West" — both are already set per section in the plan).
   4a. **Absorb the scaffold's empty `- Structures` placeholder.**
   `scaffold-project` (and new-estimate creation) seeds every item's detailed
   breakdown with five empty bucket assemblies — `"<ITEM DESC> - Structures"`
   (assembly_type `STRUCTURE`, **blank `concrete_section_type`**, no
   dimensions/components), plus `- Labor` (CREW), `- Subcontractors`,
   `- Equipment`, `- Materials`. Once you have landed real sections on an
   item, that empty `- Structures` bucket is a redundant duplicate sitting
   beside them. Absorb it: `mcp__bidmanager__list_assemblies(context="estimate",
   context_id=<estimate_item_id>, assembly_type="STRUCTURE")`, pick the entry
   whose name ends `" - Structures"`, confirm via `mcp__bidmanager__get_assembly` that its
   `concrete_section_type` is blank, its `components` are empty, AND its
   `dimensions` are absent/empty (a real pushed section carries `dimensions`
   even with no components — never delete one), then `mcp__bidmanager__delete_assembly` it (a
   reversible soft-delete). **Guards:** only ever remove the blank-typed,
   empty, name-ends-`- Structures` bucket — NEVER a section carrying a real
   `concrete_section_type`, dimensions, or components,
   and NEVER on an item where you did not land sections (its scaffold stays as
   authored). Leave the `- Labor`/`- Subcontractors`/`- Equipment`/
   `- Materials` buckets untouched — that is where item-level phase cost lives.
5. **Advisory quantity check (read-only):** for each
   `advisory_quantity_check` row, compare `model_qty` against the bid item's
   official quantity (`mcp__bidmanager__list_bid_items(project_id)`) and REPORT any deltas to
   the user. Do **not** write quantities — flag discrepancies for the
   estimator to raise with the agency instead.
6. **Estimated-vs-pay quantity decision (`quantity_override`):** a takeoff
   quantity is a COST quantity; the bid schedule holds the PAY quantity —
   they are legitimately different numbers and the estimate must carry both.
   When the advisory check (or the estimator) shows the measured quantity
   differs from the official schedule quantity, do NOT reconcile them by
   editing either one to match the other: the bid item keeps the pay
   quantity (the iron rule above — reinforced, never an exception), and the
   estimate item takes the cost quantity via
   `mcp__bidmanager__update_estimate_item(item_id, quantity_override=<cost quantity>)`.
   Costs then extend over the true measured quantity while the **bid unit
   price is derived as total cost ÷ pay quantity**. Example: bid item 35
   pays 326 LF of pile but the takeoff measures 475 LF furnished-and-driven
   — set `quantity_override = 475`, build cost on 475 LF (475 × $333.90/LF
   = $158,602.50), and the bid unit price is $158,602.50 ÷ 326 LF =
   $486.51/LF, **not** the $333.90/LF cost rate. Pushing 475 onto the bid
   item corrupts the schedule; pricing only 326 hides a third of the cost.
   `quantity_override` keeps up to **4 decimal places** (BM-5, fixed
   2026-08-06) — takeoff quantities carry their tail, so send the measured
   value directly (no pre-rounding needed).
7. **Report:** show counts of structures created / sections added, the
   advisory comparison table, then list every `unresolved` and `unsupported`
   (material/structure-kind rows, later release) row — never drop these
   silently. State which structures remain non-costing (see "Pushed
   structures are stored, not priced" below).

## Pushed structures are stored, not priced

`mcp__bidmanager__create_structure`/`mcp__bidmanager__add_structure_section` leave each section with
`components: []`, `structure_count: null`, `production_rate: null`
(AAR 2026-07-29 §2.7) — the takeoff is stored but **invisible to
costing**: nothing rolls up until the sections carry assemblies with
components. After the push:

- set each section's `structure_count` where the takeoff element carries a
  `count` (left `null`, the section multiplies as nothing — not as one);
- build the cost side (components, crew `production_rate`) with the
  `build-assemblies` workflow, or price at the item level via
  `price-estimate`;
- report the state honestly — "N structures pushed, 0 costed" — and never
  imply pushed ⇒ priced.

## Legacy target (forbidden on live bids)
`est-takeoff plan --target bid-item-quantities` still produces the old
`quantity_updates`/`quantity_creates` plan for `mcp__bidmanager__bulk_update_bid_items` /
`mcp__bidmanager__bulk_create_bid_items`, and every such plan carries
`"WARNING": "writes OFFICIAL agency schedule quantities — forbidden on live
bids; see BM #984"`. Only use it on scratch/sandbox projects with the user's
explicit, informed confirmation — never on a live bid. Render it for review
with:

```python
from estimating_tools.takeoff.push import render_takeoff_push_plan

print(render_takeoff_push_plan(plan))
```

## Notes
- `measure-plans`, `dxf-to-bim`, `bim-to-takeoff`, and `show-structure-earth` ship in the **calc-bim plugin** (same estimating-platform marketplace as this plugin). If they are not among your available skills, tell the user this workflow needs the calc-bim plugin installed (`/plugin` -> estimating-platform -> calc-bim) and offer to continue with the bundled `est-bim` CLI directly.
- Field limits + write-precision by field (`quantity_override` keeps 4 dp;
  `estimated_unit_price` still rounds to 2 dp silently): see the api-constraints
  reference in the `estimating-reference` skill
  (`../estimating-reference/references/api-constraints.md`).
- Re-running the structures path is guarded by review, not blind idempotency:
  `mcp__bidmanager__create_structure` on an item that already carries the structure would
  duplicate sections — check `mcp__bidmanager__get_structure`/`mcp__bidmanager__list_structures` first and
  switch to `mcp__bidmanager__add_structure_section` for increments.
- The BidSheet.ai write calls are **non-transactional** (partial success is
  the default) — inspect each call's response and report per-item failures
  rather than assuming all succeeded.
- Prices are untouched — `unit_price` stays a `price-estimate` concern.
- Clone-not-mutate still governs assemblies: only assemblies owned by the
  current estimate item may be written (`assert_estimate_owned`).
- The shapes above are drawn from the documented BidSheet.ai MCP tool
  schemas; a live end-to-end run against a scratch project is still
  recommended before relying on this in production.
