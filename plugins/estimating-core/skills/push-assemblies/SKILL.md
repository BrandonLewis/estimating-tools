---
name: push-assemblies
description: Generate the task-breakdown assemblies for a bid's estimate items from the spec (est-estimate assemblies), prove the generator reproduces the existing push, then replace the assemblies on BidSheet.ai item by item. Via the BidSheet.ai MCP. Writes only after the estimator confirms.
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

> **Verify the setup before relying on it:** run `~/.estimating/bin/est-python -c "import estimating_tools"`. That interpreter is the one the helpers below run on, so this answers the only question that matters — whether the code is importable where it will be used — and nothing is installed into the working repo's venv. If the import fails, follow the **Setup** block above and retry; if it still fails, proceed anyway by driving the BidSheet.ai MCP tools directly per the workflow — the `estimating_tools` helpers (plan/render/diff) are conveniences, not prerequisites.

# Push Assemblies

Use this to (re)build the CREW and GENERIC task-breakdown assemblies on a bid's estimate
items from the spec's labor blocks and package lines, and push them to BidSheet.ai. The
generator is `~/.estimating/bin/est-estimate assemblies` (pure: spec in, JSON out); this skill finds or
creates the rates, proves the generator against what is already pushed, and runs the
BidSheet.ai calls.

**Nothing runs against production without the estimator's go-ahead.** The delete and
create calls below run only after the compare passed and the estimator confirmed the
report.

## Inputs
- The spec and the bid tag (for example `B1234`).
- `Estimate/bm-assembly-ids.json`: `{"estimate_id", "pushed", "assemblies": {external_id:
  assembly_id}, ...}`. The CLI reads ids only under `"assemblies"`.
  `Estimate/bm-activity-code-ids.json` (ids under `activity_code_ids`) when present.
- The estimate items' ids (`estimate_item_id` in the spec) and the BidSheet.ai
  `organization_id` for the rates.

## Workflow
1. **Rates, find or create, by trade.** For each `rate_table` row: labor trades
   `list_labor_rates(organization_id=, classification=<trade>)`, equipment trades
   `list_equipment_rates(organization_id=, equipment_type=<trade>)`. Post-filter to an exact,
   case-sensitive match (the tools have no `is_current` parameter and cap at 50 rows across
   organizations when `organization_id` is omitted). This step only looks: list each
   missing trade with the spec's numbers, and create nothing yet. A missing rate is created
   in step 4, after the comparison passes and the estimator approves it; never invent a
   rate, and ask the estimator when the spec row is zero or incomplete.
2. **Generate into a new directory**, leaving the earlier push's payloads
   (`Estimate/bm-assemblies`) untouched:
   `~/.estimating/bin/est-estimate assemblies SPEC -o Estimate/bm-assemblies.new --bid <bid> --existing Estimate/bm-assembly-ids.json`
   It writes `<item_no>.json` (a list of `bulk_create_assemblies` payloads per item) and
   `assemblies-report.md`. Show the report verbatim: the package lines per package,
   self-perform tasks, skipped tasks, and the re-push plan with its `delete_assembly`,
   `bulk_create_assemblies` and `re-remove` lines.
3. **Compare before any delete (mandatory).** Compare the new output with the earlier push:
   `~/.estimating/bin/est-estimate assemblies SPEC -o Estimate/bm-assemblies.new --bid <bid> --existing Estimate/bm-assembly-ids.json --compare Estimate/bm-assemblies`
   It prints every difference and exits 1 on any. **If it does not exit 0, stop**: show the
   differences, delete nothing, and ask the estimator. A difference is a reason to look at
   the spec or the generator, not to push anyway.
4. **Confirm.** Wait for an explicit yes naming the items. Say which items will have their
   assemblies deleted and recreated, list the missing rates from step 1 with the spec's
   numbers, and list the `re-remove` plug removals separately (each is a `delete_component`
   call the estimator may decline). Only then create the approved missing rates with
   `create_labor_rate` / `create_equipment_rate` using the spec's numbers. See `bm-sync`
   and the api-constraints reference for the argument footguns.
5. **Per item**, in the report's order:
   a. `delete_assembly(assembly_id)` for each id the report lists for the item.
   b. `bulk_create_assemblies(context="estimate", context_id=<estimate_item_id>,
      assemblies=<the item's JSON list, unchanged>)`. Record the new ids from the result (read them from what the tool returns; do not guess a shape)
      against each payload's `external_id`.
   c. When `bm-activity-code-ids.json` exists:
      `update_assembly(assembly_id, activity_code_id=<id>)`, where the id is the task's
      labor-block `cost_code` looked up under `activity_code_ids` in that file.
      Do not guess a code; skip the call and say so when the file has none.
   d. The confirmed plug removals for the item: find the component by name with
      `list_components(assembly_id)` on the new GENERIC assembly, then
      `delete_component(component_id)`. Record `assembly_id:component_id` and the name for
      each in the report. This skill does not write the sidecar: its `plugs_removed` keeps
      the old assembly and component ids, which no longer exist after the re-push; the next
      `sync-work-packages` push flags them stale and its `--apply` prunes them.
   MCP tools return `{"error": …}` instead of raising: stop that item at the first error,
   report it, and carry on only with the estimator's say-so. Never leave an item half done
   without saying so; deleted-but-not-recreated is the state to name loudly.
6. **Write `Estimate/bm-assembly-ids.json`**: the flat `{external_id: id}` map
   **under `"assemblies"`** (never at the top level), recording what is actually on the
   estimate, item by item, even for an item that failed part-way: an old id stays only if
   its `delete_assembly` did not succeed, and every id a `bulk_create_assemblies` returned
   goes in, whether or not the item's later steps (activity codes, plug removals)
   succeeded. Keep `estimate_id` and update `pushed`. Name each failed item and the step it
   stopped at in the report, so the next re-push deletes only ids that still exist. Then, only when every item succeeded, keep the old payloads as
   `Estimate/bm-assemblies.bak-<stamp>` and move `Estimate/bm-assemblies.new` over
   `Estimate/bm-assemblies`. If any item failed, leave `bm-assemblies` as it is.
7. **Report:** per item deleted / created / activity-coded / plugs removed, and anything
   skipped or failed. The sidecar's `plugs_removed` entries for the deleted assemblies are
   stale after a re-push (the ids are gone); the re-push plan's `re-remove` lines are the
   record of what was removed again, and the next `sync-work-packages` push prunes the
   stale entries once its export carries the item's new `assemblies`.

## Notes
- `external_id` carries the bid tag, so another bid's assemblies are never touched.
- Re-pushing replaces the assemblies, which restores any plug components a vendor
  carry had removed; step 5d removes them again for the vendors still carried. A sidecar
  record that carries the component name makes its `re-remove` line exact (the `NN `
  position prefix may differ from the regenerated line's; a unique match without it
  counts, two or more get a `confirm which` note); a nameless one (written before the
  name was recorded) lists every package line with a `confirm which` note.
- Run `sync-work-packages` after, so the export's `components` reflect the new ids.
