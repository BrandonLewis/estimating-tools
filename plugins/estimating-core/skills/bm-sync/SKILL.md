---
name: bm-sync
description: Push local estimate-spec edits back to BidSheet.ai — diff a pre-edit snapshot against the edited spec with plan_sync, review the sync plan, then execute rate/crew/item creates, updates, and deletes via the BidSheet.ai MCP with estimate_item_id writeback.
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
   `references/api-constraints.md`. Verified mapping (BM MCP as of 2026-10-16):

   **General rule — every `create_*` binding:** the MCP create tools return
   `{"error": ...}` on failure; they do not raise. The binder must check the
   result and raise (e.g. `raise RuntimeError(result["error"])`) when it
   contains `"error"`, or the executor's try/except records a failed push as
   `"ok"` and the user is told it worked when nothing happened.

   - `list_labor_rates(classification=, is_current=True)` → MCP
     `list_labor_rates(organization_id=, classification=)` — the MCP tool
     has NO `is_current` param (current rows are the default; drop it) and
     caps at 50 rows across ALL of the caller's organizations when
     `organization_id` is omitted, so always pass it. Post-filter the
     result to an EXACT, case-sensitive `classification ==` match; return a
     plain list (empty when nothing matches).
   - `create_labor_rate(classification=, base_hourly_rate=, burden_percentage=,
     fringe_hourly=, rate_basis=)` → MCP `create_labor_rate` with the same
     arguments plus `organization_id`. `burden_percentage` is already a
     percent (32.0); BidSheet.ai computes the burdened rate itself. There is
     no `burdened_hourly_rate` parameter — never pass one.
   - `list_equipment_rates(equipment_type=, is_current=True)` → MCP
     `list_equipment_rates(organization_id=, equipment_type=)` — same two
     gotchas as `list_labor_rates`: no `is_current` param (drop it) and pass
     `organization_id` or risk a 50-row, all-orgs result. Post-filter to an
     EXACT, case-sensitive `equipment_type ==` match; return a plain list.
   - `create_equipment_rate(equipment_type=, hourly_rate=, includes_operator=)`
     → MCP `create_equipment_rate` with the same arguments plus
     `organization_id`.
   - `list_assemblies(assembly_type="CREW", name=)` → MCP
     `list_assemblies(context=, context_id=, assembly_type="CREW")` — it has
     NO name filter, so post-filter to EXACT `name ==` matches (substring
     resolution against e.g. `crew_ne_50` would reconcile the wrong
     assembly's members). Return records shaped `{"assembly_id": ...}`.
   - `create_assembly(assembly_type=, name=, description=)` → MCP
     `create_assembly`, closing over `context`/`context_id` (e.g.
     `context="template"`, `context_id=organization_id` for org-library
     crews). Return the new assembly's integer pk.
   - `list_components(assembly_id=)` → MCP `list_components`; map each
     component to `{"component_id": ..., "trade": ..., "count": quantity}`.
   - `create_component(assembly_id=, trade=, count=, kind=)` → MCP
     `create_component(assembly_id=, component_type=kind, name=trade,
     trade=trade, quantity=count)`, plus `labor_rate_id` (kind `labor`) or
     `equipment_rate_id` (kind `equipment`) — look it up via ONLY the list
     tool matching `kind` (`list_labor_rates` for labor,
     `list_equipment_rates` for equipment) and pass the id when a current
     rate exists for the trade. Leave `unit_cost` unset: the MCP tool
     sources it from the linked rate.
   - `update_component(component_id=, count=)` → MCP
     `update_component(component_id=, quantity=count)`.
   - `delete_component(component_id=)` → MCP `delete_component`.
   - `create_estimate_item(item_number=, description=, estimated_quantity=,
     unit=, wbs=, cost_code=, crew_assembly_id=)` → a composition:
     `search_bid_item_templates` (post-filter by unit) else
     `create_bid_item_template`; then `create_bid_item(project_id=,
     template_id=, estimated_quantity=, item_number=, wbs=, cost_code=,
     crew_assembly_id=)`; then MCP `create_estimate_item(estimate_id=,
     project_bid_item_id=, unit_price=0)` (pricing comes later via the
     price-estimate flow). OMIT `crew_assembly_id` from `create_bid_item`
     when it is 0 (create rejects update's `0` clear-sentinel — see
     api-constraints). Return the ESTIMATE ITEM's integer pk —
     that is what gets written back into the spec.
   - `update_bid_item(estimate_item_id=, item_number=?, description=?,
     unit=?, wbs=?, cost_code=?, crew_assembly_id=?)` → resolve the
     estimate item's underlying `bid_item_id` (via `list_estimate_items` /
     `get_bid_item`), then MCP `update_bid_item(bid_item_id=, ...)` passing
     the kwargs straight through. `description=` / `unit=` set PER-ITEM
     OVERRIDES in BM (BidManager #764): the shared BidItemTemplate is
     untouched, and BM treats `""` as revert-to-template. `wbs=` /
     `cost_code=` are opaque strings; `""` clears. `crew_assembly_id=` is a
     resolved assembly pk from the executor; `0` clears the assignment
     (BidManager #766).
   - `update_estimate_item(estimate_item_id=, estimated_quantity=)` →
     quantity lives on the BID item in BM: resolve `bid_item_id` as above,
     then MCP `update_bid_item(bid_item_id=, estimated_quantity=)` — never
     the same-named MCP tool (pricing-only; see api-constraints).
   - `delete_estimate_item(estimate_item_id=)` → MCP
     `delete_estimate_item(item_id=)`. Removes only the per-estimate wrapper;
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
  is never modified (use `update_bid_item_template` in BM for catalog-level
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
