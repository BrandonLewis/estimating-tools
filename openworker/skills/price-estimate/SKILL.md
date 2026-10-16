---
name: price-estimate
description: Price an imported estimate into BidSheet.ai — create/reuse an Estimate and price each existing bid item from the CanonicalEstimate's unit_price, consulting the historical bank (est-hist suggest) per mapped item for an estimator-confirmed override, via the BidSheet.ai MCP. Idempotent; structure (push-estimate) must already exist.
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

# Price an Estimate in BidSheet.ai

Use this after `push-estimate` has loaded a project's bid-schedule structure, to
price those bid items from an imported `CanonicalEstimate`. It creates (or reuses)
an **Estimate** and adds a priced **estimate item** for each bid item that has a
`unit_price`. Requires the BidSheet.ai MCP to be connected.

Imported prices (`unit_price`) are the starting point; the historical
consultation below may replace them per item when the estimator confirms a
different number. Items with no price are left unpriced (price them by hand or
via vendor quotes — a separate skill).

## Inputs
- A `CanonicalEstimate` (a `*.canonical.json` from `est-import`, or in hand) whose
  project's bid items already exist in BidSheet.ai (from `push-estimate`).
- The target `project_id`.

## Historical consultation (Phase 5)

Before writing each item's price in the Workflow below (the per-item loop in
step 6), consult the historical bank for items that carry — or can be mapped
to — an `(agency, bid_item_code)` key. This augments the judgment call, it
does not replace it: the estimator still confirms every number.

1. **Code mapping.** Items whose import already carried an agency code:
   confirm it with `mcp__bidmanager__search_bid_items_by_code(agency=..., bid_item_code=...)`.
   Items with no mapping: propose one via `mcp__bidmanager__search_bid_item_templates` (match
   on `item_code`/description) and confirm the proposal with the estimator.
   Persist the mapping via `mcp__bidmanager__update_bid_item` if the bid-item's `agency`/
   `bid_item_code` fields are writable through the MCP (verify once per
   session — try it on the first mapped item and note whether it sticks);
   if they're not yet writable, carry the mapping in-session instead (the
   historical records are keyed correctly either way) and tell the user the
   mapping didn't persist.
2. **Fetch:** `mcp__bidmanager__list_historical_records(agency=..., bid_item_code=..., limit=100)`.
3. **Suggest:** write the fetched records to a JSONL file and run
   `est-hist suggest --records <file> --code <bid_item_code> --qty <item's
   estimate quantity> --unit <unit> --region <region> --as-of <bid date>` —
   its stdout is the suggestion JSON (`status`, suggested `p25`/`median`/
   `p75`, `comparables` with unit_price/weight/age_years/outcome/bidder/
   quantity/unit/region/bid_date/project_ref, and `excluded` with reasons).
4. **Present per item:** the suggested p25/median/p75, the comparable count
   and `status` (`ok`/`thin`/`no_history`), and the top comparables (date,
   quantity, region, bidder, outcome). Ages are shown raw, as returned — no
   escalation is applied unless the org profile sets
   `estimating.escalation_rate_annual`.
5. **Estimator confirms a number** — either the suggested figure or their own
   override — before it is written; this may confirm or replace the plan's
   imported `unit_price` for that item. Only a confirmed number is passed to
   `mcp__bidmanager__create_estimate_item` in step 6. NEVER auto-price from a suggestion —
   `thin` and `no_history` items, and any item the estimator declines to
   confirm, are listed explicitly as unpriced-by-history and left for manual
   pricing.

## Workflow
1. Build the plan deterministically with
   `estimating_tools.importers.pricing.plan_pricing(canonical)` → a `PricingPlan`
   with `estimate_name` and priced `items`
   (`{schedule_name, item_number, unit_price, confidence_level, notes}`; null-price
   items are already omitted).
2. **Review the plan (read-only artifact):** render the plan inline for the user to
   review:

   ```python
   from estimating_tools.importers.pricing import render_pricing_plan

   print(render_pricing_plan(plan))
   ```

   The rendered block shows the sections that will be written to BidSheet.ai (Estimate +
   Priced items). Ask the user to confirm before
   proceeding to Create / reuse the Estimate. If they want to change anything, back up to
   step 1, adjust the input, and rebuild the plan; the render is not
   editable.
3. **Find-or-create the estimate:** `mcp__bidmanager__list_estimates(project_id)`. If one matches
   `plan.estimate_name`, reuse its `estimate_id`; otherwise
   `mcp__bidmanager__create_estimate(project_id, plan.estimate_name)`.
4. **Resolve (schedule_name, item_number) pairs to bid items:**
   `mcp__bidmanager__list_bid_items(project_id)` → build a map keyed by
   `(bid_item["schedule_name"], bid_item["item_number"]) → project_bid_item_id`.
   For each plan item, look up `(item["schedule_name"], item["item_number"])` in
   that map to find the correct `project_bid_item_id`.  This mirrors push-estimate's
   per-schedule handling and prevents collisions when the same item_number appears
   in multiple schedules (e.g. "1" in both "Base Bid" and "Additive Alt 1").
5. **Skip already-priced:** `mcp__bidmanager__list_estimate_items(estimate_id)` → the set of
   `project_bid_item_id`s already priced; don't re-price them.
6. For each remaining priced item, run the **Historical consultation** above
   first; use the estimator-confirmed number in place of `item["unit_price"]`
   if one was confirmed (otherwise the plan's imported price stands
   unchanged). Then call `mcp__bidmanager__create_estimate_item` with the `project_bid_item_id`
   resolved in step 4 (from `(item["schedule_name"], item["item_number"])`)
   and the item's fields:
   `mcp__bidmanager__create_estimate_item(estimate_id=estimate_id,
   project_bid_item_id=<resolved id>, unit_price=<confirmed or item["unit_price"]>,
   confidence_level=item["confidence_level"], notes=item["notes"])`.
7. Report priced / skipped-already-priced / unpriced-by-history counts and
   show `mcp__bidmanager__get_estimate_summary(estimate_id)`. (Items with no `unit_price` were
   already omitted from the plan by `plan_pricing`, so they are simply not
   pushed — there is no null-price count to report from the plan. The
   unpriced-by-history count is the `thin`/`no_history`/declined items from
   step 6's historical consultation.)
8. **Deposit hook (recommended):** offer to deposit the confirmed prices
   into the historical bank as `outcome: "estimated"` records — the
   `import-historicals` skill's `from-estimate` mode, reusing the code
   mappings confirmed in the consultation above (its idempotence check is
   keyed `(project_ref, outcome)`, so this never duplicates an earlier
   deposit). Decline is fine; the bank just doesn't grow this time. After
   the bid is later submitted, the same mode with `--outcome bid` records
   what we actually bid, and on results day the results tab comes back in
   via `import-historicals` (which also records competitor totals through
   `mcp__bidmanager__record_competitor_bid`). Finally, offer to bank the priced items'
   structure as bid-item scaffolds for the next bid — the `save-scaffolds`
   skill.

## Notes
- Re-running is safe: the estimate is reused by name and bid items already priced
  are skipped — no duplicates.
- The field mapping is deterministic (`estimating_tools.importers.pricing`); the
  judgment is resolving the project/estimate, confirming matches, and the
  per-item historical-price confirmation (or rejection) in the consultation
  above.
- Prices are flat per-item from the import. Quote-based and sub-allocation pricing
  are separate, later skills.
- To capture a subcontractor/vendor's quote on a scope (as a work-package quote for
  side-by-side comparison), use the `capture-quote` skill.
- BidSheet.ai write constraints and tool-signature footguns (`estimated_unit_price`
  rounds silently to 2 dp; `mcp__bidmanager__update_estimate_item` edits pricing, never quantity):
  see `../estimating-reference/references/api-constraints.md`.
- The deposit hook is how the bank grows from normal bidding activity —
  price → `estimated`, submit → `bid`, results → `awarded`/`competitor_bid`
  (see `import-historicals`). Skipping it is allowed but starves future
  consultations.
