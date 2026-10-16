---
name: estimate-template
description: Manage a customer's org-level estimate templates in BidSheet.ai — author a reusable whole-bid-structure template from an existing estimate, and start a new bid by instantiating a template into a new project's draft estimate. Via the BidSheet.ai MCP. Writes.
---

# Org Estimate Templates

Use this to help a customer **author** their standard bid structure as a reusable
**estimate template** and to **start a new bid** from one — instead of beginning from a
blank estimate. The template lives in BidSheet.ai (org-scoped, server-owned); it captures
the bid SCHEDULES and standard LINE ITEMS (item numbers, codes, descriptions, units, cost
codes) — **structure only, no quantities or prices**. Requires the BidSheet.ai MCP. WRITES
to BidSheet.ai.

Pick the workflow by intent:
- **Author** a template (one-time, from a representative estimate) → Workflow A.
- **Start a new bid** from a template (recurring) → Workflow B.

## Inputs
- The target organization (by name or id).
- Workflow A: the source `estimate_id` to capture, a template `name`, and an optional
  `description` (defaults to an empty string — do not invent one).
- Workflow B: which template, and the target project (a short `project_id` job id + title;
  a `bid_date` if known).

## Workflow A — Author a template (from a representative estimate)
1. **Resolve the org + source estimate:** `mcp__bidmanager__list_organizations` → the target
   `organization_id`. Identify the source `estimate_id` (an estimate that already has the
   standard schedules + items). If the org has no representative estimate yet, build one
   first via the `import-estimate` → `push-estimate` skills (then `price-estimate` if
   desired), and return here.
2. **Save it as a template:** `mcp__bidmanager__save_estimate_as_template(estimate_id, name, description,
   organization_id)` — pass `description` only if the user gave one, otherwise an empty
   string (do not invent a description). This requires edit access on the estimate's
   project. Report the created template from the returned detail (id, name, and the
   schedule/item counts). If the tool returns `{"error": ...}`, surface it — do not retry
   blindly.

## Workflow B — Start a new bid from a template
1. **Resolve the org + pick a template:** `mcp__bidmanager__list_estimate_templates(organization_id)`.
   Present the templates; on request, `mcp__bidmanager__get_estimate_template(template_id)` to preview its
   schedules and items. If the org has no templates, say so and offer Workflow A to author
   one — do not fabricate a template.
2. **Find-or-create the target project** (the `push-estimate` pattern):
   `mcp__bidmanager__search_projects(title)`. If a matching project exists, reuse its `project_id`;
   otherwise `mcp__bidmanager__create_project(project_id, title, bid_date)` with a confirmed short
   `project_id` (a job id — suggest a slug of the title, but confirm the real id).
3. **Instantiate:** `mcp__bidmanager__instantiate_estimate_from_template(template_id, project_id, name)` → a
   new DRAFT estimate carrying the template's schedules + items (structure only; `name`
   defaults to the template name). Report the created estimate.
4. **Hand off (do NOT price here):** the new estimate has structure but no quantities or
   prices. Tell the user to add quantities with the `quantity-takeoff` skill and prices
   with the `price-estimate` skill.

## Notes
- Templates are **org-scoped and server-owned** — there is no plugin-side template format;
  this skill only drives the BidSheet.ai MCP tools.
- Instantiation is **structure-only**: the estimator fills quantities (takeoff) then prices
  (`price-estimate`). This skill never sets quantities or prices.
- The target project is **find-or-created, never duplicated** (`mcp__bidmanager__search_projects` →
  `mcp__bidmanager__create_project`); re-instantiating onto the same project adds another draft estimate
  rather than colliding with the first.
- `mcp__bidmanager__delete_estimate_template(template_id)` exists for cleanup, but this skill does not delete
  as part of either workflow — only on an explicit user request.
- The judgment is eliciting the org / source estimate / template and confirming the project
  match; the BidSheet.ai tools do the structure-building server-side.
- BidSheet.ai write constraints and tool-signature footguns (e.g. `mcp__bidmanager__create_bid_item`
  rejects the `crew_assembly_id=0` clear-sentinel that `mcp__bidmanager__update_bid_item` accepts):
  see `../estimating-reference/references/api-constraints.md`.
