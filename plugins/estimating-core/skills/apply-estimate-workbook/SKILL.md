---
name: apply-estimate-workbook
description: Send an estimator's edits in an estimate workbook built from BidSheet.ai (HeavyBook, or any exchange pack's book) back to BidSheet.ai — run est-estimate read on the edited .xlsx and show its problems, run est-estimate apply to dry-run it and show the plan, and only on the estimator's yes run apply --commit, which applies and patches the book in place (edited inputs, rows inserted with Estimate Navigator, copied, pasted and typed rows, cut-and-pasted activities and lines, deletes). Also brings BidSheet.ai's changes into the book in place with est-estimate refresh (collisions are shown, never resolved). Writes to BidSheet.ai. Use for "apply my workbook edits", "send the workbook back", "push the edited estimate workbook", "send the HeavyBook workbook back", "refresh my workbook from BidSheet.ai", "pull BidSheet.ai changes into the workbook". To build the book in the first place use build-heavybook-workbook; a fieldbook spec workbook goes back through build-estimate-workbook's read-back and bm-sync.
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

# Apply estimate workbook edits to BidSheet.ai

A book built from BidSheet.ai (a HeavyBook book from `build-heavybook-workbook`,
or any exchange pack's) carries the estimate it was built from and the
declaration of its own layout. `est-estimate` finds the book's pack from its
stamp; you never name it. Reading the book back compares it with that
baseline, so only what the estimator changed is sent, and a row someone else
changed in BidSheet.ai since the export is caught as a conflict on that row
alone. **This skill writes to BidSheet.ai**: nothing is applied without a dry
run the estimator has seen and an explicit yes.

An edit in one estimate never reprices another: the change set touches only
this estimate's rows; a library crew edit is copied into this estimate first;
library rates are never written.

Estimate Navigator, the Excel add-in, inserts new activities, lines, steps and
crew members from the book's hidden prototype rows. Read-back recognises a new
row by its structure — a row carrying a kind and no id — so a prototype row
copied in by hand reads the same, and its position decides where it goes.

## The rule: you run the commands, never the payload

The change set, the payload and the plan move between the book and
BidSheet.ai through `est-estimate`, as the estimator, over their stored API
token. You run the commands and read what they print. You never open the
change set JSON (`<book>.changes.json`) or a payload JSON and never pass
their contents to an MCP tool: a payload that crosses you is transcribed,
and one mistyped `v` is a false conflict while one mistyped unit cost is a
silent misprice (contract rule 14).

## The exchange contract, in one screen

The full contract is `docs/estimate-exchange-contract.md` in the estimating-tools repo
(contract 1.0); where this summary is shorter or differs, the full contract governs.

- An op is `{op, ref, v, fields}`. `ref` is the row's integer id, `new:<token>` for a row
  created earlier in the set, or none for a `section.upsert` that creates. `v` is the row's
  fingerprint from the read: on every update and delete, never on a create or a `new:` row.
- The 23 ops: `estimate.update`; `item.update`; `section.upsert`, `section.delete`;
  `bid_totals.set`; `element.create`, `element.update`, `element.delete`,
  `element.set_quantity`; `activity.create`, `activity.update`, `activity.delete`,
  `activity.move`, `activity.set_links`, `activity.set_spread`, `activity.set_crew`;
  `step.add`, `step.update`, `step.delete`; `resource.create`, `resource.update`,
  `resource.delete`; `crew.update_members`.
- One transaction: any refusal refuses the whole set (the op index and why); a conflict
  lists every row whose `v` moved. The dry run is the default and rolls back; its totals are
  what the apply produces when nothing changes in between. At most 5,000 ops. A repeat of an
  apply with the same `request_id` and the same ops returns the stored plan with
  `replayed: true` for 24 hours.
- Position: a created activity or line carries the `sort_order` of the sibling it follows
  (one less than the first's when it goes first, 0 when its block has no existing row); where
  the siblings around it tie, the ones below are renumbered with `sort_order` updates (see
  "Renumbered rows"), and an allocation-posted line that would need renumbering refuses the
  read. An existing row moved within its block is not sent. A roster op's `rows` point at the
  member rows it names, a removed member as a null row, never the crew's header.

The rules every surface honours:

1. Never send a computed field.
2. `v` on every update and delete, never on a create; compare it, never compute it.
3. Conflict only on a row the user touched, or one renumbered to place a create: send ops
   for what changed and nothing else.
4. Library rates are read-only; a rate link is sent as `labor_rate_id`, `equipment_rate_id`
   or `material_cost_id`, never as a number.
5. A library crew's members are edited against its own id; BidSheet.ai copies the crew into
   the estimate.
6. Managed rows (`managed_by` set) are not written.
7. Activities move (`activity.move`); a step, line or member under another owner is a
   delete and a create.
8. A delete's cascade is BidSheet.ai's and is shown before applying.
9. The proof of price is the dry run's totals, shown before the apply.
10. A surface that cannot tell a user's edit from a server change does not guess.
11. A copied line keeps its rate link only while every input the book binds, bar its
    quantity, equals its source's.
12. Every apply carries a `request_id`; never retry blind.
13. A push never discards what the estimator typed: patch, never regenerate.
14. Payloads move over the bulk leg, through files; the agent does not transcribe.

## Workflow

0. **Once per machine.** If a command is refused (exit 2, "(nothing sent)")
   with "no BidSheet.ai token stored", "the stored BidSheet.ai token file is
   unreadable", or a message naming a host mismatch, ask the estimator to run
   `~/.estimating/bin/est-estimate login` themselves (add `--host` when the
   message names a host; it prompts for the token, you never see it), then run
   the command again. Nothing was sent, so this is never an unknown outcome and
   never needs `--request-id`.
1. **Read.** `~/.estimating/bin/est-estimate read <book>.xlsx`
   - Exit 0 prints `pack: <name> <version>`, the change summary (each line
     naming its book row; a delete's line has no row), the notes, and
     `WROTE: <book>.changes.json`. Leave that file alone. "no changes" means
     there is nothing to apply: stop.
   - Exit 2 is a **read refusal**, nothing written: show every problem as
     printed (see "Read refusals" below). The estimator fixes the book; run
     the read again.
2. **Dry run.** `~/.estimating/bin/est-estimate apply <book>.xlsx`
   - Exit 0 prints `dry run -- request <id>`, the change summary and notes
     again, then BidSheet.ai's plan: deletes and what they cascade to,
     warnings (crew copies among them), and totals before and after, ending
     with `Re-run with --commit to apply.`
   - Exit 2 is **refused locally, nothing sent**; the printed line says which:
     - A read refusal (problems listed): as in step 1.
     - No token, an unreadable token file, or another host: see step 0.
     - "this book was built from <host>; --host says <other> (nothing sent)":
       the host stamped in the book decides where the apply goes, and `--host`
       may only repeat it. Drop `--host` and run again. When the stamped host
       is not the stored token's, the refusal names it: the estimator runs
       `~/.estimating/bin/est-estimate login --host <stamped host>` first.
     - "no installed pack recognizes this book": the book was not built from
       BidSheet.ai by an exchange pack (or its stamp is gone); rebuild it.
     - "made by a newer version of the <pack> pack -- update the plugin", or
       "this book targets contract N": update the plugin (do not rebuild).
     - "the book's declaration cannot be read", "its stamp is damaged", or an
       estimate id that is not a number: rebuild the book.
     - "two packs claim this book": report it with `report-issue`; do not work
       around it.
   - Exit 3 is **BidSheet.ai's refusal or failure** (`apply failed: ...`): see
     "Errors from BidSheet.ai" below.
3. **Show the plan** to the estimator as printed, with the notes, and ask them
   to confirm. Anything short of a yes is not a yes: they change the book, and
   you run the read and the dry run again.
4. **Apply on a yes.** `~/.estimating/bin/est-estimate apply <book>.xlsx --commit`
   applies with a fresh request id, fetches the estimate, and patches the book
   in place: new rows get their ids and `v`, the baseline is replaced once the
   patched book has been read back clean, and nothing the estimator typed is
   touched. If the book is open in Excel (or read-only) the commit is refused
   before anything is sent (exit 2, "cannot open <book> for writing ... --
   close it or make it writable and retry (nothing sent)"): ask the estimator
   to close it, then run the commit again.
   - If the command reports an **unknown outcome** (no answer, or a server
     error, after the send), re-run with `--commit --request-id <id>` using the
     id it printed. A server with request-id support replays the stored result
     and nothing is created twice. Against an older server, look at the
     estimate in BidSheet.ai before resending.
   - If it prints `applied, but ...` or a `Not written:` list (both exit 3), the
     apply went through and part of the book could not be patched. Do **not**
     run `apply` again: the CLI ends with "The apply is done -- do not run
     apply on this book again; rebuild it from BidSheet.ai: est-estimate fetch
     ... -o ..., then est-estimate build --pack <pack> ... -o
     <book>.rebuilt.xlsx". Run those two commands as printed (through
     `~/.estimating/bin/est-estimate`): they keep a page a page (`--items`) and
     write a new file next to the book, never over the edited book. When "the
     book could not be patched" ends " -- close the workbook in Excel first",
     the estimator closes Excel and you run the printed rebuild; never
     re-apply.
   - A patch whose copy does not read back clean because someone changed the
     estimate in BidSheet.ai meanwhile takes their changes the way a refresh
     does (listed under `Notes:`) and is adopted. Only when it cannot does the
     book keep its old baseline, get its ids and `v`, and is marked stale: the
     CLI exits 3 with "the patched book would not read back clean (...) -- the
     apply is done; the book keeps its old baseline and is marked stale" and
     the rebuild advice. From then on every `read`, `apply` and `refresh` of
     that book refuses it until it is rebuilt; run the printed rebuild.
5. **Report the patch.** Relay the `patched <book>: ...` line (rows tagged, the
   new `v`s, the baseline). The patch stored fresh cached values with the
   built-in evaluator, so the book shows current totals in Protected View; a
   line naming formulas left uncached means those cells show blank until the
   estimator clicks **Enable Editing** (say so). `--commit --recalc excel`
   additionally has Excel recalculate the book and prints one `RECALC:` line;
   by default there is none. The estimator keeps working in the same book.

## Refresh: bring BidSheet.ai's changes into the book

When the estimator wants what others changed in BidSheet.ai since the book was
built (or last patched) without rebuilding, run
`~/.estimating/bin/est-estimate refresh <book>.xlsx` (add `--dry-run` to see
what it would do and write nothing). It reads the book, fetches the estimate
from the host stamped in the book (a page with its items), and:

- **Exit 0, `refreshed -- N cell(s), R row(s) added, D removed; baseline
  replaced`**: each line below names a change taken from BidSheet.ai. Rows the
  estimator changed and BidSheet.ai did not are kept as typed and still go out
  with the next apply. `the book is current with BidSheet.ai` means nothing
  changed there. Relay the notes (report-sheet rows blanked or as of the last
  build, labels that read as built until a rebuild).
- **Exit 4, `refresh found ... -- nothing written; the book keeps its
  baseline`**: show both lists as printed. *Changed in BidSheet.ai and in this
  book*: each line gives the sheet, row and field with BidSheet.ai's value,
  the book's and the value the book was built with. The estimator decides,
  cell by cell: to take BidSheet.ai's, type the "built with" value back; to
  keep the book's, note it, type the "built with" value back, refresh, then
  type it again and apply. You never edit a cell yourself to resolve a
  collision. *Needs a rebuild*: BidSheet.ai changed what the book is built
  around (an item, activity or crew added or deleted, an activity moved or
  given another crew, the cost shares, bid totals). Apply the book's edits
  first (steps 1 to 4), then rebuild from BidSheet.ai to a new file.
- **Exit 2** (nothing written): a read refusal (fix the book), a stale book
  (rebuild), a book open in Excel, or `--host` disagreeing with the stamp
  (drop it). "the refreshed book would not read back as this book does (...)":
  the estimator applies the book's edits first and you run the refresh again;
  if it still refuses, rebuild to a new file and report it with
  `report-issue`.
- **Exit 3**: BidSheet.ai did not answer the fetch; nothing was written; try
  again later.

## Read refusals (exit 2)

Each line reads `<sheet> row <r> column <c>: <what> -- <cure>`. Every
"rebuild" here means rebuild the book from BidSheet.ai to a new file name,
never over the edited book: the estimator's edits that must be redone live in
the old book. Relay the cure; the common ones:

- **A value typed on a marker row** (an activity's STEPS / START / END rows, a
  crew's end row): insert a row above the marker and type there.
- **A marker row deleted, moved, or pasted outside any block**: undo it, or
  rebuild.
- **"holds percent points -- type 15, not 15%"**: type the number of points.
- **A formula overwritten or cleared** ("held a formula and now holds a
  value"): undo the edit, or copy the formula back from a row of the same
  kind; "a hidden helper cell held a formula" is a typed-over hidden tag --
  undo it. **#REF!** ("a formula here lost its reference"): undo the delete,
  or rebuild.
- **A Rates sheet edit**: library rates are read-only — set the member's Rate
  override on the Crews sheet instead, and undo the Rates edit.
- **An export value edited** ("is read-only in the workbook -- change it in
  BidSheet.ai"): a figure the book's formulas read but no op writes (a crew's
  hours/shift or factor, an item's bid quantity, an element's derived
  quantity). Undo it; change it in BidSheet.ai, then rebuild.
- **"this activity's shifts come from its steps, which this book does not
  show"**: a book whose pack leaves steps out cannot send a stepped
  activity's shifts — undo the edit and change its steps in BidSheet.ai.
- **A linked activity copied with one copy edited**, or **an activity left
  under a copy of its parent**: undo, or apply the copy first, then edit.
- **An inserted row missing what it needs**: a new activity needs a name, a
  new step a name and a duration, a new line a name and a Type, a new member
  a classification and a count. Fill them in or delete the row (a row left
  completely empty is skipped, not refused).
- **A stepped block left without a step**: keep or fill in one step between
  STEPS and START, or delete the whole block.
- **A row of a kind that can't be added, copied or deleted** (items, element
  quantities, crews, sections, and any kind the pack declares fixed): undo it.
- **A stale book** ("this book's last apply was done but could not be patched
  fully"): rebuild it with the fetch and build commands the apply printed.
- **A renamed or missing tab**: rename it back, or rebuild.

## Notes (in the read and the dry run)

Notes do not stop the apply; show each one with the plan.

- **Rows not priced live**: a copied or typed activity's share of its item
  total, a typed line's cost, an inserted member's library rate — they show
  after the apply and a rebuild. Lines that price live still reach report
  sheets (HeavyBook's Flat and Checks) only then.
- **An activity added or deleted** changes the allocation between items, which
  only a rebuild lays out; the patch notes it. Rebuild once the apply is done.
- **A copy without rows the book does not show** ("the copy of activity N is
  created without its steps, which this book does not show"): the estimator
  adds them in BidSheet.ai after the apply.
- **Linked pastes**: a line pasted in from another workbook keeps its rate link
  and is priced at today's library rate, not the unit cost the book showed.
- **Renumbered rows** ("... is renumbered (sort order 0 -> 1) so a new row
  above keeps its place"): a new activity or line keeps the place it was
  given; where its neighbours share a sort order, the rows below it are
  renumbered, and their updates are in the plan. An allocation-posted line
  that would need renumbering refuses the read: put the new line below it.
- **Reordered rows** ("... is not where BidSheet.ai lists it among its
  rows"): an existing activity or line moved within its block is not sent;
  BidSheet.ai keeps its order, and a refresh or rebuild shows it. To change
  the order, reorder the rows in BidSheet.ai.
- **Edited copies** ("an edited copy of resource N, unlinked"): a line copied
  in the same book keeps its rate link only when nothing but its quantity was
  changed; any other edited input sends it as a plain line at the unit cost
  the book shows.
- **A step's cost code dropped**, **a lost multiplier** (a child activity made
  a root stops being multiplied by its former parents' count), **a library
  crew copied** into this estimate on edit: relay them.
- **Ignored rows**: a row typed among the bid items has no kind and is not
  read — bid items are added in BidSheet.ai.

## Errors from BidSheet.ai (exit 3)

The CLI prints `apply failed: <message>`, then for a refused op
`op <n> came from <sheet> row <row>` (a deleted row prints as `<sheet> (a
deleted row)`). You never map an op index yourself. Relay what it prints:

- **Conflicts** (`conflict: ...` lines): a row changed in BidSheet.ai since the
  book was last synced. To keep the book, refresh it (above): it shows each
  row changed on both sides; the estimator restores those cells, refreshes,
  retypes and applies again. A conflict can name a row the estimator did not
  edit: one renumbered to make room for an inserted row (its note is in the
  plan); refresh, then apply again. Otherwise rebuild (`~/.estimating/bin/est-estimate fetch`,
  then `build --pack <pack>`, the pack the read printed) to a new file and
  redo the edit. Nothing was applied.
- **A refused op**: BidSheet.ai's message with the op's book row. A pasted line
  whose rate link this estimate cannot use is refused this way: the estimator
  clears that line's hidden rate link (its `ref` tag; column AE on a HeavyBook
  Cost Report) or retypes the line, and you run the dry run again. A refusal
  with no `came from` line is the change set refused as a whole: relay it.
- **Access**: the estimate is missing, not theirs, or not editable.

## What read-back sends, and what it never does

Sent: markup; item quantity override, unit price, scope and bid price
override; element quantity overrides; activity, step and resource inputs;
crew member rosters; new activities, steps, lines and members; copied
activities (with their children the book shows); cut-and-pasted activities
and lines; deletes of activities, steps and lines. A field the book's pack
does not show is never sent: a copy takes it from its source.

Never: sections, bid totals, crew assignment (a copied activity keeps only its
source's crew and cost code), rate links on existing rows, codes, a reorder of
existing rows, library rates, a copied activity's element links or spread; creating or
deleting items, elements or crews; the export values the book's formulas
read.
