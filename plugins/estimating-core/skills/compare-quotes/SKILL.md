---
name: compare-quotes
description: Level a work package's vendor quotes into a side-by-side spread — best price per item, per-vendor totals + coverage, best-of-breed, gaps, and outliers — rendered as a table. Read-only, via the BidSheet.ai MCP.
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

# Compare Vendor Quotes (Spread / Leveling)

Use this to level the multiple vendor quotes on a work package (captured via
`capture-quote`) — a side-by-side spread to pick the best pricing. **Read-only:**
it reads and presents; it makes NO changes. Applying the chosen prices (sub
allocations / awarding) is a separate, later skill. Requires the BidSheet.ai MCP.

## Inputs
- The target `project_id` and the work package (by name or `work_package_id`).

## Workflow
1. **Resolve the work package:** `list_work_packages(project_id)` → match by name (or
   use a given `work_package_id`). Record `work_package_id`.
2. **Fetch the data (read-only):**
   - `get_work_package(work_package_id)` → its items (each `id` = `work_package_item_id`,
     plus `project_bid_item_id`, `item_code`, `item_number`, `schedule_name`).
   - `list_bid_items(project_id)` → full `quantity`, `unit`, `description` per item
     (join to rows by `project_bid_item_id`).
   - `list_work_package_quotes(work_package_id)` → the vendor quotes (columns).
   - `list_work_package_quote_line_items(quote_id)` for EACH quote → the line cells,
     keyed as `lines_by_quote = {quote_id: [lines]}`.
3. **Source the quote conditions.**

   **Source conditions (BM-primary).** The quotes you already fetched for
   leveling now carry `separate_acceptance_permitted`, `acceptance_notes`, and
   `scope_tags` (`get_quote` / `list_work_package_quotes` serialize them since
   BM#1045). Build the condition records with one per quote and pass them to
   `apply_conditions` — unchanged:

   ```python
   from estimating_tools.quotespace.conditions import QuoteConditionRecord
   records = [QuoteConditionRecord.from_bm_quote(q, work_package_name=work_package_name)
              for q in quotes]
   ```

   **Offline fallback.** Not connected → read the quote-conditions journal
   `<bid working dir>/Subquotes/quote-conditions.jsonl` (written by `capture-quote`)
   as today. Load the current records and filter to this package:

   ```python
   from estimating_tools.quotespace.conditions import read_conditions
   from estimating_tools.quotespace.model import current_records

   records = [r for r in current_records(read_conditions(journal_path)).values()
              if r.work_package["name"].strip().casefold()
              == work_package_name.strip().casefold()]
   ```

   No BM conditions and no journal → proceed with `records = []`, and state on the
   board that quote conditions are unrecorded (the spread then compares raw per-item
   prices, which scope folds can invert).
4. **Build the spread:** `estimating_tools.spreads.build_spread(items, bid_items,
   quotes, lines_by_quote)` → a `Spread` (rows = items, columns = vendors;
   best-per-item on unit_price; per-vendor totals + coverage; best-of-breed total;
   partial flags; no-bid/excluded gaps; outliers). Then apply the conditions
   post-pass BEFORE rendering:
   `estimating_tools.spreads.conditions.apply_conditions(spread, records)` —
   scope-group subtotals over each group's comparable basis (per-item best is
   suppressed inside a group), the obtainable single-vendor total, the obtainable
   best mix, acceptance-gated best-of-breed, and heuristic warnings. With no records
   the spread is unchanged.
5. **Present it:** by default `estimating_tools.spreads.render_spread(spread)` → show
   the markdown table (with any scope-group sections and the decision-ordered summary
   block). If the user only wants the data (e.g. to feed a later step), hand back the
   structured `Spread` without rendering.
6. **Narrate the takeaways:** lead with the **obtainable single-vendor total** —
   that is THE number to carry, not the best-of-breed; scope-group subtotals (who
   wins each group all-in); coverage gaps (who didn't bid what — a low total may
   just be missing scope); partial bids; and outliers. Then:
   - **Read out every warning** — each `spread.condition_warnings` entry
     (`possible_scope_fold`: a no-bid next to others' bids with no tag explaining
     it; `unknown_acceptance`: a winning vendor whose flag is unverified;
     `unresolved_group`: a group whose tagged items match nothing in this package)
     AND each scope group's `warnings` (groups merged because they share pricing
     items; unresolved item keys). None of these is cosmetic — each one means a
     number on the board may not mean what it appears to.
   - **Never present a suppressed or annotated best-of-breed as an award target:**
     "NOT OBTAINABLE as shown" / "suppressed" means the winning vendors forbid
     separate acceptance — quote the mix only as a theoretical floor, and point at
     the obtainable total (or obtainable best mix) instead.
   Recommend nothing is changed here — note that applying the chosen prices is the
   next skill.

## Notes
- Consult the active org profile's `house_rules` (`estimating_tools.profiles.load()`,
  the `house_rules` section) and apply them when reading the spread — surfacing which
  rule was applied whenever quote math is adjusted or a vendor's stated number is set
  aside (e.g. "unit price governs: carried $160 × 51 pay qty = $8,160, vendor stated
  $13,440").
- Best-per-item ranks on **unit_price** (the fair per-unit rate), so a vendor who
  bids a low rate on only part of an item still shows as the best rate but is flagged
  partial with low coverage — read totals alongside coverage.
- Scope folds invert per-item comparisons: a vendor who folds one item's scope into
  another shows a higher rate on the carrying item (and no bid on the folded one)
  while being cheapest all-in. Tagged conditions (step 3) fix this with group
  subtotals; folded coverage counts toward a vendor's full-package coverage. The
  post-pass warns on likely untagged folds but never auto-normalizes — go back to
  the quote document and record the condition (`~/.estimating/bin/est-quotespace condition`) rather
  than guessing.
- No-bid and excluded items are coverage gaps, never counted as $0.
- Read-only: no quote/estimate/allocation is modified. Awarding/applying is a
  separate skill.
- To award the chosen quotes — post them to the estimate as subcontractor
  allocations and roll up the estimate package — use the `apply-quotes` skill (it
  confirms before writing).
- For ungrouped per-bid-item quotes (lump sums attached directly to bid items, not to
  a work package), use the `compare-item-quotes` skill instead.
- The field mapping is deterministic (`estimating_tools.spreads`); the judgment is
  resolving the package and reading the comparison.
