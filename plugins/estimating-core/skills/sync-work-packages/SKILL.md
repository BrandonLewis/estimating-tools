---
name: sync-work-packages
description: Push a fieldbook spec's work packages and quote files to BidSheet.ai (packages, quotes, revisions, the carried choice, plug removal) and pull BidSheet.ai's choice back into the spec — export, plan, review, run the ops, record the results. Via the BidSheet.ai MCP. Writes only after the estimator confirms.
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

> **Verify the setup before relying on it:** run `~/.estimating/bin/est-python -c "import estimating_tools"`. That interpreter is the one the helpers below run on, so this answers the only question that matters — whether the code is importable where it will be used — and nothing is installed into the working repo's venv. If the import fails, follow the **Setup** block above and retry; if it still fails, proceed anyway by driving the BidSheet.ai MCP tools directly per the workflow — the `estimating_tools` helpers (plan/render/diff) are conveniences, not prerequisites.

> **Display contract:** Show `render` output to the user **verbatim in a fenced code block** — never reformat it, add/remove columns, or substitute your own table; `parse` depends on the exact shape. If the `open_artifact_editor` tool (artifact-editor server) is available, ALSO call it — `open_artifact_editor(markdown=<rendered, verbatim>, title="<title>", editable=<false for read-only plan renders>)` — and tell the user to edit in the inline panel and click **Save & send to chat**; their edits arrive as a chat message. In the terminal, the same tool instead opens the editor in the user's web browser and returns the saved block directly in the tool result — parse and push it when it returns (Save = the user's consent). If the wait expires, call `collect_artifact_edits` after the user says they've saved. If the tool is missing or errors, show the live page built by:
>
> ```python
> from estimating_tools.artifacts_html import to_editable_html
> page = to_editable_html(rendered, title="<title>")
> ```
>
> Prefer the host's native artifact mechanism (present `page` as a live HTML artifact); if the host only renders files, write it to `<slug>.artifact.html` (named after the artifact so successive renders don't overwrite each other). For editable artifacts, point the user at the page's **Copy edited artifact** button; for read-only plan renders, pass `editable=False` (the page has no button). Run `parse` only on text the user provides — the Save message, the pasted export, or their edited block — never on your own restatement of it.

> **Display-path availability:** the `open_artifact_editor` tool may be absent from the session's tool surface entirely (it lives on a separate artifact-editor server). When it is, the HTML render fallback above is the only rich display path; if the host cannot render that either, present the plan as a plain markdown table in-conversation and take the user's confirmation there — never skip the review.

# Sync Work Packages (push and pull)

Use this to keep the spec's `work_packages` and the quote files in `<quotes dir>/*.json`
in step with BidSheet.ai. **Push** creates packages, assigns items, captures each quote
file as a quote or a revision, carries the spec's choice (pinned) and offers to remove the
plug components the carried vendor replaces. **Pull** brings a choice made in BidSheet.ai
back into the quote files and the spec. The planners are deterministic (`~/.estimating/bin/est-estimate
packages push|pull`); this skill gathers the BidSheet.ai export, shows the plan, runs the
MCP calls and records the results.

`<quotes dir>` is the spec's `work_packages_quotes_dir`, else `quotes`. The sidecar is
`<quotes dir>/_bm/bm-sync.json`; the plans default to `<quotes dir>/_bm/push.plan.json` and
`pull.plan.json`. The sidecar is written only by `push --apply` and `pull --write`.

**Nothing runs against production without the estimator's go-ahead.** Every write step
below waits for an explicit yes to the plan just shown.

## Inputs
- The spec (`*.estimate.yaml`) with `work_packages`, and the quote files in the quotes dir.
- The BidSheet.ai `project_id` and `estimate_id` (the sidecar remembers them).
- The bid's `Estimate/bm-assembly-ids.json` (for the plug components).

## Export

Build one JSON file, `<quotes dir>/_bm/export.json`, from read-only MCP calls, in this order:

1. `list_work_packages(project_id)`. **Stop if the packages lack `carry_mode`**: BidSheet.ai
   is not yet on #1556 and the carried-quote model this skill pushes to does not exist
   there. Tell the estimator that and do nothing else.
2. For each package: `get_work_package(work_package_id)` (items with `item_number`,
   `work_package_item_id`, `project_bid_item_id`, `estimate_item_id`, `schedule_name`; plus
   `carry_mode`, `selected_quote`, `self_perform`, `new_quotes_since_carry`).
   `get_work_package` does not return `estimate_package_id`: take it from
   `list_estimate_packages(estimate_id)` (rows carry `id` and `work_package_id`) and set
   each package's `estimate_package_id` to the `id` whose `work_package_id` matches (absent
   when there is none). On a first run `estimate_id` comes from the bid's platforms file or
   `list_estimates(project_id)`.
3. `list_work_package_quotes(work_package_id)`; for each quote
   `list_work_package_quote_line_items(quote_id)` and `list_subcontractor_allocations(quote_id=…)`.
   Keep every revision the calls return; the planner drops a quote whose `is_current` is
   false (superseded) and keeps its allocations. Map the rows field by field, exactly these
   keys (the planner reads nothing else; a row that names its id `id` may keep it as `id`,
   the planner reads `id` when `quote_id`, `line_id` or `allocation_id` is absent):
   - quote → `{"quote_id": row.id, "vendor_name", "vendor_id", "revision", "status",
     "amount", "separate_acceptance_permitted", "acceptance_notes", "notes",
     "is_current", "line_items": […], "allocations": […]}`;
   - line item → `{"item_number": <the bid item number of the line's work-package item>,
     "line_id": row.id, "unit_price", "quantity", "amount", "is_included",
     "is_alternate", "exclusion_notes"}`;
   - allocation → `{"allocation_id": row.id, "quote_line_item_id", "allocation_type",
     "accept_alternate"}`.
4. `list_bid_items(project_id)` (also needed later to map item numbers to ids).
5. `list_organizations(search=<vendor name>)` for each vendor name in the quote files, to
   fill `organizations`.
6. `list_components(assembly_id=…)` on every GENERIC assembly: the `:lines` external ids in
   the bid's `bm-assembly-ids.json` (under `"assemblies"`), for each item that sits in a
   package. Map each returned row (keys `id, assembly_id, name, component_type, quantity,
   unit, unit_cost, trade, description, sort_order`) to `{"component_id": row.id,
   "assembly_id": <the assembly queried>, "name", "component_type", "quantity",
   "unit_cost", "description"}` and put the list under the package's `components`, keyed by
   item number. Also put every assembly id the item has now (all of them from
   `bm-assembly-ids.json`, or `list_assemblies(context="estimate",
   context_id=<estimate_item_id>)`) under the package's `assemblies`, keyed by item number:
   the planner uses it to tell a plug record left behind by a `push-assemblies` re-push
   (its assembly no longer exists) from a live one.

Shape (written as is; do not add keys):

```json
{"project_id": 1234, "estimate_id": 100,
 "organizations": [{"id": 4722, "name": "Acme Rebar"}],
 "packages": [{"<get_work_package detail, including items[], carry_mode, selected_quote, self_perform, new_quotes_since_carry>": "…",
               "quotes": [{"<quote detail>": "…", "line_items": [], "allocations": []}],
               "components": {"<item_number>": [{"component_id": 1, "assembly_id": 2, "name": "…"}]},
               "assemblies": {"<item_number>": [2, 3]}}]}
```

A package missing from BidSheet.ai is simply absent; the planner creates it.

## Push

1. Plan (writes only the plan file):
   `~/.estimating/bin/est-estimate packages push SPEC --bm EXPORT.json -o PLAN.json`
   Add `--force spec` to push the spec's side of a conflict, only on the estimator's say-so;
   `--strict` exits 1 when the plan has a conflict or refusal.
2. Show the rendered plan **verbatim** (display contract above). The command prints
   `render_plan(plan)` from `estimating_tools.estimate_spec.bm_sync.ops`; pass that text,
   not your own table, to the display step. Read out the Entries:
   conflicts and refusals are not pushed; reconcile lines compare BidSheet.ai's value with
   the workbook's carried subtotal; notices explain themselves.
3. **Wait for the estimator's confirmation.** List every remove_plug op (a
   `delete_component` call) separately, with its item, component and value, and ask item
   by item; the estimator may decline any of them. A declined op is simply not run and gets
   no result (the apply step reports it skipped).
4. Run the confirmed ops **in plan order**, each by its `tool` and `args`. Before a call,
   replace every `{"$ref": "<op id>", "path": "$.id"}` with the value at that path in that
   op's result (`$.items[?item_number=='61'].work_package_item_id` selects the element of
   `items` with that `item_number`). If the referenced op failed or was skipped, skip the
   op too and say so.
   - `create_work_package` (kind ensure_package): right after it, call
     `create_estimate_package(estimate_id, work_package_id=<new id>, name=<package name>)`
     and add `"estimate_package_id": <its id>` into the ensure_package op's result dict
     before saving it, so the sidecar entry and the recalc `$ref` resolve. Do not guess an id.
   - an assign_items op (tool `assign_items_to_package`) sends `item_numbers`: map each to its
     `project_bid_item_id` through the step 4 `list_bid_items` (match schedule and item
     number; the number can recur across schedules) and call
     `assign_items_to_package(work_package_id, bid_item_ids=[…])`. Stop on an item that
     does not resolve.
   - `create_quote_revision`: when its result has no `line_items`, call
     `list_work_package_quote_line_items(<the new revision's id>)` and attach the rows as
     `line_items` (each with `item_number` and `id`) to the result before saving it, so
     `$.line_items[?item_number=='N'].id` resolves for the line updates and the sidecar.
   - `assign_items_to_package`: when its result has no `items`, call
     `get_work_package(<work_package_id>)` and attach its `items` (each with `item_number`
     and `work_package_item_id`) to the result before saving it, so
     `$.items[?item_number=='N'].work_package_item_id` resolves.
   - `resolve_vendor` has no tool: it is a question. Show the candidate organizations and
     let the estimator pick (or decline); the answer is that op's result, `{"vendor_id": <id>}`.
   - `create_organization`, `create_work_package_quote`, `create_work_package_quote_line_item`,
     `create_quote_revision`, `update_work_package_quote_line_item`,
     `delete_work_package_quote_line_item`, `carry_work_package_quote`,
     `acknowledge_work_package_quotes`, `allocate_subcontractor`,
     `remove_subcontractor_allocation`, `recalculate_estimate_package_totals` (argument
     `package_id`): call with the
     op's arguments as given; do not add, rename or drop arguments.
   - MCP create and update tools return `{"error": …}` instead of raising. Record that as
     the op's result, then stop running ops that depend on it (`after`, `$ref`).
5. Save every result: `{"results": {"<op id>": <the tool's result, as returned>}}` to
   `RESULTS.json`. Include `carry_warning` / `carry_warnings` exactly as returned.
6. Record: `~/.estimating/bin/est-estimate packages push SPEC --apply RESULTS.json`
   (it reads the default plan; pass `--plan PLAN.json` if the plan was written elsewhere).
   Run it even when the plan has no ops but shows `adopted BidSheet.ai quote` notices
   (save `{"results": {}}`): the apply records the adopted quotes in the sidecar. It also
   records BidSheet.ai's choice as the baseline for every package the plan touched, and
   the export's `work_package_id` / `estimate_package_id` for every package it touched or
   the sidecar already records (a sidecar whose ids are null from an earlier apply heals
   on the next one; run the apply with `{"results": {}}` after a 0-op plan to do that).
   It also drops the plug records the plan flagged as stale (`stale plug record(s)`
   notices: their assembly was replaced by a `push-assemblies` re-push) and prints one
   `pruned stale plug record` line each.
   Report the `warning` lines it prints and the BidSheet.ai `carry_warnings`. A warning
   `manual subcontractor component present` means a plug component is still on that item
   (it was declined, or the vendor was carried before it was removed); say which item.
7. Report: ops run, skipped (declined or dependent), errors, and what the sidecar now holds.

## Pull

1. Dry run: `~/.estimating/bin/est-estimate packages pull SPEC --bm EXPORT.json`
   (writes only `pull.plan.json`). Rebuild the export first if it is not from this session.
   `--force bm` takes BidSheet.ai's side of a conflict, only on the estimator's say-so.
2. Show the plan verbatim and what it would change in the quote files and the spec.
3. On confirmation: the same command with `--write`. It saves the quote files (after a
   `.bak` copy), the spec and the sidecar together.
4. Rebuild the fieldbook workbook (`build-estimate-workbook`) so the comparison tab and the
   carried subtotals show the new choice. Pull never calls BidSheet.ai.

## The bid-day chain

Quote lands (`intake-quotes` / `capture-quote`) → `build` the workbook → **push** (the
comparison tab fills; BidSheet.ai carries its lowest quote automatically) → choose in Excel
or in BidSheet.ai → **pull** with `--write` → `build` → `excel_recalc` → `pricing_plan.py`
→ `bulk_update_estimate_items` → **push** again when the choice was made in Excel (the pin,
and the plug removal offered item by item). After the plug removal, `push-assemblies`
restores the plugs if a different vendor is chosen later.

## Notes
- Packages match by name, case-insensitive; ids are learned into the sidecar from the
  export, never typed.
- Re-running is safe: an unchanged quote file makes no ops; a changed one becomes a
  revision, history preserved.
- A package the spec carries as `CARRY` has no BidSheet.ai form; the plan says so.
- Plug removal is offered only when the vendor's carry is planned in this push or
  already in BidSheet.ai as the spec says, and only for the items that vendor's current
  quote includes. A conflict or a refused choice offers none.
- A notice `overrides BidSheet.ai's pin on …` means the push replaces a pin the estimator
  made in BidSheet.ai; read it out before the confirmation.
- `plugs_removed` in the sidecar records each removed plug as `assembly_id`,
  `component_id` and `name`. After a `push-assemblies` re-push the recorded assemblies are
  gone: when the export carries `assemblies`, the push plan flags those records as stale
  (a notice per item, not counted as removed) and `--apply` prunes them; that skill's
  `re-remove` lines are the record of what was removed again.
- Other-project quotes are not pushed; a plug taken from one is an explicit ask.
