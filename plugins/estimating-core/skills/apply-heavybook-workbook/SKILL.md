---
name: apply-heavybook-workbook
description: Send an estimator's edits in a HeavyBook estimate workbook back to BidSheet.ai — run est-estimate apply on the edited .xlsx (edited inputs, rows inserted with Estimate Navigator, copied, pasted and typed rows, cut-and-pasted activities and lines, deletes) to dry-run it, show the plan, and apply it only on the estimator's yes; the book is patched in place. Also brings BidSheet.ai's changes into the book in place with est-estimate refresh (collisions are shown, never resolved). Writes to BidSheet.ai. Use for "apply my workbook edits", "send the HeavyBook workbook back", "push the edited estimate workbook", "refresh my workbook from BidSheet.ai", "pull BidSheet.ai changes into the workbook". To build the book in the first place use build-heavybook-workbook.
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

# Apply HeavyBook workbook edits to BidSheet.ai

A HeavyBook book (from the `build-heavybook-workbook` skill) carries the
estimate it was built from. Reading it back (the apply command does the read) compares the edited book with that
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

## Workflow

The change set and the plan move between the book and BidSheet.ai through
`est-estimate`, as the estimator, over their stored API token. You run the
commands and read what they print. You never open the change set JSON or the
payload and never pass their contents to an MCP tool: a payload that crosses
you is transcribed, and one mistyped `v` is a false conflict while one
mistyped unit cost is a silent misprice (contract rule 14).

0. **Once per machine.** If `~/.estimating/bin/est-estimate apply` is refused
   (exit 2, "(nothing sent)") with "no BidSheet.ai token stored", or with "the
   stored BidSheet.ai token file is unreadable", or with a message naming a
   host mismatch, ask the estimator to run `~/.estimating/bin/est-estimate login`
   themselves (add `--host` when the message names a host; it prompts for the
   token, you never see it), then run the apply again. Nothing was sent, so
   this is never an unknown outcome and never needs `--request-id`.
1. **Dry run.** `~/.estimating/bin/est-estimate apply <book>.xlsx`
   - Exit 0 prints `dry run -- request <id>`, the change summary (each line
     naming its book row, except a delete's line, whose row is gone), the
     change set's notes, then the plan: deletes and what they cascade to,
     warnings (crew copies among them), and totals before and after, ending
     with `Re-run with --commit to apply.` "no changes -- nothing to send"
     means there is nothing to apply: stop.
   - Exit 2 is **refused locally, nothing sent**; the printed line says which:
     - A **read refusal** (problems listed): show the list; the estimator
       fixes the book; run again.
     - A **locked book** on `--commit` ("cannot open <book> for writing (open
       in Excel, or read-only) -- close it or make it writable and retry
       (nothing sent)"): the estimator closes Excel or makes the file
       writable; run the commit again (nothing was sent).
     - **No token, an unreadable token file, or another host** ("apply
       refused: ... (nothing sent)"): see step 0.
     - "this book was built from <host>; --host says <other> (nothing sent)":
       the host stamped in the book decides where the apply goes, and `--host`
       may only repeat it. Drop `--host` and run again. When the stamped host
       is not the stored token's, the refusal names it: the estimator runs
       `~/.estimating/bin/est-estimate login --host <stamped host>` first (step 0).
     - "no installed pack recognizes this book": not a HeavyBook; rebuild it.
     - "made by a newer version of the heavybook pack -- update the plugin":
       update the plugin (do not rebuild).
     - "this book targets contract N" (a contract major this plugin does not
       read): update the plugin (do not rebuild).
     - "the book's declaration cannot be read": rebuild the book.
     - "two packs claim this book": report it; do not work around it.
     - The book's estimate id is not a number: rebuild the book.
     - "this is a heavybook book but its stamp is damaged -- rebuild it":
       rebuild the book.
   - Exit 3 is **BidSheet.ai's refusal or failure** (`apply failed: ...`: a
     conflict, a precondition, an unknown estimate, or the server
     unreachable): the server's message is printed, with the sheet and row the
     refused op came from. A conflict means a row changed in BidSheet.ai
     since the book was last synced; rebuild the book
     (`~/.estimating/bin/est-estimate fetch`, then `build --pack heavybook`) to a new file
     name, never over the edited book, and redo the edit. For a book built
     from a page, fetch the same `--items`.
     For a conflict, refresh the book first (below) when the estimator wants
     to keep the book: it shows each row changed on both sides; the estimator
     restores those cells, refreshes, retypes, and applies again.
2. **Show the plan** to the estimator as printed, and ask them to confirm.
3. **Apply on a yes.** `~/.estimating/bin/est-estimate apply <book>.xlsx --commit`
   applies with a fresh request id, fetches the estimate, and patches the
   book in place: new rows get their ids and `v`, the baseline is replaced
   once the patched book has been read back clean, and nothing the estimator
   typed is touched. It prints
   `patched <book>: N row(s) tagged ...`. The patch rewrote inputs, and the
   built-in evaluator stored fresh cached values for every formula it covers,
   so the book shows current totals in Protected View; a line naming formulas
   left uncached means those cells show blank until the estimator clicks
   **Enable Editing** (say so). `--commit --recalc excel` additionally has
   Excel recalculate the book (for functions the built-in evaluator does not
   cover) and prints one `RECALC:` line; by default no engine runs and no
   `RECALC:` line is printed. The estimator keeps working in the
   same book. A book built from a page is patched from a fetch of the same
   items, so it stays a page: the book's stamp says whether it is a page and
   which items it covers, and the commit (and the printed rebuild advice)
   carries `--items` only for a page; a whole-estimate book is fetched and
   rebuilt without it. If the book is open in Excel (or read-only)
   before the send, the commit is refused with exit 2: "cannot open <book>
   for writing (open in Excel, or read-only) -- close it or make it writable
   and retry (nothing sent)". Ask the estimator to close it, then run the
   commit again.
   - If the command reports an **unknown outcome** (no answer, or a server
     error, after the send), re-run with `--commit --request-id <id>` using the id
     it printed. A server with request-id support replays the stored result
     and nothing is created twice. Against an older server, look at the
     estimate in BidSheet.ai before resending.
   - If it prints `applied, but ...` or a `Not written:` list (both exit 3),
     the apply went through and part of the book could not be patched. Do
     **not** run `apply` again: the CLI ends with "The apply is done -- do not
     run apply on this book again; rebuild it from BidSheet.ai: est-estimate
     fetch ... -o ..., then est-estimate build --pack heavybook ... -o
     <book>.rebuilt.xlsx". Run those two commands as printed (through
     `~/.estimating/bin/est-estimate`): they keep a page a page (`--items`)
     and write a new file next to the book, never over the edited book (the
     edits still to redo live in it); a re-apply would resend creates that are
     already done. When "the book could not be patched" ends " -- close the
     workbook in Excel first", the estimator closes Excel and you run the
     printed rebuild; never re-apply.
   - A patch whose copy **does not read back clean** because someone changed
     the estimate in BidSheet.ai meanwhile takes their changes the way a
     refresh does (the last lines of the printout list them under `Notes:`)
     and is adopted. Only when it cannot -- BidSheet.ai changed something
     the book cannot take in place, such as an added item -- does the book
     keep its old baseline, get its ids and `v`, and is marked stale: the CLI
     exits 3 with "the patched book would not read back clean (...) -- the
     apply is done; the book keeps its old baseline and is marked stale, so
     every read refuses it; rebuild the book from BidSheet.ai" and the same
     rebuild advice. From then on every `read`, `apply` and `refresh` of that
     book refuses it (exit 2, nothing sent or written) until it is rebuilt;
     run the printed rebuild.
   Anything short of a yes is not a yes: they change the book, and you run
   the dry run again.

## Refresh: bring BidSheet.ai's changes into the book

When the estimator wants what others changed in BidSheet.ai since the book
was built (or last patched) without rebuilding, run
`~/.estimating/bin/est-estimate refresh <book>.xlsx` (add `--dry-run` to see
what it would do and write nothing). It reads the book, fetches the estimate
from the host stamped in the book (a page with its items), and:

- **Exit 0, `refreshed -- N cell(s), R row(s) added, D removed; baseline
  replaced`**: each line below names a change taken from BidSheet.ai.
  Rows the estimator changed and BidSheet.ai did not are kept as typed and
  still go out with the next apply. `the book is current with BidSheet.ai`
  means nothing changed there. Notes may say that a summary sheet cell now
  reads `#REF!` (a line BidSheet.ai deleted) or that added lines reach the
  summary sheets on the next rebuild -- display only, prices are live.
  A refresh that wrote the book caches its values the same way as
  `apply --commit`; `--recalc excel` additionally has Excel recalculate it
  (one `RECALC:` line; none by default).
- **Exit 4, `refresh found ... -- nothing written; the book keeps its
  baseline`**: show both lists as printed. *Changed in BidSheet.ai and in
  this book*: each line gives the sheet, row and field with BidSheet.ai's
  value, the book's and the value the book was built with. The estimator
  decides, cell by cell: to take BidSheet.ai's, type the "built with"
  value back; to keep the book's, note it, type the "built with" value back,
  refresh, then type it again and apply. Run the refresh again when done.
  You never edit a cell yourself to resolve a collision: relay the list and
  let the estimator decide. A collision is per row, so it lists every field
  of that row that differs -- also fields the estimator did not touch, which
  BidSheet.ai changed: for those the book already shows the "built with"
  value, typing it back does nothing, and they come in with the refresh once
  the estimator's own edits on that row are restored.
  *Needs a rebuild*: BidSheet.ai changed what the book is built around (an
  item, activity or crew added or deleted there, an activity moved or
  given another crew, the cost shares, bid totals). Apply the book's edits
  first (`apply`, then `apply --commit`), then rebuild from BidSheet.ai to a
  new file as the apply's advice prints it.
- **Exit 2** (nothing written): a read refusal (fix the book; see below), a
  stale book (rebuild), a book open in Excel ("close it or make it writable
  and retry"), or `--host` disagreeing with the book's stamp (drop it). "the
  refreshed book would not read back as this book does (...) -- nothing
  written" is the refresh refusing a result it could not verify: show the
  lines (the ops it would also send, or no longer send); the estimator
  applies the book's edits first (`apply`, then `apply --commit`) and you run
  the refresh again. If it still refuses, rebuild from BidSheet.ai to a new
  file and report it with the `report-issue` skill.
- **Exit 3**: BidSheet.ai did not answer the fetch; nothing was written; try
  again later.

Known limits: lines, steps and members a refresh adds reach the summary
sheets (Flat, Recap, Schedule, Checks rows) only on a rebuild, and labels a
book does not bind (codes, item descriptions) stay as built. An activity
whose crew is not on the Crews sheet is priced from its labour and man-hours
per shift as of the build: when BidSheet.ai changes that activity's labour,
the refresh does not carry it -- rebuild.

You run the command and relay what it prints; you never open the payload.

## Read refusals (exit 2)

Each line reads `<sheet> row <r> column <c>: <what> -- <cure>`, naming the
sheet, row and column where it applies (a deleted row has no row, a
whole-row problem no column). Every "rebuild" here, and everywhere in this
skill, means rebuild the book from BidSheet.ai to a new file name, never over
the edited book: the estimator's edits that must be redone live in the old
book. Relay the cure; the common ones:

- **A value typed on a marker row** (the STEPS / START / END rows of an
  activity, a crew's end row): insert a row above the marker and type there.
- **A marker row deleted or moved**: undo it, or rebuild the book.
- **A stray marker** ("a stray STEPS marker", START, END or a crew's end
  row): a marker row was pasted outside any block, where no activity or
  crew owns it — undo the paste.
- **"holds percent points -- type 15, not 15%"**: a percent cell (markup,
  burden) was typed with a `%`; type the number of points.
- **A formula overwritten or cleared** ("held a formula and now holds a
  value"): undo the edit, or copy the formula back from a row of the same
  kind. A value typed over a hidden owner tag (the cell that names the
  block a step, line, marker or crew member sits in) reads as "a hidden
  helper cell held a formula and now holds a value" — undo it. **#REF!**
  ("a formula here lost its reference"): a row a formula pointed at was
  deleted — undo the delete, or rebuild.
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
  cannot tell which row keeps the links — undo the edit, apply the copy
  (`apply --commit` patches the ids in), then make the edit and apply again.
- **An activity left under a copy of its parent** ("now sits under a copy of
  its parent"): copy the parent together with its children, or undo.
- **An inserted row missing what it needs**: a new activity needs a name, a
  new step a name and a duration, a new line a name and a Type, a new member
  a classification and a count. Fill them in, or delete the row. An inserted
  row left completely empty is skipped, not refused.
- **A stepped block left without a step** ("a new activity with a STEPS
  marker needs at least one step filled in -- add one between STEPS and
  START, or build it from the plain prototype"; "a copied activity with a
  STEPS marker needs at least one step -- keep one of its steps between STEPS
  and START, or delete the copy"; "activity <id> (<name>): all of its steps
  were deleted or cut away -- keep at least one step, or delete the whole
  block"): BidSheet.ai would leave the activity without steps under a block
  whose STEPS marker says it has them, and the next read would refuse the
  book. The estimator fills in or keeps one step, or deletes the whole block;
  run the read again.
- **A stale book** ("this book's last apply was done but could not be patched
  fully (...) -- do not apply it again; rebuild the book from BidSheet.ai"):
  a committed apply went through but its patch did not read back clean (step
  3), so the book kept its old baseline and was marked. Every read and apply
  refuses it. Rebuild it from BidSheet.ai to a new file with the fetch and
  build commands the apply printed; never edit the book back into shape.
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

## Notes (in the dry run)

Notes do not stop the apply; show each one with the plan (the dry run prints
them).

- **Rows not priced live**: a copied or typed activity's share of its item
  total, a typed line's cost, a typed member's rate in its crew rate — the
  live figures appear on the next refresh (after a rebuild). Copied, pasted and
  typed lines that do price live in the book still reach the Flat sheet and
  the Checks rows only on that refresh. After the patch their ids are in the
  book.
- **Inserted rows**: an inserted activity is a root of the item above it; its
  share of the item total, and an inserted member's library rate (0 until
  then, unless a Rate override is typed), show on the next refresh (after a
  rebuild). Inserted lines price live, but reach the Flat sheet and the Checks
  rows only on that refresh. A row inserted and never filled is
  skipped, with a note naming its row; an empty inserted activity is skipped
  as one. An inserted stepped activity with no step filled in is refused, not
  created: fill a step in between its STEPS and START rows, or insert a plain
  activity instead.
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

## Errors from BidSheet.ai (exit 3)

The CLI prints `apply failed: <message>`, then for a refused op
`op <n> came from <sheet> row <row>` (a deleted row prints as `<sheet> (a
deleted row)`). You never map `op_index` yourself. Relay what it prints:

- **Conflicts** (`conflict: ...` lines): a row changed in BidSheet.ai since
  the book was last synced -- rebuild the book (`~/.estimating/bin/est-estimate fetch`, then
  `build --pack heavybook`) to a new file name, never over the edited book, and redo the
  edit. Nothing was applied.
- **A refused op**: BidSheet.ai's message with the op's book row. Nothing was
  applied. A pasted line whose rate link this estimate cannot use (another
  organization's library, or a retired rate) is refused this way: tell the
  estimator to clear that line's hidden rate link (column AE) or retype the
  line, then run the dry run again. A refusal with no `came from` line means
  BidSheet.ai refused the change set as a whole: there is no book row to
  name -- relay its message.
- **Access**: the estimate is missing, not theirs, or not editable (a viewer,
  or a locked estimate). No token stored is a local refusal (exit 2, nothing
  sent); see step 0.

## What read-back sends, and what it never does

Sent: markup; item quantity override, unit price, scope and bid price
override; element quantity overrides; activity, step and resource inputs;
crew member rosters; new activities (inserted with Estimate Navigator), steps,
lines and members; copied activities (with
their children); cut-and-pasted activities (moved to their new item) and lines
(moved to their new activity); deletes of activities, steps and lines.

Never: sections, bid totals, crew assignment (a copied activity only keeps
its source's crew and cost code), rate links on existing rows, codes, sort
order (crew members keep theirs; new members are appended), library rates, a
copied activity's element links or spread; creating or deleting items,
elements or crews; the export values the book's formulas read (a crew's
hours/shift and crew factor, an item's bid quantity, an element's derived
quantity) — an edit to one is refused.
