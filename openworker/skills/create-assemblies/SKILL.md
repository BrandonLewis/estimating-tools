---
name: create-assemblies
description: Build a new customer's org-level assembly templates with them and push them into BidSheet.ai as v2 template-context assemblies — find-or-create, estimate-safe, resolve cost codes. Via the BidSheet.ai MCP. Writes.
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

# Create Org Assembly Templates

Use this to help a new customer stand up their **org-level assembly templates** in
BidSheet.ai — the reusable assemblies (their methods that explode into
labor/equipment/material) that future estimates draw from. It WRITES to BidSheet.ai
(the org's library tier). Requires the BidSheet.ai MCP.

**Estimate-safe:** template assemblies are a separate library tier from estimate
assemblies; an estimate gets an independent snapshot clone of a template, so creating
or editing a template here does NOT change any existing estimate.

## Inputs
- The target organization (by name or id) and the org's common assemblies (elicited
  from the user, or in hand).

## Workflow
1. **Build the library (create):** with the user, construct a
   `CanonicalAssemblyLibrary` — each assembly's `name`, `assembly_type`, optional
   `cost_code`, `description`, and `components` (each `component_type` one of
   labor/material/equipment/subcontractor/other, with `quantity`, `unit`, `unit_cost`,
   `trade`; on a labor/equipment/material component a `rate_ref` names a rate-library rate
   resolved to the org's rate id at push, while on a subcontractor/other component it is
   non-routable and only flagged, using inline cost).
2. **Review & edit the library (editable artifact):** render the elicited library inline
   for the user to review and edit:

   ```python
   from estimating_tools.assemblies.artifact import render

   print(render(library))
   ```

   The rendered block is one `## <name> [<type>] (cost_code: <code>)` heading per assembly
   with an optional `> description` blockquote and a components table (columns:
   `component_type`, `component`, `quantity`, `unit`, `unit_cost`, `rate_ref`, `trade`,
   `description`). Users can rename an assembly, change its `assembly_type` or
   `cost_code` (`-` for none), add or remove component rows, tweak values, or add /
   remove / reorder entire assembly sections. `-` in any optional cell means "unset".

   The user edits and sends it back — the Save message, or a pasted block. Parse it into
   the canonical library:

   ```python
   from estimating_tools.assemblies.artifact import library_diagnostics, parse

   library = parse(user_edited_text)
   for warning in library_diagnostics(library):
       # surface each warning (empty assemblies, etc.) to the user before pushing
       print(warning)
   ```

   `parse` raises `ValueError` with a section+row locator on malformed input (see the
   artifact's docstring). Surface the message and ask the user to correct — do not
   silently drop.
3. **Resolve the org + cost-code system:** `mcp__bidmanager__list_organizations` → the target
   `org_id`; `mcp__bidmanager__list_cost_code_systems` → the org's `system_id` (for cost-code
   resolution). If the org has no cost-code system, note it and proceed (assemblies
   are created without cost codes).
4. **Plan it:** `estimating_tools.assemblies.plan_assembly_push(library, org_id)` →
   an `AssemblyPushPlan` (template-context assembly dicts with `mcp__bidmanager__create_component`
   payloads; `cost_code` strings to resolve; `rate_refs` flagged).
5. **Review the plan (read-only artifact):** render the plan inline for the user to
   review:

   ```python
   from estimating_tools.assemblies.plan import render_assembly_push_plan

   print(render_assembly_push_plan(plan))
   ```

   The rendered block shows every section that will be written to BidSheet.ai, plus a
   `## Flagged` list if any refs need attention. Ask the user to confirm before
   proceeding to Per assembly — find-or-create by name. If they want to change anything, back up to
   step 4, adjust the input, and rebuild the plan; the render is not
   editable.
6. **Per assembly — find-or-create by name in the template context:**
   `mcp__bidmanager__list_assemblies` filtered to `context='template'`, `context_id=org_id`. Reuse the
   one whose `name` matches; else resolve its `cost_code` with
   `mcp__bidmanager__find_activity_code_by_code(system_id, cost_code)` (if absent or unfound, omit it
   and note the unresolved code) and `mcp__bidmanager__create_assembly(name, assembly_type,
   context='template', context_id=org_id, description, activity_code_id=<resolved or
   omitted>)`. Record `assembly_id`.
7. **Components:** `mcp__bidmanager__get_assembly(assembly_id)` for the existing components; for each
   planned component NOT already present (match on `name`+`component_type`), resolve its
   `rate_resolution` (when not `None`) against the org's rate library by `kind`:
   - `labor` → `mcp__bidmanager__list_labor_rates(org_id)`, match `key` to a rate's `classification` →
     `labor_rate_id`.
   - `equipment` → `mcp__bidmanager__list_equipment_rates(org_id)`, match `key` to `equipment_type` →
     `equipment_rate_id`.
   - `material` → `mcp__bidmanager__list_material_costs(org_id)`, match `key` to `material_name` →
     `material_cost_id`.
   Then `mcp__bidmanager__create_component(assembly_id, component_type, name, quantity, unit_cost, unit,
   trade, description, <labor_rate_id|equipment_rate_id|material_cost_id>=<resolved id>)` —
   pass ONLY the id matching the kind (the others stay unset); keep passing `unit_cost`.
   If the `rate_resolution` key has no matching rate in the org's library, create the
   component with inline `unit_cost` only and add the `key` to the flagged items. The
   per-assembly `rate_refs` (subcontractor/other refs that can't reference a rate library)
   are flagged as-is and use inline cost.
8. **Report:** assemblies created / reused; components created / skipped; and the
   flagged items — cost codes that couldn't be resolved, `rate_resolution` keys with no
   matching rate in the org's rate library, and non-routable `rate_ref`s (subcontractor/
   other) that used inline cost.

## Notes
- Find-or-create is keyed on the assembly `name` WITHIN the org template context
  (`context='template'`, `context_id=org_id`) — it never reaches into project or
  estimate assemblies, so existing estimates are untouched.
- Re-running is safe: existing template assemblies are reused and existing components
  are skipped — no duplicates.
- Cost codes are resolved, not created; an unresolved code means the assembly is created
  without it and flagged. A component's `rate_ref` is resolved to the org's labor /
  equipment / material rate id (routed by `component_type`) and passed to
  `mcp__bidmanager__create_component` (BidManager #593); inline `unit_cost` is also passed. A `rate_ref`
  with no matching rate — or one on a subcontractor/other component — falls back to inline
  cost and is flagged.
- The field mapping is deterministic (`estimating_tools.assemblies`); the judgment is
  eliciting the org's assemblies and confirming the org/cost-code matches.
