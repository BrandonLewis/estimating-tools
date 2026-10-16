---
name: import-historicals
description: Import pricing observations into BidSheet.ai's historical bank — agency bid tabs (est-hist parse → awarded/competitor_bid records) and own estimates (est-hist from-estimate → estimated/bid records with cost-code breakdowns) — via preview → confirm → bulk-create, keyed by (agency, bid_item_code); idempotent by (project_ref, outcome). Via the BidSheet.ai MCP. Writes.
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Import a Bid Tab into the Historical Pricing Bank

Use this when an agency has published bid results (a PDF, Excel, or CSV award
tabulation) and the org wants those bidders' unit prices in BidSheet.ai's
historical bank for future pricing consultations (`mcp__bidmanager__price_bid_item`,
`suggest`-style lookups). The `est-hist` CLI does the deterministic parsing
and fan-out; the judgment is in reviewing QC flags, filling metadata gaps,
and confirming the write.

## Inputs
- The agency's bid tab (PDF/Excel/CSV award tabulation).
- If the project is already intaken, its `project_ref` (used for the
  idempotence check and to key every record).

## Workflow
1. **Locate/register the tab document.** In a project context (an intaken
   bid working dir), the tab normally lives under that project's `Reference/`
   folder — use it from there. Outside a project context, any local path to
   the file works.
2. **Parse:** `est-hist parse <file>` → writes `<file>.tab.json` and prints a
   QC summary to stdout (item/bidder counts, parse-warning count, total-check
   flag count). Read every line — surface EVERY parse warning and every
   total-check flag to the user before going further. A flagged bidder column
   ("bidder columns not in expected Unit Price/Amount pairs; prices may be
   misattributed") usually means the source table's columns were mis-detected
   during extraction (common with PDF table extraction) — fix the source file
   or hand-prepare a normalized CSV in the expected layout: metadata rows
   `Agency:`/`Contract:`/`Project:`/`Bid Date:`/`Region:`, then a header row
   `Item No,Item Code,Description,Quantity,Unit` followed by per-bidder
   `<Name> Unit Price,<Name> Amount` column pairs, and an optional `TOTAL`
   row. Re-run `est-hist parse` on the corrected file.
3. **Fill metadata gaps.** If the tab lacked `Agency:`/`Project:`/
   `Bid Date:`/`Region:` metadata rows (or `est-hist parse` left those fields
   blank in `<file>.tab.json`), ask the user for them and edit the JSON's
   top-level `agency` / `project_ref` / `bid_date` / `region` fields directly
   before fan-out — `to_records()` copies these onto every record it emits,
   so a gap here means every record in this import is missing that field.
4. **Fan out:** `est-hist records <file>.tab.json` → `<file>.records.jsonl`
   (one line per item × bidder that has a price; status printed to stderr).
   Each line is a ready `mcp__bidmanager__create_historical_record` kwargs payload — the low
   bidder's rows are `outcome: "awarded"`, every other bidder's rows are
   `outcome: "competitor_bid"`. Report the record count to the user
   (items × bidders, minus any missing prices).
5. **Idempotence check.** Before writing anything,
   `mcp__bidmanager__list_historical_records(project_ref=<project_ref>, limit=1)`. If any
   records already exist for this `project_ref`, STOP and confirm with the
   user before continuing — re-importing the same tab duplicates
   observations in the historical bank. Default is to skip the import when
   records already exist; only proceed if the user explicitly wants a
   re-import (e.g. a corrected tab).
6. **Preview and get explicit confirmation.** Show the user, before any
   write:
   - the tab header (agency, contract, project_ref, bid date, region),
   - the bidder list with each bidder's total bid and rank (low bidder =
     awarded),
   - the total record count about to be created,
   - 3 sample records from `<file>.records.jsonl` (pick across different
     items/bidders, not just the first 3 lines).
   Do not call `mcp__bidmanager__bulk_create_historical_records` until the user confirms.
7. **Write in batches.** `mcp__bidmanager__bulk_create_historical_records` with the parsed
   JSONL records, batched at **≤50 records per call**. After each batch,
   track how many were created vs. the batch size; surface any per-row
   errors (e.g. a rejected `outcome`, a malformed `bid_item_code`) to the
   user rather than silently dropping them. Report the total created count
   against the expected count from step 4.
8. **Verify:** `mcp__bidmanager__list_historical_records(project_ref=<project_ref>)` and
   confirm its count matches what step 7 reported created. If it doesn't,
   report the discrepancy — do not assume the write succeeded.

## Own-estimate deposits (`from-estimate` mode)

Use this for the deposit hooks: after pricing an estimate deposit
`outcome: "estimated"` records; after submitting the bid deposit
`outcome: "bid"` records. Both come from the same `CanonicalEstimate`
(`*.canonical.json` from `est-import`).

1. **Resolve the code map.** Records are keyed `(agency, bid_item_code)` —
   the agency's code, not the org cost code that `item_code` usually holds.
   Reuse the mappings confirmed during `price-estimate`'s historical
   consultation when they exist; otherwise confirm them now (propose via
   `mcp__bidmanager__search_bid_items_by_code` / `mcp__bidmanager__search_bid_item_templates`, estimator
   confirms). Write them to a JSON file:
   `{"<schedule>::<item_number>": "<bid_item_code>", ...}` (plain
   `"<item_number>"` keys work when numbers don't repeat across schedules).
   Only if the import's `item_code` column already holds agency codes may
   `--code-map` be omitted — `from-estimate` falls back to `item_code`.
2. **Fan out:**
   `est-hist from-estimate <file>.canonical.json --outcome estimated|bid
   --agency <slug> --region <region> --bidder "<our org name>"
   --code-map codes.json` → `<file>.records.jsonl` (status on stderr).
   `estimated` puts the price in `unit_cost_estimated`; `bid` puts it in
   `unit_price_bid`; cost-code breakdowns from the import ride along.
3. **Idempotence check — keyed `(project_ref, outcome)`.**
   `mcp__bidmanager__list_historical_records(project_ref=<ref>)` and filter the result by
   `outcome`: the same project legitimately accumulates `estimated` then
   `bid` records — only a match on BOTH is a re-import. On a match, STOP
   and confirm with the user (default skip), same as the tab path.
4. **Preview, confirm, write, verify** exactly as steps 6–8 of the tab
   workflow above (same ≤50-record batches, same verification count).

## Results day

When the agency publishes results for a project we bid:

1. Import the results tab via the tab workflow above — that deposits the
   `awarded` / `competitor_bid` observations.
2. ALSO record each competitor's total through BidSheet.ai's native
   `mcp__bidmanager__record_competitor_bid` (project-level bid-results surface — feeds
   `mcp__bidmanager__analyze_bid_competitiveness` / `mcp__bidmanager__get_bid_result`; the historicals bank
   and the results surface are separate stores, fill both). The tab's
   bidder list (name, total, rank) has everything the call needs.
3. If our own `bid` records weren't deposited at submission time, deposit
   them now (`from-estimate` mode, `--outcome bid`).

## Notes
- Never call `mcp__bidmanager__bulk_create_historical_records` (or
  `mcp__bidmanager__create_historical_record`) without the explicit confirmation in step 6 —
  this skill writes observational history, not draft state; there is no
  "preview then just do it" shortcut.
- `bid_item_code` is imported exactly as published — a string, leading
  zeros preserved (e.g. `"070030"`), never coerced to a number.
- `agency` is a lowercase slug (`caltrans`, not `Caltrans` or `CalTrans`);
  `est-hist parse` already lowercases it when it reads an `Agency:` row —
  keep that convention when filling gaps by hand in step 3.
- The pair-shape warning from step 2 ("bidder columns not in expected Unit
  Price/Amount pairs; prices may be misattributed") is tab-wide — it names no
  bidder, so there is no single bidder to exclude. The default is to fix the
  source file or hand-prepare the normalized CSV (step 2) and re-parse; only
  proceed with the flagged parse if the user reviews the columns and directs
  you to. Per-bidder exclusion applies only to QC flags that DO name a bidder
  — the total-mismatch and no-extensions cross-check flags: those bidders'
  records default to EXCLUDED — filter them out of `<file>.records.jsonl`
  (by the `bidder` field) before step 7 — unless the user reviews the flag
  and directs you to include them anyway.
- Idempotence is keyed on `project_ref`, not on individual records — importing
  the same bid tab twice under the same `project_ref` is what step 5 guards
  against. Two different tabs that happen to share `bid_item_code`s (e.g. the
  same standard item across two different lettings) are unrelated imports
  with different `project_ref`s and both proceed normally.
- The tab path writes `awarded` / `competitor_bid` observations; the
  `from-estimate` path writes `estimated` / `bid`. `actualized`
  observations (as-built job costs) come from a later workflow, not this
  skill.
