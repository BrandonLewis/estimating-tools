---
name: build-heavybook-workbook
description: Build the HeavyBook estimate workbook for a BidSheet.ai estimate — an outlined Cost Report with live formulas that match BidSheet.ai to the cent, plus Bid Form, Recap, Crews, Rates, Schedule, Checks and Flat sheets — from the estimate's workbook payload, fetched with est-estimate fetch. Read-only against BidSheet.ai; writes a local .xlsx. Use for "HeavyBook workbook", "estimate workbook for estimate N", "export the estimate to Excel (HeavyBook)". For a spec-driven fieldbook workbook use build-estimate-workbook instead.
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

# Build the HeavyBook estimate workbook

The HeavyBook workbook is a second estimate workbook alongside fieldbook. It is
built straight from the BidSheet.ai estimate (not from a spec YAML), and every
cost figure is a live Excel formula that reproduces BidSheet.ai's own rule. Its
Checks sheet compares each figure with BidSheet.ai's and reads 0 differing rows
on a fresh build, unless BidSheet.ai's stored totals or a step's shifts stamp
are stale -- those show as DIFF by design (re-pricing or re-stamping the
estimate in BidSheet.ai and re-exporting clears them).

## Workflow

1. **Resolve the estimate.** Get the `estimate_id` from the user, or from
   `list_estimates` for their project.
2. **Fetch the payload** with the estimator's token, to a file you never open:
   `~/.estimating/bin/est-estimate fetch <estimate_id> -o <estimate>.workbook.json`
   (`--items 12,13` for one page; the payload is stamped as a page of those
   items, and a book built from it stays that page -- applying edits to it
   patches it from a fetch of the same items; a long `--items` list is fine,
   the fetch pages itself and merges the pages into one file). Then build:
   `~/.estimating/bin/est-estimate build --pack heavybook <estimate>.workbook.json -o <estimate>.xlsx`.
   `~/.estimating/bin/est-estimate heavybook build` is the same builder with the style options.
   To rebuild a book the estimator has edited, write to a new file name
   (`-o <estimate>.rebuilt.xlsx`), never over the edited book.
   **Once per machine:** if the fetch is refused (exit 2) with "no BidSheet.ai token stored", ask
   the estimator to run `~/.estimating/bin/est-estimate login` themselves (it
   prompts for the token; you never see it), then fetch again.
   For a large estimate (more than ~50 items) fetch in pages of ~50 item ids
   (`list_estimate_items` gives the ids and the total count), each to its own
   file: `<estimate>.workbook.p1.json`, `.p2.json`, ... Never open or edit
   the JSON. Build from the page files with
   `~/.estimating/bin/est-estimate build --pack heavybook <estimate>.workbook.p1.json <estimate>.workbook.p2.json [...] -o <estimate>.xlsx`
   (`heavybook build` takes the same page files; it is the alias),
   passing **every** page file, in any order. A missing page leaves its items
   out of the book. If the estimate or a row changed between page fetches the build is refused ("re-fetch") -- fetch
   every page again and rebuild.
   **Completeness check (paged):** the Bid Form and the Recap list every item
   in the book, one row each. Confirm the Recap's item count equals the total
   from `list_estimate_items`; if it is short, a page is missing -- fetch the
   missing item ids and rebuild with every page.
3. **Report.** Tell the user the output path and which sheets it holds, and
   say that the build stored cached values with its built-in evaluator, so
   the book shows numbers in Protected View; pass on any line naming formulas
   left uncached (those cells appear only once the estimator clicks **Enable
   Editing**). `--recalc excel` additionally has Excel recalculate the book
   (for functions the built-in evaluator does not cover) and prints one
   `RECALC:` line to pass on; by default there is none. Open
   questions for them, if any: the Checks sheet lists BidSheet.ai's own warnings
   (missing rates, broken links), and the Schedule sheet is empty when the
   estimate has no schedule start in BidSheet.ai.

## Styling

An organization can restyle the book with a style pack directory holding
`tokens.yaml` and/or `sheets.yaml` (partial files merge over the bundled
style): pass `--style DIR` (to `build --pack heavybook` or `heavybook build`, the same
builder), or set `estimating.heavycivil_style` in the org
profile. Structure (columns, hidden id/`v` cells) cannot be restyled.

## What the estimator can edit

Inputs are tinted: resource lines, production, shifts, counts and crew members
on the Cost Report and Crews sheets; markup, item scope and bid price
overrides on the Bid Form. Totals follow live. To send the edits back to
BidSheet.ai, use the `apply-heavybook-workbook` skill: it runs `~/.estimating/bin/est-estimate apply`, which
reads the book, dry-runs the change set, and applies it only on the estimator's yes.

The book also carries a hidden `_templates` sheet: the prototype rows Estimate
Navigator, the Excel add-in, copies when it inserts a new activity, resource
line, step or crew member. Leave it hidden and unedited; read-back never reads it.
