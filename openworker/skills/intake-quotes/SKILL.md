---
name: intake-quotes
description: Turn quote documents saved to the bid's inbox folder into vendor columns on the Sub <package> sheets. Scans the inbox (PDF, Word, Excel, email, images), has you read each new document against the spec's work packages, and writes the spec's quote files with `est-quotes`. Run it once after saving quotes or on an interval through bid day. Local files only; never calls BidManager.
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Intake Quotes

Quotes that arrive as documents (a PDF on letterhead, an email, a spreadsheet,
a photo of a fax) are saved in the bid's inbox folder; this skill turns them
into the quote files the spec's `work_packages` read, so each vendor shows up
as a column on its `Sub <package>` sheet. `est-quotes` does the deterministic
file work (scan, text recovery, batch file, import, state); you do the
reading in between.

## When

- Bid day, on an interval: `/loop 5m intake-quotes`, or a scheduled wake-up.
- Once, after the estimator has saved a handful of quotes to the inbox.
- Never calls BidManager. Pushing the quote files there is a separate step
  (piece 2).

The inbox defaults to `<spec dir>/../Subquotes/inbox`, or the spec's
`work_packages_inbox_dir`; `--inbox DIR` on `run` overrides it. Nothing in the
inbox is moved, renamed or deleted.

## Each tick

1. **Run the tick.** `est-quotes run <spec>` prints one line:
   - `nothing new`: stop. Nothing to do this tick.
   - `nothing to extract`: new files arrived but none is readable yet. Run
     `est-quotes report <spec>`, and tell the estimator which
     documents are unreadable and why (a bad scan, an `.xls`, an `.msg`).
   - otherwise the line is the path of the batch file. Go on.

   Exit 2 (the reason is on stderr) means the spec cannot be read, has no
   `work_packages`, its work packages do not build, or the inbox does not
   exist. Report the reason; do not retry blind. `--limit N` caps the
   documents in one batch. `run` may also print, on stderr,
   `unsupported: …`, `N vision document(s) not rendered`,
   `held <sha8> <file>: <reason>` or `error <sha8> <file>: <reason>` (a
   document this tick could not take, such as an `.msg` or an `.xls`), and
   `N document(s) offered before and still open` (every document in the batch
   was in an earlier batch and is still unread). Pass every such line on to
   the estimator (nothing is silently skipped).
2. **Read the batch file.** Its `instructions` are the extraction rules; follow
   them. `packages` lists each package's name, scope, condition keys and
   package lines (schedule, item, line name, unit, qty). `docs` lists the
   documents, each with `sha256`, `file_name`, and either `text_path` (read the
   text) or `image_paths` (read the images). Read every document, then write
   the results file to `<quotes dir>/_intake/results/<batch file name>`
   (the quotes dir is the spec's `work_packages_quotes_dir`, default `quotes`,
   beside the spec; the batch file itself sits in `<quotes dir>/_intake/batches/`,
   so the results file goes in the sibling `results/` folder under the same
   name), following the contract in `instructions`:
   - one result per document per package it prices;
   - transcribe, never compute;
   - a document you got to but cannot read is a result with
     `doc_type: "unreadable"` and a `reason` (it lands in the report and is
     not offered again); omit a document only when you did not get to it in
     this batch (it stays open, nothing is invented);
   - put a priced line that fits no package line in `extras`.
3. **Import.** Run the dry run first and read its report:
   `est-quotes import <spec> <results file>`. Then apply it
   with `--write`:
   `est-quotes import <spec> <results file> --write`.
   Exit 1 means the results file was refused: every error is on stderr, so fix
   the file and import again. Show the report verbatim in a fenced block. Its
   lines are `written`, `revised`, `unchanged`, `held`, `not_quote`, `review`
   and `refused`, then a summary.
4. **Rebuild the workbook** so the new vendor columns show: run the build line in
   the bid's `Estimate/quotes/README.md` (section "Bid-day chain") exactly as
   written there, from the bid directory; it has the form
   `est-estimate build Estimate/<bid>.estimate.yaml -o Estimate/<bid>-fieldbook.xlsx --format <org profile>/format`,
   then the recalc step the README names. An estimator working in BidManager runs `sync-work-packages`
   instead (piece 2, when it exists).
5. **Explain every `held` entry**: why it was held and what unblocks it.
   - A package the spec lacks: add the package to the spec, then
     `est-quotes requeue <spec> --held` (or `requeue <spec>
     SHA...` with 8+ characters of each sha256) and run the next tick.
   - An unreadable document: a re-saved file in the inbox. A `.msg` is saved
     again as `.eml` (or its attachments saved on their own).
   - `previous quote would remain on file`: a correction changed the vendor, package,
     or document classification. Reconcile the named existing quote with the
     estimator before re-importing; the tool keeps it intact and writes no
     replacement until that conflict is resolved.
   - A document already extracted is `unchanged` on re-import; to redo it,
     `requeue <spec> SHA` first.
   - `the file holds parts from other documents; requeue them too: …`: the
     quote file is the union of several documents; requeue the named ones as
     well and import all of them again.

## Rules

- A price is transcribed as printed. Never add, convert or round.
- A line that fits no package line is an extra, not a guess.
- A revision from a carried vendor appears in the import report as
  `<file>: <vendor> revised <package> (carried): old → new` (for example
  `dirt-movers--hauling.json: Dirt Movers revised Hauling (carried): 7,590.00 → 6,900.00`). Read every such
  line out to the estimator in plain words; a carried price changed.
- A document you cannot read is returned as `unreadable` with a reason; omit
  a document only when you did not get to it in this batch.
- To redo an extracted document, `est-quotes requeue <spec> SHA`
  and re-import; the new extraction replaces that document's contribution to
  its quote file (reported as `revised`). A corrected file re-saved in the
  inbox does the same on its next import.
- Nothing in the inbox is moved or renamed, and `est-quotes` never calls
  BidManager.

## Notes

- All state lives in the quotes dir's `_intake/`. `inventory.json` is the one
  file worth committing in a bid repo; the rest is derivable.
- `est-quotes batch <spec> [--limit N] [-o FILE]
  [--include-held]` and `scan` / `text` are the `run` steps taken singly;
  `report <spec> [--json]` shows the inventory.
- For quotes already in BidManager, see `capture-quote`; for the package setup
  itself, `manage-work-packages`.
