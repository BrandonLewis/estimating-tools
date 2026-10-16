---
name: import-directory
description: Import a customer's existing vendor/subcontractor directory from an Excel spreadsheet into BidSheet.ai's directory — read its columns, propose and confirm a mapping to the canonical fields, build the open canonical directory, then find-or-create the organizations and contacts (orgs by name, people by email). Via the BidSheet.ai directory MCP tools.
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

# Import an Org's Vendor/Sub Directory from Excel

Use this to onboard a customer's directory of organizations (primes/subs/vendors) and
their contacts. You read their columns, figure out the mapping to the canonical fields,
import the directory, then find-or-create each org and contact in BidSheet.ai. The import
is local; the push drives the directory MCP tools.

## Inputs
- Path to the org's directory spreadsheet (`.xlsx`).

## Workflow
1. **Inspect the columns:** read the header row — e.g. with
   `estimating_tools.directory.read_directory_rows(path)` (the keys of the first row are
   the org's column names). List them for the user.
2. **Propose and confirm the column mapping (editable artifact):** the canonical fields are
   `organization`, `region`, `license_number`, `bidder_id`, `org_phone`, `org_email`,
   `address`, `is_dbe`, `certification_number`, `certifying_agency`, `federal_id`,
   `contact_email`, `first_name`, `last_name`, `contact_phone`, `job_title`, `role`.
   Required: `organization`. Build the artifact and render it inline for the user to edit:

   ```python
   from estimating_tools.directory.excel import _CANONICAL_FIELDS, _REQUIRED, read_directory_rows
   from estimating_tools.importers.mapping_artifact import propose_mapping, render

   sample = read_directory_rows(path)
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
3. **Import:** `estimating_tools.directory.build_directory_from_excel(path, mapping)` →
   a `CanonicalDirectory`. If it raises (an unknown `role`, or `organization` missing),
   surface the message and fix the mapping/data with the user. (For a headless run, the
   `dir-import` CLI does the same with a `--mapping` JSON file.)
4. **Push (find-or-create, idempotent):** for each organization, then its contacts:
   - **Organization:** `list_organizations(search=name)` → if an existing org's name
     matches case-insensitively, reuse its `id`; else
     `create_organization(name, region=…, license_number=…, bidder_id=…, phone=org.phone,
     email=org.email, address=…, is_dbe=…, certification_number=…, certifying_agency=…,
     federal_id=…)`. Record `organization_id`.
   - **Contact:** `list_people(search=email)` → if a person with that email exists, reuse
     `person_id`; else `create_person(email, first_name=…, last_name=…,
     phone_primary=…, job_title=…, organization_id=organization_id,
     role_in_organization=role)` — a NEW person is affiliated inline (no staff needed).
     For an EXISTING person not yet on this org, `add_person_to_organization(person_id,
     organization_id, role=role)` — **staff-only; if you are not staff, surface this for a
     staff user to apply rather than calling it (see the staff-gate note below)**.
   - Re-running is safe: orgs are reused by name, people by email; an identical re-import
     creates nothing new.

## Notes
- **Staff-only gate.** BidSheet.ai restricts `update_organization`, `update_person`, and
  `add_person_to_organization` to staff users. Creating brand-new orgs/people (and a new
  person's inline affiliation via `create_person(organization_id=…)`) needs no staff. So
  if an EXISTING org or person differs from the imported data, or an existing person must
  be attached to an org, and you are not staff, **report what would change and that a
  staff user must apply it** — do not claim it was updated.
- `is_dbe` is parsed from the spreadsheet (`yes`/`y`/`true`/`1`/`x`/`dbe` → DBE);
  `role` must be one of prime_contact, engineer, pm, superintendent, estimator, executive,
  sales, other (or blank) — an unrecognized role is reported so you can correct it.
- Rows sharing the same `organization` group into one org (org-level fields from the first
  row); a row with a blank `contact_email` creates an org with no contact; duplicate
  contact emails within an org collapse to one.
- The field mapping + grouping is deterministic (`estimating_tools.directory`); the
  judgment is proposing the column mapping and confirming the org/contact matches.
