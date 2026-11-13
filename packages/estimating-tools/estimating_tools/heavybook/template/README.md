# HeavyBook's template pack

`template.xlsx` and `pack.yaml` are the source of HeavyBook's workbook. They were
generated once (exchange step 4) from the retired code writers; from then on they are
edited by hand -- in Excel, or by an agent through openpyxl -- to extend the book.

## Editing

- Edit `template.xlsx` in Excel. Rows above each sheet's first fill row (titles,
  headings, the Bid Form's estimate rows, the Recap's total, the Checks counters) are
  the template's own: edit them freely; a total over the filled rows spans the heading
  row to the sentinel row so it grows as rows are filled and inserted.
- Prototype rows live on the hidden `_templates` sheet, each block under a defined name
  (`hc.tpl.*` for what patch, refresh and Estimate Navigator insert; `hb.fill.*` for the
  rows only the fill copies). A prototype formula reads its own row, its block's owner
  and marker rows, the rows above it (`X$4:X<row above>`), whole columns and defined
  names -- never a fixed row of a filled sheet. Find another row by key:
  `INDEX('Cost Report'!$R:$R, MATCH("ITEM:"&$K5, 'Cost Report'!$AK:$AK, 0))`.
  The owner-row helper columns (`AJ` on the Cost Report, `R` on the Crews) stay blank on
  prototype rows: the fill writes them.
- The `hc.tpl.*` names are fixed: never rename them in a copy (in `template.xlsx` or in
  `pack.yaml`). The pack reports its insert kinds (`HeavyBookPack.templates()`, what an
  estimator's tool inserts) by the shipped template's names, not a copy's, so a renamed
  prototype is one it names but the book does not hold.
- A new column a formula reads from the read model is a label (`labels:` in
  `pack.yaml`, a bare path such as `activity.item.item_number`) or, when an edit of it
  must refuse the read, an export value.
- A defined name over a sheet's filled rows (`hc.cost_report`, `hc.bid_form`,
  `hc.checks`, `hc.schedule`, `hc.bid_totals`) ends on its region's sentinel row in the
  template; the fill sets it to end on the last row it placed. A name that is only the
  sentinel row (`hc.bid_totals`) covers exactly the placed rows; one that starts above
  (a heading) keeps its start. When the fill places no rows there, a name made only of
  the sentinel row stays on the sentinel row (a blank row), and one that starts above
  covers the rows above. Only workbook-scoped names are fitted: define such a name in
  Excel's Name Manager with scope Workbook, not a sheet.
- Change `pack.yaml` with the template: a new filled column, a new prototype, a new
  label. Keep `pack.version` at 2: this plugin reads HeavyBook books of versions 1 (built
  by the retired code writers) and 2, refuses a newer one ("update the plugin"), and
  refuses to build from a copy that declares another version. A layout an older book
  could not be read as is a new pack version, shipped with the plugin that reads it.

## Verifying an edit

1. `est-estimate build --pack heavybook payload.json --template DIR -o book.xlsx`, with
   `DIR` the edited template pack directory (`pack.yaml` and `template.xlsx`) -- the lint
   runs on every build and names the cell and formula it refuses.
2. `pytest packages/estimating-tools/estimating_tools/heavybook/tests` -- above all
   `test_golden_values.py` (every value the code build computed, by row identity) and the
   read-back, patch and refresh suites, which build from this template.
3. A deliberate change of values or layout updates the golden in the same commit, with
   the reason in the message. Edit `fixtures/golden/values.json` by hand: rename the keys
   of the rows the change moved and change the values it changed. Do not run
   `UPDATE_GOLDEN=1 pytest .../test_golden_values.py` for it: that rewrites the whole
   golden file from the template build, adding every identity the template build holds
   and dropping the code build's `Z` values (an element quantity's parent tag), so the
   golden no longer holds the template to the code build, which is what it is for.
