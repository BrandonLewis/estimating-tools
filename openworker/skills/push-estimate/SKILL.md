---
name: push-estimate
description: Push an imported CanonicalEstimate into BidSheet.ai as a Project with Bid Schedules and Bid Items, via the BidSheet.ai MCP — creating a new project or adding to an existing one without duplicating.
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

# Push an Estimate into BidSheet.ai

Use this after importing a legacy estimate (see the import-estimate skill) to load
the open `CanonicalEstimate` into BidSheet.ai as a Project + Bid Schedules + Bid
Items. Requires the BidSheet.ai MCP to be connected.

This pushes the bid-schedule STRUCTURE (item numbers, codes, descriptions,
quantities, units, schedules). It does NOT push prices — `unit_price` is an
estimate-side concern, handled separately.

## Inputs
- A `CanonicalEstimate` (a `*.canonical.json` from `est-import`, or in hand).
- The target `organization_id` (whose template library to use) and a
  `project_id` (a short job id string). Ask the user if not known; you can
  suggest a slug of the project name, but confirm the real job id.

## Workflow
1. Build the plan deterministically:
   ```bash
   python -c "import json,sys; from estimating_tools.importers.model import CanonicalEstimate; from estimating_tools.importers.push import plan_push; print(plan_push(CanonicalEstimate.from_json(open(sys.argv[1]).read())))" <file.canonical.json>
   ```
   (or call `plan_push` in-process). The plan has `project`, `schedules`,
   `templates`, and `items`.
2. **Review the plan (read-only artifact):** render the plan inline for the user to
   review:

   ```python
   from estimating_tools.importers.push import render_push_plan

   print(render_push_plan(plan))
   ```

   The rendered block shows the sections that will be written to BidSheet.ai (Project /
   Schedules / Templates / Items). Ask the user to confirm before
   proceeding to Find-or-create the project. If they want to change anything, back up to
   step 1, adjust the input, and rebuild the plan; the render is not
   editable.
3. **Find-or-create the project:** `mcp__bidmanager__search_projects(plan.project["title"])`. If a
   matching project exists, reuse its `project_id`; otherwise `mcp__bidmanager__create_project`
   with the confirmed `project_id`, `title=plan.project["title"]`, and `bid_date`.
4. **Find-or-create each schedule:** `mcp__bidmanager__list_bid_schedules(project_id)`. For each
   entry in `plan.schedules`, reuse the schedule whose `name` matches, else
   `mcp__bidmanager__create_bid_schedule(project_id, name, display_order=...)`. Record each
   `schedule_id` by name.
5. **Find-or-create each template:** for each entry in `plan.templates`,
   `mcp__bidmanager__search_bid_item_templates(organization_id, item_code, description)` — it matches on
   `item_code`/`description` only (there is no `unit` filter), so **post-filter the results
   by `unit`** to find the exact `(item_code, description, unit)` match. Reuse that match,
   else `mcp__bidmanager__create_bid_item_template(organization_id, item_code, description, unit)`. Record
   each `template_id` by its `(item_code, description, unit)`.
6. **Create only new items:** `mcp__bidmanager__list_bid_items(project_id)` to get the currently
   existing items. Build an `existing_by_schedule` mapping of
   `schedule_name -> set of item_numbers` from those results (group by the item's
   schedule name). Then call `diff_new_items(plan.items, existing_by_schedule)` to
   obtain only the truly new items — items whose `item_number` does not already
   exist **in the same schedule** (the same `item_number` in a different schedule
   is independent and will be kept). Call
   `mcp__bidmanager__bulk_create_bid_items(project_id, items=[...])` where each item dict has
   `template_id` (resolved in step 5), `estimated_quantity`, `item_number`,
   `item_code`, and `schedule_id` (resolved in step 4).
   `mcp__bidmanager__bulk_create_bid_items` requires `estimated_quantity`, so an item whose
   `estimated_quantity` is null (the source had no quantity) should be surfaced to
   the user for a value rather than pushed with a null.
7. Report what was created vs reused (project, schedules, templates, item counts).

## Notes
- Re-running is safe: existing project/schedules/templates are reused and items
  with an existing `item_number` are skipped — no duplicates.
- The field mapping and the new-item diff are deterministic
  (`estimating_tools.importers.push`); the judgment is resolving the org/project
  and confirming matches.
- To price the pushed bid items (create an Estimate from the imported
  `unit_price`s), use the `price-estimate` skill next.
