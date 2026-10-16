---
name: compare-item-quotes
description: Level a project's ungrouped per-bid-item vendor quotes into a side-by-side quote board — best price per item, per-vendor totals + coverage, gaps, outliers. Read-only, via the BidSheet.ai MCP.
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

# Compare Per-Item Vendor Quotes (Quote Board)

Use this to level the simple per-bid-item quotes on a project (lump-sum vendor prices
attached directly to bid items, NOT to a work package) into a side-by-side board.
**Read-only:** it reads and presents; it makes NO changes. For quotes captured on a
work package, use `compare-quotes` instead. Requires the BidSheet.ai MCP.

## Inputs
- The target `project_id`.

## Workflow
1. **Fetch the bid items:** `list_bid_items(project_id)` → the project's items (each
   `id` = `project_bid_item_id`, with `item_code`, `item_number`, `schedule_name`,
   `description`, `unit`, full `quantity`).
2. **Fetch the per-item quotes:** for each bid item, `list_quotes(project_bid_item_id=…)`
   → its quotes. Drop any with `status == "rejected"`. Collect the kept quotes into one
   flat list; note which items have ≥1 quote.
3. **Build the board:** `estimating_tools.spreads.build_item_spread(bid_items, quotes)`
   → a `Spread` (rows = quoted items, columns = vendors; best-per-item, per-vendor
   totals + coverage, best-of-breed, outliers). It dedupes to the most recent quote
   per (item, vendor) and handles items with no/zero quantity.
4. **Present it:** `estimating_tools.spreads.render_spread(spread)` → show the quote
   board, or hand back the structured `Spread` when only the data is wanted.
5. **Narrate the takeaways:** best per item, per-vendor totals and coverage (who quoted
   how many items), gaps (items with no quote), and outliers — making no changes.

## Notes
- Per-item quotes are lump sums; the board shows an implied unit rate (amount ÷ item
  quantity) alongside the real quantity, and ranks on it (equivalent to lowest amount).
- The most recent quote per (item, vendor) wins (a revision supersedes an older one).
- Read-only: no quote/estimate is modified. Awarding/accepting a per-item quote is a
  separate path. For work-package quotes (with line items), use `compare-quotes`.
- DBE status carries onto the board (DBE vendors are starred `*` in the column
  headers) — call it out in the narration; it is decision-relevant on fed-aid work.
- **Scope-fold annotation (annotation only):** if the quote-conditions journal
  (`<bid working dir>/Subquotes/quote-conditions.jsonl`, written by `capture-quote`)
  tags scope folds touching any quoted item, mark those items **not comparable** in
  the narration and make NO best-price claim for them — a vendor who folded that
  scope elsewhere makes the per-item prices describe different scopes. No group math
  on the per-item board; full scope-group treatment (subtotals, obtainable totals)
  is `compare-quotes`' job on work-package quotes.
- The reshape is deterministic (`estimating_tools.spreads.build_item_spread`); the
  judgment is reading the board.
