---
name: import-rates
description: Import a customer's existing rate library (labor classifications, equipment rates, material costs) from an Excel spreadsheet into BidSheet.ai — read its columns, propose and confirm a mapping to the canonical fields, build the open canonical rate library, then idempotently push the rates (skip unchanged) into a resolved organization's rate library. Via the BidSheet.ai rate MCP tools.
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

# Import an Org's Rate Library from Excel

Use this to onboard a customer's labor/equipment/material rates. You read their columns,
figure out the mapping to the canonical fields, import the rate library, resolve the
target organization, and push the rates — creating only new or changed rates. The import
is local; the push drives the rate MCP tools.

## Inputs
- Path to the org's rate spreadsheet (`.xlsx`).
- The target organization (the rates are org-scoped).

## Workflow
1. **Inspect the columns:** read the header row — e.g. with
   `estimating_tools.rates.read_rate_rows(path)` (the keys of the first row are the org's
   column names). List them for the user.
2. **Propose and confirm the column mapping (editable artifact):** the canonical fields are
   `rate_type` (labor/equipment/material), `name` (classification / equipment_type /
   material_name), `rate` (base hourly wage / equipment hourly rate / material unit cost),
   `unit`, `region`, `description`, `burden_percentage`, `trade`, `is_union`, `union_local`,
   `source`, `includes_operator`, `category`, `supplier`. Required: `rate_type`, `name`,
   `rate`. Build the artifact and render it inline for the user to edit:

   ```python
   from estimating_tools.rates.excel import _CANONICAL_FIELDS, _REQUIRED, read_rate_rows
   from estimating_tools.importers.mapping_artifact import propose_mapping, render

   sample = read_rate_rows(path)
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
3. **Import:** `estimating_tools.rates.build_rate_library_from_excel(path, mapping)` →
   a `CanonicalRateLibrary` (`labor_rates`, `equipment_rates`, `material_costs`). If it
   raises (an unknown `rate_type`, a non-numeric `rate`, a missing `name`), surface the
   message and fix the mapping/data with the user. (For a headless run, the `rate-import`
   CLI does the same with a `--mapping` JSON file.)
4. **Resolve the target org:** `mcp__bidmanager__list_organizations(search=…)` → the organization to load
   the rates into; record `organization_id`.
5. **Push (idempotent — skip unchanged):** read the org's current rates with
   `mcp__bidmanager__list_labor_rates(organization_id)`, `mcp__bidmanager__list_equipment_rates(organization_id)`,
   `mcp__bidmanager__list_material_costs(organization_id)`. For each canonical rate, compare against the
   current rate for its key:
   - **Labor:** key = classification (+ region). New or changed value →
     `mcp__bidmanager__create_labor_rate(organization_id, classification, base_hourly_rate,
     burden_percentage=…, region=…, trade=…, is_union=…, union_local=…, source=…)`.
   - **Equipment:** key = equipment_type (+ region) →
     `mcp__bidmanager__create_equipment_rate(organization_id, equipment_type, hourly_rate, description=…,
     region=…, includes_operator=…, source=…)`.
   - **Material:** key = material_name →
     `mcp__bidmanager__create_material_cost(organization_id, material_name, unit_cost, unit=…, category=…,
     supplier=…)`.
   - If the current rate matches the imported value, **skip it** (report "no change") so
     re-importing doesn't churn effective dates. `make_current=True` (the default) retires
     the prior current rate server-side when you do create a new/changed one.

## Notes
- `rate` is the type-appropriate number (labor base hourly wage, equipment hourly rate,
  material unit cost); BidSheet.ai auto-computes the burdened labor rate from
  `burden_percentage` (defaults to 35 when the column is blank).
- `rate_type` must be one of labor/equipment/material (aliases `lab`/`equip`/`mat` etc.
  are accepted); an unrecognized type is reported so you can correct it. `is_union` /
  `includes_operator` are parsed from the spreadsheet (`yes`/`y`/`true`/`1`/`x` → true).
- Rows with a blank `rate_type` are skipped; a blank `name` or a non-numeric `rate` is
  reported as an error to fix.
- The field mapping + routing is deterministic (`estimating_tools.rates`); the judgment is
  proposing the column mapping, confirming the target org, and confirming the
  skip-unchanged decisions.
