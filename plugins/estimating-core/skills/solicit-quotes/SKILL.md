---
name: solicit-quotes
description: Solicit subcontractor/vendor quotes for a work package — generate per-vendor ITB documents (scope from the briefing pack, items from the work package, org-profile letterhead) and record who was solicited when in the bid working dir's solicitation journal, with optional Gmail drafts. Via the BidSheet.ai MCP for package/vendor reads; sending stays a human act. Writes local files; BM writes limited to find-or-create of new vendors.
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

# Solicit Quotes for a Work Package

Use this when the estimator wants to invite subs/vendors to bid a work
package. The `est-quotespace` CLI does the deterministic document rendering
and journal writes; the judgment — which vendors, what scope text, when it
actually got sent — stays here.

## Inputs
- The work package (name or id) — `list_work_packages` / `get_work_package`.
- Vendors to invite — from the BM directory (`list_organizations`,
  `list_people`) or named by the user.
- If the project carries a DBE (or similar disadvantaged-business)
  participation goal: the goal percent — it shapes vendor selection (see
  step 2). `estimating_tools.takeoff.core.check_dbe_requirements` computes
  the goal amount from the project value and goal percent.
- If the project is intaken: the bid working dir (from the intake manifest)
  — the journal lives at `<bid working dir>/Subquotes/solicitations.jsonl`
  and ITBs at `<bid working dir>/Subquotes/ITB/`.

## Workflow
1. **Resolve the package.** `get_work_package` for the item list (number,
   schedule, description, quantity, unit). Write it as the package JSON:
   `{"project_name", "name", "items": [{"schedule", "item_number",
   "description", "quantity", "unit"}]}`.
2. **Resolve vendors.** For each vendor: find in the directory
   (`list_organizations`, case-insensitive name); if absent, confirm with the
   user and find-or-create per import-directory rules (`create_organization`,
   `create_person` by email). Collect contact emails. Write the vendors JSON:
   `[{"org_name", "bm_vendor_id", "contacts": [emails]}]`.

   **DBE outreach.** When the project carries a DBE (or similar)
   participation goal, solicit DBE-certified vendors for the package
   deliberately — don't leave goal coverage to whoever happens to bid — and
   make sure that outreach gets RECORDED (the solicitation records in steps
   6 and 8 are the documentation). A public-works bid can fail a
   good-faith-effort review if targeted DBE outreach isn't documented: who
   was invited, when, and through what channel is exactly what the
   journal/BM records exist to prove.
3. **Scope text.** Pull the relevant scope from the briefing pack
   (`Briefing/` in the project dir) for the structures behind the package's
   bid items; a few sentences is enough. Save to a temp file. Ask the user
   for the respond-by date.
4. **Letterhead.** If an org profile is active, use its `letterhead.md`;
   otherwise omit (agnostic fallback).
5. **Generate ITBs:** `~/.estimating/bin/est-quotespace itb --package-json <pkg.json>
   --vendors-json <vendors.json> --scope <scope.md> [--letterhead <lh.md>]
   --respond-by <date> -o <bid working dir>/Subquotes/ITB`. Show the user
   one rendered ITB and confirm before continuing.
6. **Record solicitations.** For each vendor:

   **Record the solicitation (BM-primary).** When the work package resolves in
   BidSheet.ai (it does — you looked it up in step 1) and a connection is
   available, record each solicitation directly:
   `record_solicitation(work_package_id, vendor_id, sent_at=<date>, channel=<...>,
   status="planned"|"sent"|"declined", contacts=[emails],
   items=[{"schedule": "<sched>", "item_number": "<num>"}], notes=<...>)`. It is
   append-only per (work_package, vendor):
   call it again to mark `sent` with `sent_at`, or `declined` — the prior revision
   is preserved. Unknown fields copy forward from the last revision.

   **Offline / pre-intake fallback.** If BidSheet.ai is not connected or the work
   package has no BM id yet, append to the local journal instead
   (`~/.estimating/bin/est-quotespace solicit --journal <bid dir>/Subquotes/solicitations.jsonl
   --package "<name>" --bm-package-id <id> --vendor "<org name>" --bm-vendor-id
   <id> --contact <email> --items '<JSON of the package's item keys>'
   --status planned`) and, when you next have a connection, run the sync (below)
   to push it.

   **Sync a journal to BM.** Dump BM's current state
   (`list_solicitations(work_package_id)` per package). Its rows already carry
   `work_package_name` and `vendor_name`, so no id→name resolution is needed —
   copy `vendor_name` to a `vendor_org_name` key on each row (the sync CLI reads
   that key), then
   `~/.estimating/bin/est-quotespace sync --journal <journal> --bm-solicitations <dump.json>` — its
   stdout is the delta to push; `record_solicitation` each delta entry.
7. **Optional email drafts.** If the Gmail MCP is connected, offer to create
   one draft per vendor (`create_draft`: to = contacts, subject =
   "Invitation to Bid — <package> — <project>", body = the ITB markdown).
   NEVER send — drafts only; the estimator reviews and sends.
8. **Mark sent.** When the user says the ITBs went out, re-run
   `~/.estimating/bin/est-quotespace solicit` per vendor with `--status sent --sent-at
   <YYYY-MM-DD> --channel <email|phone|portal|other>` (latest record wins —
   this is the append-only journal idiom). REPEAT the same `--items` as the
   planned record: because the latest record wins, omitting `--items`
   silently broadens the vendor's coverage to the whole package. Declines
   later: `--status declined` with a `--notes` reason (same `--items` rule).

## Notes
- The journal is append-only; never edit or rewrite existing lines.
- A vendor not yet in BM can still be solicited — omit `--bm-vendor-id`.
- Coverage of who was solicited/received/leveled is the `quote-coverage`
  skill's job; this skill only writes the solicited side.
