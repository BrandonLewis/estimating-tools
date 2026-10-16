---
name: build-assemblies
description: Workflow for building detailed assembly cost breakdowns on BidSheet.ai estimate items — select items, create assemblies, add components from rate library. Reviewed via an editable live artifact in the conversation; writes to BidSheet.ai (for a local spreadsheet deliverable use build-estimate-workbook instead).
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

> **Display contract:** Show `render` output to the user **verbatim in a fenced code block** — never reformat it, add/remove columns, or substitute your own table; `parse` depends on the exact shape. If the `open_artifact_editor` tool (artifact-editor server) is available, ALSO call it — `open_artifact_editor(markdown=<rendered, verbatim>, title="<title>", editable=<false for read-only plan renders>)` — and tell the user to edit in the inline panel and click **Save & send to chat**; their edits arrive as a chat message. In the terminal, the same tool instead opens the editor in the user's web browser and returns the saved block directly in the tool result — parse and push it when it returns (Save = the user's consent). If the wait expires, call `collect_artifact_edits` after the user says they've saved. If the tool is missing or errors, show the live page built by:
>
> ```python
> from estimating_tools.artifacts_html import to_editable_html
> page = to_editable_html(rendered, title="<title>")
> ```
>
> Prefer the host's native artifact mechanism (present `page` as a live HTML artifact); if the host only renders files, write it to `<slug>.artifact.html` (named after the artifact so successive renders don't overwrite each other). For editable artifacts, point the user at the page's **Copy edited artifact** button; for read-only plan renders, pass `editable=False` (the page has no button). Run `parse` only on text the user provides — the Save message, the pasted export, or their edited block — never on your own restatement of it.

# Build Assembly Breakdowns

Follow this workflow when asked to create detailed cost breakdowns for bid items.

## The roll-up contract (read before authoring)

> **Enforced in code (issue #201).** Do not hand-shape the
> `bulk_create_assemblies`/`create_component` payloads and trust this prose —
> route the push through `plan_assembly_load` (Step 4). It raises on the three
> traps below (a production-basis crew with no `production_rate`, a `quantity=0`
> line, an unknown `labor_cost_basis`) so the wrong encoding is *unauthorable*
> rather than merely discouraged. The contract is explained here so the numbers
> are legible; the planner is what guarantees them.

**A production-basis labor component contributes `cost = quantity × unit_cost ×
production_rate`.** For a CREW assembly, author the readable crew-composition
shape:

- assembly `production_rate` = the crew-hours for the task (in `production_unit`
  HOURS), on the **CREW** assembly,
- one component per trade: `quantity` = headcount, `unit_cost` = hourly rate,
  `labor_cost_basis="production"` (the default),
- so each component rolls up `headcount × hourly_rate × crew_hours` and the
  crew makeup stays legible from the rows.

Example (verified live): a Set-Faces crew of 1 FORE + 2 CARP + 1 LAB
(175 / 165 / 150 $/hr) over 43.65 crew-hr rolls up Foreman `1 × 175 × 43.65 =
7,638.75`, Carpenter `2 × 165 × 43.65 = 14,404.50`, Laborer `1 × 150 × 43.65 =
6,547.50` → `cost_breakdown.labor = total = 28,590.75`. You do **not** need to
pre-multiply men × hours into `quantity`; production_rate carries the duration.

**Three pitfalls to avoid:**

- **Unset `production_rate` on a CREW assembly rolls up $0 labor.** The whole
  buildup then contributes the bare component `quantity × unit_cost` (an hourly
  rate, not the extended cost). Always set the assembly's `production_rate`.
  (The `create_assembly` tool documents this: "leaving it unset makes
  production-basis labor roll up $0.")
- **`has_detailed_breakdown: true` does not imply the breakdown carries cost.**
  Assigning any assembly flips the item to `has_detailed_breakdown: true` /
  `pricing_source: "detailed_breakdown"`, so it can LOOK priced while a
  zero-production_rate crew carries no labor.
- **Zeros are silently rewritten — a $0 line becomes a phantom charge.**
  `create_component`/`update_component` coerce `quantity=0` to `1.0` and
  ignore `unit_cost=0` (AAR 2026-07-29 §2.1: "the zero became a one,
  inventing a $300 charge"). A legitimate $0 placeholder cannot be stored:
  omit the component, note it in the assembly/item description, and read
  the assembly back whenever a zero matters. Field limits + precision:
  see the api-constraints reference.

Historical note: a mis-cased `component_type` ("LABOR" vs "labor") used to drop
a component out of every cost bucket silently — BidSheet.ai BM-2, fixed
2026-08-06 (the tool now normalizes case on write, and rejects unknown types).
Pass lowercase types (`labor`/`material`/`equipment`/`subcontractor`/`other`)
regardless.

**Post-authoring verification (recommended):** read the assembly back with
`get_assembly(assembly_id)` and confirm `cost_breakdown.labor` is the extended
figure (not a bare hourly rate) and each labor component shows
`has_missing_production_data: false` before trusting the item as priced.

## Component order and write pacing

- **Display order is alphabetical — `sort_order` is not exposed** through
  the MCP, and bracket prefixes don't group ("[C]" sorts between "C" and
  "CONCRETE", interleaving labor with materials). When order matters,
  prefix component names with two-digit numerics (`01 `, `02 `, …).
  Upstream ask BM#1137 to expose `sort_order`.
- **Pace the writes.** The BM MCP rate limiter counts reads too and locks
  out for ~7–10 minutes with no Retry-After; ~10–15 rapid calls or any
  parallel burst can trigger it. Run calls serially, and after a lockout
  wait the full window before retrying (an observed 180 s wait was not
  enough; 420 s was).

## Steps

1. **Identify the target estimate item.** Use `list_estimate_items(estimate_id)` to pick
   the item that needs a detailed breakdown. Record its `bid_item_id`, its
   `estimate_item_id`, and the item's `description` / `assembly_type` (a hint for what
   assembly type to use) / `cost_code` (from the item template) — these become the
   assembly meta.

2. **Fetch or draft the initial assembly.**
   - **Existing assembly on the item:** `list_assemblies(context='estimate',
     context_id=estimate_item_id)` → if one exists, `get_assembly(assembly_id)` and
     `list_components(assembly_id)`. Build a canonical `Assembly` dataclass from the
     result:

     ```python
     from estimating_tools.assemblies.model import Assembly, Component

     original = Assembly(
         name=bm_assembly["name"],
         assembly_type=bm_assembly["assembly_type"] or "",
         cost_code=bm_assembly.get("cost_code"),
         description=bm_assembly.get("description") or "",
         components=[
             Component(
                 component_type=c["component_type"],
                 name=c["name"],
                 quantity=float(c["quantity"]),
                 unit=c.get("unit") or "",
                 unit_cost=float(c["unit_cost"]) if c.get("unit_cost") is not None else None,
                 rate_ref=c.get("rate_ref"),
                 trade=c.get("trade") or "",
                 description=c.get("description") or "",
             )
             for c in bm_components
         ],
     )
     ```

   - **No existing assembly:** either `clone_assembly(template_id, 'estimate',
     estimate_item_id)` (if a template fits) and then fetch as above, OR draft an empty
     skeleton `original = Assembly(name=…, assembly_type=…, cost_code=…, description="",
     components=[])`.

3. **Render → user edits → parse.** Render the initial assembly, let the user edit it
   in the panel (or a pasted block), and parse the text they send back:

   ```python
   from estimating_tools.assemblies.artifact import parse_single_with_meta, render_single

   print(render_single(original))
   # ... user_edited_text = the Save message (or a pasted block) ...
   edited = parse_single_with_meta(
       user_edited_text,
       name=original.name,
       assembly_type=original.assembly_type,
       cost_code=original.cost_code,
   )
   ```

   The rendered block is an optional `> description` blockquote + a components table
   (columns: `component_type`, `component`, `quantity`, `unit`, `unit_cost`,
   `rate_ref`, `trade`, `description`). Users can rename a component, tweak
   quantities / rates, add or remove rows. `-` in any optional cell means "unset".
   `parse_single_with_meta` uses the caller-supplied meta and raises `ValueError`
   with a row locator on malformed input.

4. **Plan the write through `plan_assembly_load`, then apply it.** Which path
   depends on whether you are authoring a fresh buildup or editing an existing one.

   **Path A — author / cost-load a fresh item (the common case, incl. the
   takeoff→structures cost-load).** Build a `CanonicalAssemblyLoad` from the
   confirmed assemblies, plan it (traps enforced here), show the load-plan render
   for a final confirm, then create:

   ```python
   from estimating_tools.assemblies import (
       CanonicalAssemblyLoad, AssemblyLoadItem, LoadAssembly, LoadComponent,
       plan_assembly_load, render_assembly_load_plan,
   )

   load = CanonicalAssemblyLoad(items=[AssemblyLoadItem(
       estimate_item_id=estimate_item_id, bid_item_code=bid_item_code,
       assemblies=[LoadAssembly(
           name=edited.name, assembly_type=edited.assembly_type,
           cost_code=edited.cost_code, description=edited.description,
           production_rate=<crew-hours>, production_unit="HOURS",
           components=[LoadComponent(
               component_type=c.component_type, name=c.name, quantity=c.quantity,
               unit=c.unit, unit_cost=c.unit_cost, rate_ref=c.rate_ref,
               trade=c.trade, description=c.description,
               labor_cost_basis="production",   # or "flat"
           ) for c in edited.components],
       )],
   )])
   plan = plan_assembly_load(load, estimate_id)      # raises on the 3 traps
   print(render_assembly_load_plan(plan))            # read-only confirm (verbatim)
   ```

   `render_assembly_load_plan` is a **read-only** confirmation render (per the
   Display contract, `editable=False`) — it shows each component's rolled-up cost
   and a `## Flagged` list of non-routable `rate_refs`. It has no `parse`
   counterpart; the editing already happened per-assembly in Step 3. After the
   user confirms, push each `plan.assemblies` entry:
   - `create_assembly(name=…, assembly_type=…, context='estimate',
     context_id=estimate_item_id, description=…, production_rate=…,
     activity_code_id=<resolved from cost_code>)` — one per assembly.
   - For each component payload: if `rate_resolution` is set (`{kind, key}`),
     resolve `key` against the org rate library (`list_labor_rates` /
     `list_equipment_rates` / `list_material_costs`, routed by `kind`) to its id;
     then `create_component(assembly_id, component_type, name, quantity, unit,
     unit_cost, trade, description, <labor_rate_id | equipment_rate_id |
     material_cost_id>=<resolved>)`. Components in the plan's `rate_refs`
     (subcontractor/other) have no routable id — they fall back to the inline
     `unit_cost`; surface them from the `## Flagged` section.

   **Path B — incremental edit of an existing assembly.** Keep the component
   diff, but **validate through the planner first** so the traps fire in code
   before any write. Build the validation `LoadAssembly` from the **BidSheet.ai
   metadata**, not from the edit model: `assemblies.model.Assembly`/`Component`
   (Steps 2–3) carry no `production_rate` / `production_unit` /
   `labor_cost_basis`, so wrapping `edited` directly would default a real crew to
   no production rate and `plan_assembly_load` would reject it. The component
   table can't edit those fields anyway — read them back from the
   `get_assembly` / `list_components` response (`bm_assembly` / `bm_components`),
   matching each edited component to its BM row by `(component_type, name)` and
   defaulting a newly added row to `"production"`:

   ```python
   from estimating_tools.assemblies import (
       CanonicalAssemblyLoad, AssemblyLoadItem, LoadAssembly, LoadComponent,
       plan_assembly_load,
   )
   from estimating_tools.assemblies.artifact import diff_components

   basis = {(c["component_type"], c["name"]): (c.get("labor_cost_basis") or "production")
            for c in bm_components}
   plan_assembly_load(CanonicalAssemblyLoad(items=[AssemblyLoadItem(
       estimate_item_id=estimate_item_id,
       assemblies=[LoadAssembly(
           name=edited.name, assembly_type=edited.assembly_type,
           cost_code=edited.cost_code,
           production_rate=bm_assembly.get("production_rate"),
           production_unit=bm_assembly.get("production_unit") or "HOURS",
           components=[LoadComponent(
               component_type=c.component_type, name=c.name, quantity=c.quantity,
               unit=c.unit, unit_cost=c.unit_cost, rate_ref=c.rate_ref,
               trade=c.trade, description=c.description,
               labor_cost_basis=basis.get((c.component_type, c.name), "production"),
           ) for c in edited.components],
       )],
   )]), estimate_id)   # raises on the traps; proceed only if it returns

   diff = diff_components(original.components, edited.components)
   ```

   Route each diff entry:
   - **`to_create`:** resolve rates as in Path A, then `create_component(…)`.
   - **`to_update`:** `update_component(component_id, …)` with the differing
     fields. Look up `component_id` from the fetched `bm_components` by matching
     `(component_type, name)` on `original`.
   - **`to_delete`:** look up `component_id` the same way, then
     `delete_component(component_id)`.

   If the assembly's own metadata changed (description, cost_code, or
   production_rate), call `update_assembly(assembly_id, …)` before the components.

5. **Verify.** `get_assembly(assembly_id)` and confirm the total cost + component
   counts match the load-plan render (Path A) or the user's edited plan (Path B).
   Report a summary: assemblies + components created / updated / deleted, and any
   rate refs that could not be resolved (which fell back to inline `unit_cost`).

## Tips

- Field limits + write-precision by field (`estimated_unit_price` rounds to
  2 dp silently): see the api-constraints reference in the `estimating-reference`
  skill (`../estimating-reference/references/api-constraints.md`)
- Structure assemblies map to physical elements (manhole base, walls, deck)
- Use the rate library for consistent pricing across assemblies
- Include waste factors for materials (typically 5-15%)
- Check production rates match crew composition — a CREW assembly's
  `production_rate` (crew-hours) DOES extend into cost per the roll-up contract
  above; an unset production_rate is what rolls up $0
