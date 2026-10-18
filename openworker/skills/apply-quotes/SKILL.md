---
name: apply-quotes
description: Award a work package's chosen vendor quotes to the estimate as subcontractor allocations and roll up the estimate package — via the BidSheet.ai MCP. Confirms before writing; idempotent; adjusts on bid-day revisions. Writes.
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

# Apply / Award Vendor Quotes

Use this after `compare-quotes` to AWARD the chosen vendor pricing — post it to the
estimate as **subcontractor allocations** and roll up the estimate package. This
**writes** to BidSheet.ai, but only after you confirm the plan. Built for bid day:
partial bids are normal (a sub bids the structures; the GC self-performs
excavation/backfill), and quotes get revised — re-run to adjust the award.

**Precondition:** the project has a priced estimate (`price-estimate`). Each
allocation resolves the quote line to its estimate item; if that fails, run
`price-estimate` first.

## Inputs
- The target `project_id` and the work package (by name or `work_package_id`).
- The award decision (gathered below).

## Workflow
1. **Resolve the work package:** `mcp__bidmanager__list_work_packages(project_id)` → match by name, or
   use the given `work_package_id`. Record `work_package_id`.
2. **(Re)build the spread** (read-only), exactly as `compare-quotes` does:
   `mcp__bidmanager__get_work_package` items + `mcp__bidmanager__list_bid_items` + `mcp__bidmanager__list_work_package_quotes` +
   `mcp__bidmanager__list_work_package_quote_line_items` per quote →
   `estimating_tools.spreads.build_spread(...)`. Building fresh each run reflects any
   revised lines.
3. **Get the award decision** from the user:
   - `vendor` — one `vendor_id` gets all the items it bid; or
   - `manual` — a list of `{work_package_item_id, vendor_id}` (multiple subs per item
     allowed, e.g. a sub does the structures and the GC self-performs the rest).
   - Separately, ask whether the user wants to **accept any vendor alternate**
     (`Cell(status="alternate")` on the spread) — an alternate is scope the vendor
     is offering as an option, never part of either strategy above. Accepting one
     is step 8a, a deliberate action outside the batch plan.
4. **Plan it:** `estimating_tools.spreads.plan_award(spread, strategy, vendor_id=…,
   selection=…)` → an `AwardPlan` (entries with `quote_line_item_id` +
   `allocation_type`/`value`; per-item coverage with the self-perform remainder).
   `plan_award` never includes an alternate cell (status `"alternate"`) in either
   strategy — same as an excluded cell, it is skipped even when manually selected —
   so accepting one is always the separate step 8a below, never silently planned.
5. **Forbidden-mix guard (BEFORE any allocation write):** read the quote-conditions
   journal — `<bid working dir>/Subquotes/quote-conditions.jsonl` (written by
   `capture-quote`); load the current records and filter to this package:

   ```python
   from estimating_tools.quotespace.conditions import read_conditions
   from estimating_tools.quotespace.model import current_records
   ```

   Match planned-award vendors to journal records by `bm_vendor_id` when present,
   else by casefolded org name — the same rule the leveling engine uses.
   For each vendor the plan awards PART (not all) of the items that vendor bid:
   - `separate_acceptance_permitted` is `false` → **STOP.** Make no writes. Surface
     the vendor's `acceptance_notes` clause **verbatim** — the vendor's own terms
     forbid this mix. The paths forward are a whole-quote award to that vendor, an
     award that excludes them, or the user renegotiating the clause with the vendor
     (then re-recording the condition via `est-quotespace condition`).
   - `null` / vendor unrecorded / journal missing → **WARN** ("acceptance terms for
     <vendor> are unverified — this partial award assumes permission the quote
     doesn't grant") and require the user's **explicit confirmation** of that risk
     before proceeding to the confirm step.
   A whole-quote award (every item the vendor bid) needs no guard — separate
   acceptance is not in play.
6. **Detect superseded allocations:** `mcp__bidmanager__list_subcontractor_allocations(quote_id=…)` for
   the package's quotes → any existing allocation whose `quote_line_item_id` is NOT in
   the new plan is a *candidate* for **superseded** (e.g. a revision changed the
   winner). Before flagging one, check whether it is an **accepted alternate**
   (step 8a — its line has `is_alternate=true`): `plan_award` never includes an
   alternate line (step 4), so every accepted alternate looks like a candidate here
   even when nothing changed. Split on whether its line is still on the quote's
   **current revision** (check `mcp__bidmanager__list_work_package_quote_line_items(quote_id)`):
   - **Current revision** → it is NOT superseded. Leave it out of the superseded
     list; list it separately as **"accepted alternates (kept)"** so the user can see
     it's still in effect, and make no write for it.
   - **Superseded revision** (a newer current revision replaced the line it points
     at) → flag it "vendor <X> revised to v<N> — re-accept the alternate on v<N>"; this
     needs a fresh, confirmed step 8a accept on the new revision's line, not a plain
     update/removal.
   Every other allocation not in the new plan (i.e. not an accepted alternate) is a
   genuine superseded allocation — usually the vendor **revised** their quote and the
   line the allocation pointed at belongs to a superseded revision that a new current
   revision has replaced. Surface it as "vendor <X> revised to v<N> — re-point the
   award to the current revision's line" (use `mcp__bidmanager__list_quote_revisions(quote_id)` to show
   the history if helpful), and handle it with the same confirm-driven update/removal.
7. **Confirm BEFORE writing:** show `estimating_tools.spreads.render_award_plan(plan)`,
   the superseded allocations that would be removed, and the accepted alternates kept
   unchanged (step 6). If the user's `manual` selection (step 3) named a
   `{work_package_item_id, vendor_id}` pair whose cell on the spread is
   `Cell(status="alternate")`, say plainly that it was dropped from this plan (step 4 —
   `plan_award` never includes an alternate) and point them to step 8a if they want to
   award it. Make NO writes until the user explicitly confirms.
8. **Upsert allocations** (on confirmation): for each entry, if no allocation exists
   for its `quote_line_item_id`, `mcp__bidmanager__allocate_subcontractor(quote_line_item_id,
   allocation_type, value)` (the result has a `created` flag); if one exists and its
   `allocation_type`/`value` differ, `mcp__bidmanager__update_subcontractor_allocation(allocation_id,
   …)`; skip unchanged. Remove each **confirmed** superseded allocation with
   `mcp__bidmanager__remove_subcontractor_allocation(allocation_id)`.
8a. **Accepting a vendor alternate (only if the user asked, step 3):** allocating an
    alternate line's `quote_line_item_id` (from the spread's `Cell(status="alternate")`,
    or `mcp__bidmanager__list_work_package_quote_line_items`) **without** `accept_alternate=true` is
    **refused with an error** ("Accept the alternate (`accept_alternate`) to allocate
    it.") — so call `mcp__bidmanager__allocate_subcontractor(quote_line_item_id, allocation_type, value,
    accept_alternate=True)` (same on `mcp__bidmanager__update_subcontractor_allocation`). Confirm the
    specific line, its price, and that it is an add to the award **before** making
    this call — it is not covered by the step 7 confirm, which only shows the
    strategy's planned entries. Likewise, don't allocate an **excluded** line's
    `quote_line_item_id` — the vendor isn't bidding it. Unlike an alternate, the server
    does NOT refuse this call: it silently creates an allocation that posts **$0**
    (`accept_alternate` has no effect here either way). There is no override that makes
    excluded scope a legitimate award, so skip excluded lines entirely rather than
    calling `mcp__bidmanager__allocate_subcontractor` on them.
9. **Roll up the estimate package:** find it for this work package —
   `mcp__bidmanager__list_estimates(project_id)` → the project's estimate →
   `mcp__bidmanager__list_estimate_packages(estimate_id)` → the package whose `work_package_id`
   matches → `mcp__bidmanager__recalculate_estimate_package_totals(package_id)`. If none exists, skip
   and say so.
10. **Report:** allocations created / updated / skipped / removed; per-item
    self-perform remainders; and the refreshed estimate-package totals.

## Notes
- The remainder after partial awards is the GC's self-perform (or a later manual
  allocation) — it is reported, never auto-filled.
- Re-running is safe and is the bid-day path: it updates changed allocations and
  surfaces superseded ones for confirm-driven removal — no duplicates.
- This cycle does NOT change quote status (award is recorded as allocations, not on
  the quote). The field mapping is deterministic (`estimating_tools.spreads`); the
  judgment is the award decision and confirming the writes.
- Quote revisions now preserve history (BidManager #556): a vendor's revised quote is a
  new current revision captured by `capture-quote`; leveling and award operate on the
  current revision, and prior revisions remain for audit (`mcp__bidmanager__list_quote_revisions`).
- BidSheet.ai write constraints (`allocation_percentage` precision, silent rounding,
  tool-signature footguns): see `../estimating-reference/references/api-constraints.md`.
- A vendor alternate is accepted one line at a time, confirmed each time (step 8a) —
  never batched into `plan_award`/`render_award_plan` like a normal award. It is a
  conscious add to scope, not a pricing choice among competing bids.
