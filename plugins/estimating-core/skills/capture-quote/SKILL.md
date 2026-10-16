---
name: capture-quote
description: Capture a subcontractor/vendor's quote into BidSheet.ai as a work-package quote with per-item line items — find-or-create the work package, assign the quoted items, and capture the quote lines (changed pricing becomes a new revision, history preserved). Via the BidSheet.ai MCP.
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

# Capture a Vendor Quote

Use this to record a sub/vendor's quote (from a PDF, email, or spreadsheet) into
BidSheet.ai as a **work-package quote** with per-item line items — the structure the
spreads/leveling workflow compares. Requires the BidSheet.ai MCP, and the project's
bid items to already exist (from `push-estimate`).

## Inputs
- The vendor's quote (the agent extracts it).
- The target `project_id`.

## Workflow
1. **Extract** the quote into a `CanonicalQuote`: the vendor (`vendor_name`;
   `is_dbe` is a boolean that defaults to `false` — set it `true` only for a
   confirmed DBE; optional `vendor_id`/`contact_info`/total `amount`), the
   `work_package_name` (the scope being quoted), and `lines` — each a
   `(schedule_name, item_number)` with `unit_price` and/or `amount` (+ optional
   `quantity`), and `is_included=false` + `exclusion_notes` for any item the
   vendor is NOT bidding.
2. **Resolve the vendor against the directory (set `vendor_id`):** before building the
   plan, link the quote to a directory organization so vendors are deduped and the quote
   surfaces the org's display name / DBE / contacts. `list_organizations(search=vendor_name)`:
   - **Exact case-insensitive name match** → set the canonical quote's `vendor_id` to that
     organization's `id` (auto-link).
   - **Partial / ambiguous matches** → show them and let the user pick the right org (or
     decline).
   - **No match** → keep the free-text `vendor_name` and **offer to create the org** in the
     directory: `create_organization(name=vendor_name, is_dbe=<the quote's is_dbe>)` (this
     is not staff-gated), then set `vendor_id` to the new org's `id`.
   - **User declines / no appropriate org** → leave `vendor_id` unset; the quote keeps the
     free-text `vendor_name` (the prior behavior).
   The rest of the flow is unchanged: `plan_quote` threads `vendor_id` into the
   `quote_header`, and `create_work_package_quote(work_package_id, **plan.quote_header)`
   links the quote to the org (BidSheet.ai fills `vendor_display_name`).
3. Build the plan: `estimating_tools.quotes.plan.plan_quote(canonical)` → a
   `QuotePlan` with `work_package_name`, `quote_header`, `bid_item_refs`, and
   `lines`.
4. **Review the plan (read-only artifact):** render the plan inline for the user to
   review:

   ```python
   from estimating_tools.quotes.plan import render_quote_plan

   print(render_quote_plan(plan))
   ```

   The rendered block shows the sections that will be written to BidSheet.ai (Work package
   + quote header / Bid item refs / Line items). Ask the user to confirm before
   proceeding to Find-or-create the work package. If they want to change anything, back up to
   step 3, adjust the input, and rebuild the plan; the render is not
   editable.
5. **Find-or-create the work package** by name: `list_work_packages(project_id)` →
   reuse the one matching `plan.work_package_name`, else
   `create_work_package(project_id, plan.work_package_name)`. Record `work_package_id`.

   **Preflight — check the estimate link (warn, don't stop):**
   `get_work_package(work_package_id)` returns the resolved `estimate_id` and an
   `estimate_link_error` (BM-1, fixed 2026-08-06 — the precondition is now
   checkable in one call).
   - **`estimate_id` present, `estimate_link_error` null:** the work package
     resolves to an estimate — `apply-quotes`'s `allocate_subcontractor` will
     succeed. Proceed.
   - **`estimate_id` null:** `estimate_link_error` names the problem. The usual
     case is "no EstimatePackage" — get the project's current estimate id from
     `list_estimates(project_id)` (call it `est_id`; the null `estimate_id` from
     the work package can't be used here), WARN the user, and create the bridge
     with `create_estimate_package(est_id, work_package_id)`, then CONTINUE
     capturing. If the error reports the link is *ambiguous* (the work package is
     referenced by estimate packages on more than one estimate), surface it and
     let the estimator resolve which estimate — don't guess. Quote capture is
     idempotent, so capturing before the link is settled is safe.
6. **Resolve + assign the quoted items:** `list_bid_items(project_id)` returns each
   bid item's `id` (= `project_bid_item_id`), `item_code`, `item_number`, and flat
   `schedule_name`/`schedule_id`. For each `plan.bid_item_refs` entry (which carries
   `schedule_name` and `item_number`), resolve to its `project_bid_item_id` by
   matching on BOTH `schedule_name` and `item_number` — the same `item_number` can
   recur across schedules, so the schedule disambiguates. **Record, per resolved ref,
   the `project_bid_item_id`** — carry it to step 7 as the stable key across both
   hops. Then `assign_items_to_package(work_package_id, bid_item_ids=[...])` for any
   not already in the package.
7. **Map items to work-package items:** `get_work_package(work_package_id)` → its
   items each carry `id` (= `work_package_item_id`) and their source
   `project_bid_item_id`. Build the map `project_bid_item_id → work_package_item_id`,
   and resolve each line via the `project_bid_item_id` recorded in step 6. This is
   exact even when the same `(item_code, item_number)` recurs across schedules,
   because `project_bid_item_id` is unique per bid item.
8. **Find-or-create the quote** by vendor: `list_work_package_quotes(work_package_id)`
   (each quote carries `vendor_id`, `vendor_name`, and `vendor_display_name`). Match in
   this order:
   - **By `vendor_id` (preferred):** if the captured quote has a `vendor_id` (resolved
     against the directory in step 2), reuse an existing quote with the SAME `vendor_id` —
     the directory organization is the vendor identity, so name variants
     ("Acme Striping" vs "Acme Striping, Inc.") still dedup to one quote.
   - **By `vendor_name` (fallback):** if the captured quote has no `vendor_id` (the vendor
     was not linked / the user kept it free-text), reuse a quote whose `vendor_name`
     matches, as before.
   - **Else create:** `create_work_package_quote(work_package_id, **plan.quote_header)`.
   Record `quote_id`. (Do not back-fill an existing free-text quote's `vendor_id` here —
   matching only selects which quote receives this capture.)
9. **Capture the lines (revision-aware):** read the current revision's lines with
   `list_work_package_quote_line_items(quote_id)`. Diff the planned lines against them
   with `estimating_tools.quotes.diff_quote_lines(planned_lines, existing_lines)` (each
   planned line resolved to its `work_package_item_id` per step 7):
   - **The quote was just created this run** (no existing lines) → create each line with
     `create_work_package_quote_line_item(quote_id, work_package_item_id, unit_price=…,
     amount=…, quantity=…, is_included=…, exclusion_notes=…)`. This is the initial
     capture (revision v1).
   - **`diff.unchanged`** → make NO writes; report "no change to <vendor>'s quote"
     (re-capturing identical pricing is a no-op).
   - **`diff.changed` or `diff.added`** on a quote that already had lines → capture a
     REVISION: `create_quote_revision(quote_id, copy_line_items=True)` mints the new
     current revision (carrying the prior lines forward); record the new revision's
     `quote_id`. Then on the NEW revision: for each `diff.changed` line,
     `update_work_package_quote_line_item(line_item_id, unit_price=…, amount=…,
     quantity=…, is_included=…, exclusion_notes=…)` — resolve `line_item_id` from the new
     revision's lines by `work_package_item_id` (the carried-forward copy of the line the
     diff's `existing_line_id` referred to); for each `diff.added` line,
     `create_work_package_quote_line_item(new_quote_id, work_package_item_id, …)`.
   - If an existing line is NOT in the planned set (a possibly-removed item), surface it
     to the user — do NOT delete it.
10. **Record quote conditions** while the document is in hand: the separate-acceptance
    clause (quote it verbatim) and any scope folds ("cages included in item 41").

    **Record conditions (BM-primary).** Set them on the BidSheet.ai quote directly:
    the acceptance clause via the quote itself —
    `update_work_package_quote(quote_id, separate_acceptance_permitted=True|False,
    acceptance_notes="<verbatim clause>")` (or pass them on `create_work_package_quote`
    when first recording it; `clear_separate_acceptance=True` resets to unknown) —
    and the scope folds via
    `set_quote_scope_tags(quote_id, scope_tags=[{"group": "<name>",
    "items": [{"schedule": "<sched>", "item_number": "<num>"}],
    "treatment": "separate"|"folded",
    "folded_into": {"schedule": "<sched>", "item_number": "<num>"} | null,
    "notes": "<text>"}])`. Include
    `items` — the bid items this scope covers for this vendor; leveling's
    fold-coverage math (`apply_conditions`) needs it, and dropping it silently
    breaks the group basis. A quote silent on acceptance stays NULL (never
    guess `True`).

    **Offline fallback.** No connection, the quote has no BM id yet, or the
    server predates BM#1045 (`set_quote_scope_tags` errors as an unknown tool)
    → append to the
    local journal as today; it feeds compare-quotes' offline path:
    `~/.estimating/bin/est-quotespace condition --journal <bid working dir>/Subquotes/quote-conditions.jsonl
    --package "<name>" [--bm-package-id <id>] --vendor "<org name>"
    [--bm-vendor-id <id>] --separate-acceptance yes|no|unknown
    [--acceptance-notes "<clause>"] [--tag '<scope-tag JSON>']…` — `--tag` is
    repeatable, one per scope group:
    `{"group": "<name>", "items": [{"schedule": "<sched>", "item_number": "<num>"}],
    "treatment": "separate"|"folded",
    "folded_into": {"schedule": "<sched>", "item_number": "<num>"} | null}`
    (`folded` requires `folded_into`; `separate` forbids it).
    Record-level `--notes "<free text>"` captures any other condition context on the record.
    Each `--tag` JSON also takes an optional `"notes"` field for per-group context.
    A quote silent on acceptance stays `unknown` — never guess `yes`. Latest record
    per (package, vendor) wins, so re-capturing a revision with changed conditions is
    just another append.
11. **Report:** for an initial capture, the lines created; for a revision, "captured
    revision v<N> for <vendor>" with the changed/added lines, noting the prior revision is
    preserved (`list_quote_revisions(quote_id)` shows the history); for an identical
    re-capture, "no change".

## Notes
- **Estimate-package prerequisite:** An `EstimatePackage` (created with
  `create_estimate_package(estimate_id, work_package_id)`) is the bridge between a
  work package and the estimate — `allocate_subcontractor` (called by
  `apply-quotes`) fails with "The work package is not linked to an estimate."
  when it is absent. Since BidManager#1027 (BM-1, fixed 2026-08-06)
  `allocate_subcontractor` resolves the estimate through that
  EstimatePackage→WorkPackage edge and succeeds once the package exists, and
  `get_work_package` exposes the resolved `estimate_id` / `estimate_link_error`
  so the precondition is checkable up front (the step-5 preflight does this and
  creates the package with a warning when it's missing).
- Re-running is safe (idempotent): the work package and the vendor's quote are
  reused, an identical re-capture is a no-op, and new line items are created; CHANGED
  pricing is captured as a new revision (see below), not overwritten in place.
- A captured quote that resolved to a directory organization dedups on its `vendor_id`, so
  the same vendor entered with name variants does not create duplicate quotes (and
  re-captures land on the right quote + its revision history). An unlinked/free-text quote
  still dedups on `vendor_name`.
- Re-capturing a vendor's quote with CHANGED pricing is recorded as a new revision
  (`create_quote_revision`) — the prior revision is preserved as history
  (`list_quote_revisions`); leveling/award see the current revision by default. An
  identical re-capture is a no-op.
- Resolution is exact end-to-end: `list_bid_items` exposes flat `schedule_name` and
  `get_work_package` items expose their source `project_bid_item_id` (BidSheet.ai
  #571), so a line resolves `(schedule_name, item_number) → project_bid_item_id →
  work_package_item_id` with no ambiguity, even when an `item_number` recurs across
  schedules.
- The field mapping is deterministic (`estimating_tools.quotes.plan`); the judgment
  is extracting the quote and confirming the work-package scope and matches.
- Once a work package has multiple vendor quotes, use the `compare-quotes` skill to
  level them side-by-side (best price per item, totals, coverage gaps, outliers).
- The quote-conditions journal (`Subquotes/quote-conditions.jsonl`, step 10) is the
  input to `compare-quotes`' scope-split leveling — scope groups are only compared on
  an all-in basis, and best-of-breed only gated on acceptance flags, for conditions
  recorded here. Untagged folds surface downstream as warnings at best; capture time,
  with the document in hand, is when the conditions are cheapest to record.
- Captured quotes link to the org/vendor directory: the vendor name is resolved to a
  directory organization (`vendor_id`) during capture — deduping vendors across quotes and
  surfacing the org's display name / DBE / contacts. When no org matches and the user
  declines creating one, the quote keeps the free-text `vendor_name` (unchanged behavior).
  Use the `import-directory` skill to bulk-load an org's existing vendor list first.
- **Batch mode:** capturing N quotes in one sitting does NOT mean N render/confirm
  loops. Build all N plans first, consolidate them into ONE review artifact/table
  covering every quote (vendor, work package, line count, totals, exclusions), get a
  single confirmation, then capture all confirmed quotes — falling back to per-quote
  review only for the ones the user flags.
- Consult the active org profile's `house_rules` (`estimating_tools.profiles.load()`,
  the `house_rules` section) and apply them when extracting quote math — surfacing
  which rule was applied whenever a vendor's stated number is adjusted (e.g. "unit
  price governs: carried $160 × 51 pay qty = $8,160, vendor stated $13,440").
- Field limits + silent rounding on quote writes (`contact_info` 200 chars,
  `exclusion_notes` 500 chars, 2-dp prices/percentages): see the api-constraints
  reference in the `estimating-reference` skill
  (`../estimating-reference/references/api-constraints.md`).
