---
name: bm-sync
description: Push local estimate-spec edits back to BidSheet.ai — diff a pre-edit snapshot against the edited spec with plan_sync, review the sync plan, then execute rate/crew/item creates, updates, and deletes via the BidSheet.ai MCP with estimate_item_id writeback.
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

# Sync an Edited Estimate Spec to BidSheet.ai

Use this after editing an estimate spec (typically via the editable compact
view — `render_compact` / `parse_compact`) to push the edits back to
BidSheet.ai. Requires the BidSheet.ai MCP to be connected.

The diff and the execution logic are deterministic
(`estimating_tools.estimate_spec.sync.plan_sync` and
`estimating_tools.estimate_spec.sync_executor.run_sync`); the judgment is
resolving the BM estimate context and confirming the plan with the user.

## Inputs

- `base_spec`: the pre-edit snapshot (the spec as of the last BM fetch).
- `edited_spec`: the post-edit spec (e.g. `parse_compact` output written to
  disk). This file is MUTATED by the sync: new items get their BM
  `estimate_item_id` written back.
- BM context: `estimate_id` (and its `project_id` / `organization_id`).
  Ask the user if not known.

## Workflow

1. **Build and review the plan:**

   ```python
   import yaml
   from estimating_tools.estimate_spec.sync import plan_sync, render_sync_plan

   base = yaml.safe_load(open(base_path))
   edited = yaml.safe_load(open(edited_path))
   plan = plan_sync(base, edited)
   print(render_sync_plan(plan))
   ```

   If the plan is empty (no ops in any section), report "nothing to sync"
   and stop. Otherwise show the rendered plan and ask the user to confirm
   before any BM write. If they want changes, they edit the spec and you
   rebuild the plan; the render is not editable.

2. **Bind the client.** `run_sync` calls plain keyword-arg callables; you
   write a small binder for each MCP tool it needs. The binder owns all
   MCP-signature adaptation:

   The client keys are LOGICAL operations, not 1:1 MCP tool names — several
   same-named MCP tools do something different; the tool-signature footguns
   are catalogued in the `estimating-reference` skill's
   `references/api-constraints.md`. Verified mapping (BM MCP as of 2026-07):

   - `mcp__bidmanager__list_labor_rates(classification=, is_current=True)` → MCP
     `mcp__bidmanager__list_labor_rates`; post-filter to the classification and
     `is_current=True`; return a plain list (empty when nothing matches).
   - `mcp__bidmanager__create_labor_rate(classification=, burdened_hourly_rate=)` → MCP
     `mcp__bidmanager__create_labor_rate`, closing over `organization_id`.
   - `mcp__bidmanager__list_assemblies(assembly_type="CREW", name=)` → MCP
     `mcp__bidmanager__list_assemblies(context=, context_id=, assembly_type="CREW")` — it has
     NO name filter, so post-filter to EXACT `name ==` matches (substring
     resolution against e.g. `crew_ne_50` would reconcile the wrong
     assembly's members). Return records shaped `{"assembly_id": ...}`.
   - `mcp__bidmanager__create_assembly(assembly_type=, name=, description=)` → MCP
     `mcp__bidmanager__create_assembly`, closing over `context`/`context_id` (e.g.
     `context="template"`, `context_id=organization_id` for org-library
     crews). Return the new assembly's integer pk.
   - `mcp__bidmanager__list_components(assembly_id=)` → MCP `mcp__bidmanager__list_components`; map each
     component to `{"component_id": ..., "trade": ..., "count": quantity}`.
   - `mcp__bidmanager__create_component(assembly_id=, trade=, count=)` → MCP
     `mcp__bidmanager__create_component(assembly_id=, component_type="labor", name=trade,
     trade=trade, quantity=count)`; link `labor_rate_id` when the trade has
     a library rate.
   - `mcp__bidmanager__update_component(component_id=, count=)` → MCP
     `mcp__bidmanager__update_component(component_id=, quantity=count)`.
   - `mcp__bidmanager__delete_component(component_id=)` → MCP `mcp__bidmanager__delete_component`.
   - `mcp__bidmanager__create_estimate_item(item_number=, description=, estimated_quantity=,
     unit=, wbs=, cost_code=, crew_assembly_id=)` → a composition:
     `mcp__bidmanager__search_bid_item_templates` (post-filter by unit) else
     `mcp__bidmanager__create_bid_item_template`; then `mcp__bidmanager__create_bid_item(project_id=,
     template_id=, estimated_quantity=, item_number=, wbs=, cost_code=,
     crew_assembly_id=)`; then MCP `mcp__bidmanager__create_estimate_item(estimate_id=,
     project_bid_item_id=, unit_price=0)` (pricing comes later via the
     price-estimate flow). OMIT `crew_assembly_id` from `mcp__bidmanager__create_bid_item`
     when it is 0 (create rejects update's `0` clear-sentinel — see
     api-constraints). Return the ESTIMATE ITEM's integer pk —
     that is what gets written back into the spec.
   - `mcp__bidmanager__update_bid_item(estimate_item_id=, item_number=?, description=?,
     unit=?, wbs=?, cost_code=?, crew_assembly_id=?)` → resolve the
     estimate item's underlying `bid_item_id` (via `mcp__bidmanager__list_estimate_items` /
     `mcp__bidmanager__get_bid_item`), then MCP `mcp__bidmanager__update_bid_item(bid_item_id=, ...)` passing
     the kwargs straight through. `description=` / `unit=` set PER-ITEM
     OVERRIDES in BM (BidManager #764): the shared BidItemTemplate is
     untouched, and BM treats `""` as revert-to-template. `wbs=` /
     `cost_code=` are opaque strings; `""` clears. `crew_assembly_id=` is a
     resolved assembly pk from the executor; `0` clears the assignment
     (BidManager #766).
   - `mcp__bidmanager__update_estimate_item(estimate_item_id=, estimated_quantity=)` →
     quantity lives on the BID item in BM: resolve `bid_item_id` as above,
     then MCP `mcp__bidmanager__update_bid_item(bid_item_id=, estimated_quantity=)` — never
     the same-named MCP tool (pricing-only; see api-constraints).
   - `mcp__bidmanager__delete_estimate_item(estimate_item_id=)` → MCP
     `mcp__bidmanager__delete_estimate_item(item_id=)`. Removes only the per-estimate wrapper;
     the ProjectBidItem stays.

3. **Execute:**

   ```python
   from estimating_tools.estimate_spec.sync_executor import run_sync, render_exec_report

   report = run_sync(plan, edited, client)
   ```

4. **Persist the writeback:** write the mutated `edited` spec back to
   `edited_path` (new items now carry `estimate_item_id`). Do this even if
   some ops errored — successful creates must not lose their anchors.

5. **Report:** `print(render_exec_report(report))`. If any row shows
   `error`, tell the user that re-running this skill is safe: rates check
   for an existing current rate first, crew creates fall through to a
   member-reconcile when the assembly already exists, and item creates that
   succeeded now carry `estimate_item_id` so the next `plan_sync` won't
   re-emit them.

## Notes

- Fixed execution order: rates → crews → items.
- Best-effort per op: one failure never aborts the run; every op gets a
  report row.
- Formula quantities (`=...`) are not pushable; those ops error with
  "formula qty; resolve before sync". Resolve the formula to a number in
  the spec, or leave the qty cell alone, then re-run.
- Crew description changes are not pushed on update (deferred); the
  description is used only when creating a new crew assembly.
- Description/uom pushes set per-item overrides in BM — the shared template
  is never modified (use `mcp__bidmanager__update_bid_item_template` in BM for catalog-level
  fixes).
- Item crew assignment (`crew_id`) is resolved by exact Assembly name at
  push time. The crew must exist in BM — same-plan crew creates run first
  (fixed rates → crews → items order), so a crew added and referenced in
  one edit session syncs cleanly. An unresolvable or ambiguous crew name is
  an error row; re-running after fixing the crew is safe.
- No deletes for rates or crews, no rate updates, no pricing sync — see the
  design doc's deferred list
  (`docs/superpowers/specs/2026-07-10-bm-sync-executor-design.md`).
- Pace the executor: the BM MCP rate limiter counts reads too and locks out
  for ~7–10 minutes with no Retry-After (~10–15 rapid calls or a parallel
  burst triggers it; an observed 180 s wait was not enough, 420 s was).
  Bind the client so ops run serially — never in parallel — and on a
  lockout pause the full window before resuming; best-effort per-op
  reporting makes the re-run safe.
