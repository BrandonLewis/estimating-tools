---
name: import-cost-codes
description: Import a customer's existing cost-code system (a hierarchy of activity / job-cost codes plus their cost types) from an Excel spreadsheet into BidSheet.ai — read its columns, propose and confirm a mapping to the canonical fields, build the open canonical cost-code system (validated + topologically ordered), then push it in dependency order (system, then cost types, then activity codes with cost_type/parent resolution), skipping codes that already exist. Via the BidSheet.ai cost-code MCP tools.
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

# Import an Org's Cost-Code System from Excel

Use this to onboard a customer's cost-code system: the cost types (Labor/Material/Equipment/…)
and the hierarchy of activity (job-cost) codes. You read their columns, figure out the
mapping, import + validate the system locally, resolve the target organization, then push
the system, cost types, and activity codes in dependency order. The import is local; the
push drives the cost-code MCP tools.

## Inputs
- Path to the org's cost-code spreadsheet (`.xlsx`).
- A display name for the system (e.g. "Standard Codes 2026"), optional version/description.
- The target organization (the system is org-scoped).

## Workflow
1. **Inspect the columns:** read the header row — e.g. with
   `estimating_tools.costcodes.read_costcode_rows(path)` (the keys of the first row are the
   org's column names). List them for the user.
2. **Propose and confirm the column mapping (editable artifact):** the canonical fields are
   `code`, `description`, `category`, `cost_type`, `cost_type_name`, `parent_code`,
   `default_unit`, `notes`, `sort_order`, `is_active`. Required: `code`. Build the artifact
   and render it inline for the user to edit:

   ```python
   from estimating_tools.costcodes.excel import _CANONICAL_FIELDS, _REQUIRED, read_costcode_rows
   from estimating_tools.importers.mapping_artifact import propose_mapping, render

   sample = read_costcode_rows(path)
   if not sample:
       raise ValueError("spreadsheet has no data rows")
   pm = propose_mapping(_CANONICAL_FIELDS, _REQUIRED, list(sample[0].keys()), sample)
   print(render(pm))
   ```

   Show the rendered table to the user. They edit column names (or set a column to `-`
   to skip a field) and send it back — the Save message, or a pasted block. Parse it:

   ```python
   from estimating_tools.importers.mapping_artifact import parse, to_mapping_dict

   pm = parse(user_edited_text)
   mapping = to_mapping_dict(pm, required=set(_REQUIRED))
   ```

   The `mapping` is the `{canonical_field: spreadsheet_column}` dict the importer expects.
3. **Import:** `estimating_tools.costcodes.build_cost_code_system_from_excel(path,
   system_name=…, version=…, mapping=…)` → a `CanonicalCostCodeSystem` (`cost_types`,
   `activity_codes` already topologically ordered, parents first). If it raises (a missing
   `code`, a `parent_code` not in the sheet, a duplicate code, a self-parent, or a cycle),
   surface the message and fix the mapping/data with the user. (For a headless run, the
   `costcode-import --system-name …` CLI does the same with a `--mapping` JSON file.)
4. **Resolve the target org:** `mcp__bidmanager__list_organizations(search=…)` → the organization to own the
   system; record `organization_id`.
5. **Push (ordered, idempotent):**
   - `mcp__bidmanager__create_cost_code_system(organization_id, name=…, description=…, version=…)` → record
     `system_id`. (If a system of that name already exists for the org via
     `mcp__bidmanager__list_cost_code_systems()`, you may reuse it.)
   - **Cost types:** for each `cost_type`, `mcp__bidmanager__create_cost_type(system_id, code, name,
     sort_order)` → build a `cost_type_code → cost_type_id` map. Use
     `mcp__bidmanager__list_cost_types(system_id)` to reuse any that already exist.
   - **Activity codes — in the canonical (topological) order, which guarantees every parent
     is created before its children:** for each, resolve `cost_type_id` from the map (None
     if `cost_type_code` is blank) and `parent_id` from the codes already created this run
     (track `code → activity_code_id`; None if `parent_code` is blank). Call
     `mcp__bidmanager__find_activity_code_by_code(system_id, code)` first — if it exists, record its id and
     **skip** (report "no change"); else `mcp__bidmanager__create_activity_code(system_id, code, description,
     category=…, cost_type_id=…, parent_id=…, default_unit=…, notes=…, sort_order=…,
     is_active=…)` and record the new id.

## Notes
- The activity codes are pushed **in dependency order** (the builder topologically sorts
  them), so a parent always exists before BidSheet.ai validates a child's `parent_id`.
- Cost types are **derived** from the distinct `cost_type` codes the rows reference; their
  display names come from the `cost_type_name` column (or default to the code) — confirm
  them with the user at step 3.
- `is_active` defaults to true; a value like `no`/`false` marks a code inactive.
  `sort_order` is an integer (blank → 0).
- Re-running is safe: existing codes are detected via `mcp__bidmanager__find_activity_code_by_code` and
  skipped; only missing codes are created.
- The field mapping, tree validation, and ordering are deterministic
  (`estimating_tools.costcodes`); the judgment is proposing the column mapping, confirming
  the system name + cost-type names, and confirming the target org.
