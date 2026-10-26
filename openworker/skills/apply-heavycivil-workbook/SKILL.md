---
name: apply-heavycivil-workbook
description: Send an estimator's edits in a HeavyCivil estimate workbook back to BidSheet.ai — read the edited .xlsx into a change set (edited inputs, copied, pasted and typed rows, cut-and-pasted activities and lines, deletes), dry-run it with mcp__bidmanager__apply_estimate_workbook_changes, show the plan, and apply it only on the estimator's yes, then rebuild the book. Writes to BidSheet.ai. Use for "apply my workbook edits", "send the HeavyCivil workbook back", "push the edited estimate workbook". To build the book in the first place use build-heavycivil-workbook.
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Apply HeavyCivil workbook edits to BidSheet.ai

A HeavyCivil book (from the `build-heavycivil-workbook` skill) carries the
estimate it was built from. Reading it back compares the edited book with that
baseline, so only what the estimator changed is sent, and a row someone else
changed in BidSheet.ai since the export is caught as a conflict on that row
alone. **This skill writes to BidSheet.ai**: nothing is applied without a dry
run the estimator has seen and an explicit yes.

An edit in one estimate never reprices another: the change set touches only
this estimate's rows; a library crew edit is copied into this estimate first;
library rates are never written.

## Workflow

1. **Read the book.**
   `est-estimate heavycivil read <book>.xlsx [-o <book>.changes.json]`
   - Exit 0 prints one line per change (each naming its book row, except a
     delete's line, whose row is gone), then `Notes:`, and writes the change
     set JSON (`estimate_id`, `estimate_v`, `ops`, `rows`, `summary`, `notes`;
     default `<book>.changes.json` beside the book). "no changes" (an empty
     `ops`) means there is nothing to send — show any notes printed under it
     (say, an ignored Bid Form row), then stop.
   - Exit 2 is a **read refusal**: every problem is printed, naming its sheet,
     row and column where it applies, and nothing is written. Show the whole
     list to the estimator and stop; they fix the book (or rebuild it) and you
     run the read again. See "Read refusals" below for what each one means.
     Exit 2 also comes from an `-o` that names the workbook itself (give the
     change set its own file name) and from a change set that could not be
     written (the old file at that path is left as it was).
2. **Dry run.** Call `mcp__bidmanager__apply_estimate_workbook_changes(estimate_id, ops,
   dry_run=true)` with the JSON's `estimate_id` and `ops`, unchanged. Never
   edit, reorder or drop ops: `new:` tokens and later ops depend on earlier
   ones.
3. **Show the plan.** In a short table or list:
   - the `summary` lines (each names its book row; a delete's names only
     its sheet, since the row is gone);
   - **deletes and what they cascade to** (the plan's `deleted[].cascade`:
     child activities, lines, steps, element and item links) — a deleted
     activity takes its whole subtree;
   - **moves** (`activity.move` ops: an activity and its subtree moving to
     another item, or out from under its parent);
   - **crew copies** (the plan's `warnings` and `created["crew:<id>"]`): a
     library crew edit makes an estimate-local copy; the library crew and
     other estimates are untouched;
   - every one of the change set's `notes` (see "Notes" below) — they say
     what the book does not show yet and what BidSheet.ai will do beyond the
     edit;
   - **totals before and after** (the plan's `totals`).

   Then ask the estimator to confirm.
4. **Apply on a yes.** Only when the estimator explicitly confirms, call
   `mcp__bidmanager__apply_estimate_workbook_changes(estimate_id, ops, dry_run=false)` with
   the same ops. If anything changed in BidSheet.ai since the book was
   built, the apply refuses as a conflict and nothing is applied — handle it
   as under "Errors from BidSheet.ai" (rebuild the book, redo the edit). A
   second dry run does not cure it: the row versions come from the book.
   Anything short of a yes (a question, an edit request) is not a yes: they
   change the book, and you read it again from step 1.
5. **Rebuild the book.** The old book's row versions are stale after an
   apply, and new rows only reach the Flat and Checks sheets in a rebuilt
   book. Rebuild with the `build-heavycivil-workbook` skill, writing the new
   book beside the old one (a new name, e.g. `<estimate>.workbook.2.xlsx`),
   and tell the estimator to continue in the new book — never in the old one.

## Read refusals (exit 2)

Each line reads `<sheet> row <r> column <c>: <what> -- <cure>`, naming the
sheet, row and column where it applies (a deleted row has no row, a
whole-row problem no column). Relay the cure; the common ones:

- **A value typed on a marker row** (the STEPS / START / END rows of an
  activity, a crew's end row): insert a row above the marker and type there.
- **A marker row deleted or moved**: undo it, or rebuild the book.
- **"holds percent points -- type 15, not 15%"**: a percent cell (markup,
  burden) was typed with a `%`; type the number of points.
- **A formula overwritten or cleared** ("held a formula and now holds a
  value"): undo the edit, or copy the formula back from a row of the same
  kind. **#REF!** ("a formula here lost its reference"): a row a formula
  pointed at was deleted — undo the delete, or rebuild.
- **Any Rates sheet edit** (a rate changed, added, deleted or reordered):
  library rates are read-only — set the member's Rate override on the Crews
  sheet instead, and undo the Rates edit.
- **An export value edited** ("is read-only in the workbook -- change it in
  BidSheet.ai"): a crew's hours/shift or crew factor (Crews), an item's bid
  quantity (Bid Form) or an element's derived quantity (Cost Report). The
  book's formulas read them but no apply op writes them — undo the edit and
  change the figure in BidSheet.ai, then rebuild.
- **A linked activity copied with one copy edited**: an activity tied to
  elements or spreads was copied and the copies now differ, so BidSheet.ai
  cannot tell which row keeps the links — undo the edit, apply the copy,
  rebuild, then edit.
- **An activity left under a copy of its parent** ("now sits under a copy of
  its parent"): copy the parent together with its children, or undo.
- **A renamed or missing tab**: rename it back, or rebuild.
- Also: a coded cell with an unknown value (pick one from its drop-down); a
  row outside any block a new row can go in (a resource goes between an
  activity's START and END, a step between STEPS and START, a member inside a
  crew's rows); a row of a kind that can't be added, copied or deleted in the
  book (items, element quantities, crews, sections — undo it); a structure
  activity added, deleted or moved (structure activities are added, deleted
  and moved in the takeoff, not the workbook; edits to their inputs are
  sent); an allocation-posted line edited, moved or deleted (change it in
  BidSheet.ai); a first step added to an unstepped activity (add it in
  BidSheet.ai, then rebuild); a book of another layout or with no baseline
  (rebuild).

## Notes (exit 0)

Notes do not stop the read; show each one with the plan.

- **Rows not priced live**: a copied or typed activity's share of its item
  total, a typed line's cost, a typed member's rate in its crew rate — they
  show after the apply and a rebuild. Copied, pasted and typed lines that do
  price live in the book still reach the Flat sheet and the Checks rows only
  after the apply and a rebuild.
- **Linked pastes**: a line pasted in from another workbook keeps its rate
  link and is priced at today's library rate, not the unit cost the book
  showed; the note names both, and the dry run's totals use the library rate.
- **A step's cost code dropped**: a cut or copied step keeps its cost code
  only when it fits under the destination activity's code; otherwise it
  lands without one — set it in BidSheet.ai after the apply.
- **A lost multiplier**: a child activity that becomes a root (moved, cut away
  from its parent, or copied out from under it) stops being multiplied by its
  former parents' count; the note names the factor.
- **Library crew copied**: editing a library crew's members makes
  BidSheet.ai copy that crew into this estimate and edit the copy.
- **Ignored Bid Form rows**: a row typed among the bid items has no kind and
  is not read — bid items are added in BidSheet.ai.

## Errors from BidSheet.ai

Map every `op_index` through the JSON's `rows` (each entry is `{op_index,
sheet, row}`; `row` is null for a deleted row, and one op can have more than
one entry) to name the book row:

- **Conflicts** (`{"error", "conflicts": [{op_index, ref, kind}]}`): for each,
  "<sheet> row <row> changed in BidSheet.ai since export — rebuild the book
  and redo the edit". Nothing was applied.
- **A refused op** (`{"error", "op_index"}`): BidSheet.ai's message with the
  op's book row. Nothing was applied. A pasted line whose rate link this
  estimate cannot use (another organization's library, or a retired rate) is
  refused this way: tell the estimator to clear that line's hidden rate link
  (column AE) or retype the line, then read the book again. An `op_index`
  of null means BidSheet.ai refused the change set as a whole: there is no
  book row to name — relay its message.
- **Access** (`{"error"}` with no `op_index`): the estimate is missing, not
  theirs, or not editable (a viewer, or a locked estimate).

## What read-back sends, and what it never does

Sent: markup; item quantity override, unit price, scope and bid price
override; element quantity overrides; activity, step and resource inputs;
crew member rosters; new steps, lines and members; copied activities (with
their children); cut-and-pasted activities (moved to their new item) and lines
(moved to their new activity); deletes of activities, steps and lines.

Never: sections, bid totals, crew assignment (a copied activity only keeps
its source's crew and cost code), rate links on existing rows, codes, sort
order (crew members keep theirs; new members are appended), library rates, a
copied activity's element links or spread; creating or deleting items,
elements or crews; the export values the book's formulas read (a crew's
hours/shift and crew factor, an item's bid quantity, an element's derived
quantity) — an edit to one is refused.
