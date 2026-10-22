---
name: build-heavycivil-workbook
description: Build the HeavyCivil estimate workbook for a BidSheet.ai estimate — an outlined Cost Report with live formulas that match BidSheet.ai to the cent, plus Bid Form, Recap, Crews, Rates, Schedule, Checks and Flat sheets — from the estimate's mcp__bidmanager__get_estimate_workbook data over the BidSheet.ai MCP. Read-only against BidSheet.ai; writes a local .xlsx. Use for "HeavyCivil workbook", "estimate workbook for estimate N", "export the estimate to Excel (HeavyCivil)". For a spec-driven fieldbook workbook use build-estimate-workbook instead.
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Build the HeavyCivil estimate workbook

The HeavyCivil workbook is a second estimate workbook alongside fieldbook. It is
built straight from the BidSheet.ai estimate (not from a spec YAML), and every
cost figure is a live Excel formula that reproduces BidSheet.ai's own rule. Its
Checks sheet compares each figure with BidSheet.ai's and reads 0 differing rows
on a fresh build, unless BidSheet.ai's stored totals or a step's shifts stamp
are stale -- those show as DIFF by design (re-pricing or re-stamping the
estimate in BidSheet.ai and re-exporting clears them).

## Workflow

1. **Resolve the estimate.** Get the `estimate_id` from the user, or from
   `mcp__bidmanager__list_estimates` for their project.
2. **Size it.** `mcp__bidmanager__list_estimate_items(estimate_id)` -- page through it to the
   end and note the total item count. Up to ~50 items: fetch once. More:
   fetch in pages of ~50 item ids, covering every item id.
3. **Fetch.** `mcp__bidmanager__get_estimate_workbook(estimate_id)` — or per page
   `mcp__bidmanager__get_estimate_workbook(estimate_id, item_ids=[...])`. Save each response,
   unchanged, as JSON: `<estimate>.workbook.json`, or `<estimate>.workbook.p1.json`,
   `.p2.json`, ... for pages. Do not edit the JSON.
4. **Build.** Pass `--host <host>`: the BidSheet.ai host the MCP server
   points at (default `www.bidsheet.ai`). It is stamped into the workbook so
   a later read-back sends edits to the same BidSheet.ai the data came from.
   One payload:
   `est-estimate heavycivil build <estimate>.workbook.json --host <host> [-o out.xlsx] [--style DIR]`.
   Paged: pass **every** page file, in any order --
   `est-estimate heavycivil build <estimate>.workbook.p1.json <estimate>.workbook.p2.json [...] --host <host>`.
   A missing page leaves its items out of the book. If the estimate or a row
   changed between page fetches the build is refused ("re-fetch") -- fetch
   every page again and rebuild.
   **Completeness check (paged):** the Bid Form and the Recap list every item
   in the book, one row each. Confirm the Recap's item count equals the total
   from `mcp__bidmanager__list_estimate_items`; if it is short, a page is missing -- fetch the
   missing item ids and rebuild with every page.
5. **Report.** Tell the user the output path and which sheets it holds. Open
   questions for them, if any: the Checks sheet lists BidSheet.ai's own warnings
   (missing rates, broken links), and the Schedule sheet is empty when the
   estimate has no schedule start in BidSheet.ai.

## Styling

An organization can restyle the book with a style pack directory holding
`tokens.yaml` and/or `sheets.yaml` (partial files merge over the bundled
style): pass `--style DIR`, or set `estimating.heavycivil_style` in the org
profile. Structure (columns, hidden id/`v` cells) cannot be restyled.

## What the estimator can edit

Inputs are tinted: resource lines, production, shifts, counts and crew members
on the Cost Report and Crews sheets; markup, item scope and bid price
overrides on the Bid Form. Totals follow live. Edits are not yet sent back to
BidSheet.ai by this skill — say so if asked.
