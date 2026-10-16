---
name: import-assemblies
description: Import a new customer's existing assembly library from an Excel spreadsheet — read its columns, propose and confirm a mapping to the canonical fields, build the open canonical library, then hand it to create-assemblies to push into BidSheet.ai.
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

# Import an Org's Assembly Library from Excel

Use this to onboard a customer who keeps their assemblies in a spreadsheet. You read
their columns, figure out the mapping to the canonical fields, import the library, and
hand it to `create-assemblies` to push into BidSheet.ai as org templates. The import is
local (no BidSheet.ai); the push is `create-assemblies`' job.

## Inputs
- Path to the org's assembly spreadsheet (`.xlsx`).
- The target organization (passed through to `create-assemblies`).

## Workflow
1. **Inspect the columns:** read the spreadsheet's header row — e.g. with
   `estimating_tools.assemblies.read_assembly_rows(path)` (the keys of the first row are
   the org's column names), or open the file. List the columns for the user.
2. **Propose and confirm the column mapping (editable artifact):** the canonical fields are
   `assembly`, `assembly_type`, `cost_code`, `assembly_description`, `component_type`,
   `component`, `quantity`, `unit`, `unit_cost`, `rate_ref`, `trade`,
   `component_description`. Required: `assembly`, `component_type`, `component`. Build the
   artifact and render it inline for the user to edit:

   ```python
   from estimating_tools.assemblies.excel import _CANONICAL_FIELDS, _REQUIRED, read_assembly_rows
   from estimating_tools.importers.mapping_artifact import propose_mapping, render

   sample = read_assembly_rows(path)
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
3. **Import:** `estimating_tools.assemblies.build_assembly_library_from_excel(path,
   mapping)` → a `CanonicalAssemblyLibrary`. If it raises (an unrecognized
   `component_type`, or a required field whose column isn't present), surface the message
   and fix the mapping or the data with the user. (For a headless/scripted run, the
   `asm-import` CLI does the same with a `--mapping` JSON file.)
4. **Review & edit the imported library (editable artifact):** render the imported
   library inline for the user to review and clean up (rename assemblies the spreadsheet
   formatted awkwardly, drop stragglers, correct component types the Excel importer
   couldn't disambiguate):

   ```python
   from estimating_tools.assemblies.artifact import render

   print(render(library))
   ```

   Users edit the library and send it back — the Save message, or a pasted block. Parse the edits:

   ```python
   from estimating_tools.assemblies.artifact import library_diagnostics, parse

   library = parse(user_edited_text)
   for warning in library_diagnostics(library):
       print(warning)
   ```

   The parser raises `ValueError` with a section+row locator on malformed input; surface
   the message and re-render for the user to fix. Hand the cleaned library off to the
   `create-assemblies` skill (which now starts at its plan step — the library is already
   reviewed).
5. **Hand off to push:** pass the canonical library to the `create-assemblies` skill —
   it resolves the org, plans the push, and find-or-creates the assemblies + components
   in BidSheet.ai (estimate-safe). Optionally write the canonical JSON for the org to keep.

## Notes
- `component_type` values are normalized (e.g. `Labor`/`MAT`/`equip` → `labor`/`material`/
  `equipment`); an unrecognized value is reported so you can correct the mapping/data.
- Rows sharing the same `assembly` value group into one assembly (assembly-level fields
  from the first row). Blank rows and rows with no assembly name are skipped.
- This skill makes NO BidSheet.ai calls itself — the import is local and the push is
  `create-assemblies`.
