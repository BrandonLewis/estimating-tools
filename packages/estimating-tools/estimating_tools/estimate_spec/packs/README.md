# Writing a format pack

A **format pack** is the data that decides what an estimate workbook looks like.
The engine (`estimating_tools.estimate_spec`) supplies the mechanism; the pack
supplies the shape, the styling and the vocabulary. Packs are **data, never
code**: every document is read with `yaml.safe_load` / `json.loads`, and nothing
a pack names is imported or executed.

One pack ships with the tool: `packs/fieldbook/`, the default — a full
estimate format built on every feature below (see "The fieldbook pack" at the
end). Read it alongside this page, or copy it as the start of your own. The demo
pack it replaced is retired; its frozen copy is the engine's regression fixture,
`tests/fixtures/packs/legacy_demo/` in the source repository, and still the
shortest complete pack there is.

A pack is resolved, in order, from `--format <dir>`, then the org profile's
`estimating.format`, then the bundled fieldbook pack. **A pack that is named but
missing or invalid is an error** — never a silent fall back to another format.

---

## The directory

```
my-pack/
  format.yaml        # the manifest: identity, capabilities, and what the other files are called
  units.yaml         # structure: the block types a recipe can compose, and their params
  tokens.yaml        # style: fonts, fills, borders, number formats
  recipes.yaml       # composition: which units make up each item type
  vocabulary.yaml    # what is permitted: trades, cost blocks, takeoff/spreads shapes
  seed.yaml          # what a fresh spec starts with, and how apply-takeoff routes geometry
  examples/*.estimate.yaml    # optional, but write one: it is how a reader learns the pack
```

A pack never ships a schema file. The engine's skeleton carries the mechanism
and `{"$vocab": KEY}` markers; `load_pack` composes it with your
`vocabulary.yaml` into `FormatPack.schema`.

## `format.yaml` — the manifest

```yaml
name: my-pack          # required
version: 1             # required
provenance: authored   # required of packs shipped IN this repo; optional for yours
files:                 # all five are required
  units: units.yaml
  tokens: tokens.yaml
  recipes: recipes.yaml
  vocabulary: vocabulary.yaml
  seed: seed.yaml
supports: [summarize, artifact]      # optional; see "Capabilities"
labor:
  crew_factor_default: 1             # required if `supports:` includes summarize
strict: true                         # optional, default false; see "strict:" below
derived_from: fieldbook              # optional; see "derived_from:" below
```

Every `files:` path must stay inside the pack directory. An unknown `files:`
key is refused.

`provenance: authored` is asserted of every pack under `estimate_spec/packs/`
in this repo, as a guard against a customer's real format being committed here
by accident. `load_pack` does not require it, so your own pack need not carry
it.

### `derived_from:` — a fork that keeps fieldbook's grid

An org pack copied from fieldbook (its own `name`, trades, seed, an extra
column) declares `derived_from: fieldbook` to say it keeps fieldbook's layout
contract: the hidden Q..T tag columns, the row-kind vocabulary (ITEM, TASK,
CREW, LINE, ...) and the input columns of each row kind. Then:

- **It inherits fieldbook's `layout_map:`** when it declares none, so its
  workbooks get Estimate Navigator's defined names, `_templates` sheet and
  `est.layout` (which records `derived_from`). Its own `layout_map:` wins when
  present.
- **`est-estimate read-back` reads its workbooks.** Read-back resolves the
  pack the way `build` does — `--format`, then the org profile's
  `estimating.format`, then the bundled pack — accepts a workbook whose
  `estimate_format` stamp is that pack's `"<name> <version>"`, and builds its
  comparison baseline with that pack. `--format` also takes the bare name
  `fieldbook` (no path needed), so a stock fieldbook workbook reads back with
  `--format fieldbook` on a machine whose profile names the org pack.
- **An inherited map must fit.** The pack is refused at load when fieldbook's
  map names an export it does not publish: keep fieldbook's Cost Summary,
  Checks and Codes export names (`cs[ITEM].bid`, `cost_summary_total.direct`,
  `checks_head.count`, `code_rows.codes`), or declare your own `layout_map:`.

Only `fieldbook` can be named today; any other value is refused at load. The
declaration is a promise: `test_readback_layout.py` checks every pack that
makes it against what the reader expects (set `EST_READBACK_LAYOUT_PACKS` to
your pack's directory to run it against yours). A fork that moves an input
column fails it — and read-back would misread that column — so keep the
columns, or do not declare `derived_from`.

## Capabilities (`supports:`)

Three verbs work with any valid pack: **build**, **scaffold** and
**apply-takeoff**. Two more read shapes the engine cannot infer, so a pack opts
into them explicitly and every other pack is refused by name:

| capability  | what it enables                        | what the pack must also provide |
|-------------|----------------------------------------|---------------------------------|
| `summarize` | `est-estimate summarize` (pure-Python pricing) | `labor.crew_factor_default` in the manifest; `vocabulary.foreman_trade`; spreads legs named `ftg_qty`/`ftg_waste`/`wall_qty`/`wall_waste`, with waste defaults declared on a unit param or set per block |
| `artifact`  | `render_item` / `parse_item`, the inline item editor | a spreads/takeoff shape the renderer can read |

Declaring a capability your pack cannot actually satisfy is worse than not
declaring it: the tools will run and produce a number. Leave it off unless the
shape matches.

### `strict:` — enforce your schema on the build path

`scaffold`, `apply-takeoff` and `scaffold.validate_spec` always run full
jsonschema validation against `FormatPack.schema` (the skeleton composed with
your `vocabulary.yaml` — item_rules, `defs.takeoff`/`defs.spreads`, a `false`
schema for a field your pack forbids outright, and so on). `build.generate`
(and so `est-estimate build`) historically did not: it only ever checked
cross-references (crew ids, trades, rate breakdowns), so a spec your
vocabulary refuses could still be built if nothing validated it first.

`strict: true` closes that gap: `generate` runs the same schema check, in the
same `schema violation: $[path]: <message>` shape, before laying out a single
cell. It is opt-in and `false` by default — a pack that never sets it builds
exactly as it always has; this is not one of the two `supports:` capabilities
(every pack's build path can run its own schema, the same way every pack can
be scaffolded against), just a switch for a check that was already true of
your pack and is now also enforced where it writes a file.

Turn it on once your vocabulary's refusals are the ones you actually want
build-time to enforce — not every pack needs this the day it is written, but
a pack that lays out its own per-item invariants (fieldbook's per-task cost
code, its ban on item-level `cost_details`) should.

## Workbook-level sheets, protection and conditional formats

More engine features, all pack-opted and all inert unless a pack (or the
estimate config) actually uses them — a pack that touches none of them
renders exactly as it did before these existed.

### `book:` — workbook-level sheets, instead of a cover

A pack declares **either** `recipes.cover` **or** a top-level `book:` list in
`recipes.yaml` — never both (a pack that sets both is refused at load,
"a pack declares either recipes.cover or book, not both"). `book:` lays out
one or more sheets that are not item sheets — typically a front sheet
listing every bid item's total, and a back sheet of notes:

```yaml
book:
  - sheet_name: Front
    position: before_items          # before_items | after_items
    column_widths: { A: 10, B: 18 }
    units:
      - unit: book_list
        params: { items: "{book.items}" }
  - sheet_name: Back
    position: after_items
    hidden: true
    units:
      - unit: book_note
        params: { text: "{config.project}" }
```

Each book sheet mapping carries `sheet_name`, `position`, `column_widths`,
`units`, `hidden`, `hidden_columns`, `freeze`, `print` — the same shape a recipe has, except a
book sheet's own units may not set `sheet:` (they always write to that
sheet).

`{book.items}` is a scope available only on a book sheet's units: the bid
items the estimate carries, *excluding* any item marked `in_summary: false`
(a shared-cost sheet, whose dollars already reach the bid through the items
that pay for it — the rule `recipes.cover` has always applied). A unit that
iterates it reaches each item's own exports with the cross-sheet ref pattern,
its sheet name coming from the item itself:

```yaml
B: { formula: "={ref:{it.sheet}!job_total.grand_total}" }
```

`{it.sheet}` expands at recipe-expansion time (the item's own sheet name);
the `{ref:SHEET!...}` it leaves behind resolves at write time exactly like
any other cross-sheet ref (see "Referring to another sheet" below) — order
does not matter, so a book sheet may name an item sheet laid out before or
after it.

A book entry's `when:` sees only **that sheet's own** exports — never an
item sheet's, and never another book sheet's. A unit that needs an item's
export has to reach it with a cross-sheet `{ref:...}`, not a `when:`.

Every `sheet_name` must be a legal Excel worksheet title (a non-empty string
of at most 31 characters, none of `[ ] : * ? / \`), and every book
`sheet_name` must be unique **case-insensitively** ('Front' and 'FRONT'
collide, the way Excel itself treats them) — and must not collide with any
item sheet's name, nor with a sheet an anchored unit's `sheet:` override
already created (e.g. a rate-table host). The build refuses either
collision by name, naming what it collided with.

The workbook's active sheet on open is the first **visible** sheet in book
order (the `before_items` sheets, then the item sheets, then the
`after_items` sheets) — a `hidden: true` book[0] does not leave the
workbook un-openable.

### `locked:` and sheet protection

```yaml
# tokens.yaml
styles:
  price_input: { fill: input_bg, locked: false }
```

```yaml
# format.yaml
protect: { sheets: true, password: "" }
```

A style may set `locked: false` (or `true`) — a real boolean, not the string
`"false"`; anything else stops the build, naming the style. A style that
never sets `locked` is left completely alone (its cells keep openpyxl's own
default), so a pack that doesn't opt in renders byte-for-byte as before.

`protect:` in the manifest is the switch: `sheets: true` locks every sheet
in the workbook, and only the cells whose style says `locked: false` stay
editable. `password` (optional; it requires `sheets: true`) sets Excel's
legacy protection hash. A protected sheet still lets the estimator resize
columns and rows to fit what they typed; everything else openpyxl protects
by default — inserting/deleting rows, sorting, filtering, re-formatting —
stays blocked.

A cell that resolves blank (an `optional:` cell with nothing to show) gets no
value and none of its style's other formatting, but it still gets the
style's `locked:` setting — otherwise a protected sheet would permanently
lock a price cell that happened to render empty, with no way to ever type a
price into it.

**`protect.password` is an accident guard, not a security control** — it is
Excel's legacy hash, trivially recoverable by anything that tries. `protect`
locks cells, not the workbook's structure, so a `hidden: true` sheet can still
be unhidden from Excel's sheet tabs: hiding keeps a sheet out of the way, it
does not keep anything secret. A pack
whose output is meant to be edited by copy-and-paste (as fieldbook's is)
should not protect at all: Excel refuses to paste into a locked cell, so
protection would break the very workflow the pack exists for.

### `conditional:` — live Excel conditional formatting

```yaml
rows:
  - repeat: p.lines
    cells: { ... }
    conditional:
      - { cells: F, formula: "={r}>10000", style: total }
      - { cells: "A:F", formula: '=AND($G{r}<>"",$G{r}>10000)', style: total }
```

A unit row (`units.yaml`) may carry `conditional:`, a list of `{cells,
formula, style}` rules. `cells` is a single **uppercase** column letter or a
column range (`F` or `A:F`, first column before the second — `F:A` and
lowercase letters are both refused). `formula` is a string starting with
`=`; the usual `{r}` / `{row:}` / `{ref:}` / `{p.}` placeholders resolve the
same as on any other cell. `style` names a `tokens.yaml` style; only its
font bold/italic/colour and fill are lifted into the Excel conditional
format ("dxf") — border, alignment and number_format on that style are
silently inert here.

A rule **spanning more than one column** must `$`-anchor every column
reference in its *resolved* formula (`$F{r}`, never bare `F{r}`): Excel
evaluates a formula-based rule relative to the top-left cell of the range it
is painted over, so an unanchored reference drifts column to column — almost
never what the author meant. This is checked on the resolved formula (after
every placeholder has expanded), and it does not mistake a function name
that merely looks like a reference (`LOG10(...)`, `ATAN2(...)`) or a named
range for one.

The rule belongs to the **row**, not to any one cell on it: a cell the row
skips (blank, `if_it:`, `if_ref:`, `optional:`) does not remove the row's
rule — guard the formula itself if you want the format to go quiet for that
row, e.g. `=AND($G{r}<>"",$G{r}>10000)`. On a conflicting property between
two rules listed on the same row, the earlier-listed rule wins
(non-conflicting properties — one rule's fill, another's font colour —
combine). A merged row (`merge_down:`) gets its rule on the merge's first
row only.

### `if_it:` — a per-repeat-element cell condition

```yaml
cells:
  G: { value: "{it.unit_price}", if_it: { cost_type: material } }
```

A cell may carry `if_it:`, a non-empty mapping of field -> value. The cell
is rendered only for the repeat elements whose fields equal those values,
compared as **text** (YAML's `31` and `"31"` compare equal; `31` and `31.0`
do not). A field the element lacks compares as `None`. `if_it:` is legal
only on a cell inside a `repeat:` row over mappings — a non-repeat row
(whose `item` is always `None`) or a non-mapping element fails the build by
name ("`if_it` needs a `repeat:` row over mappings").

### `hidden_columns:` and `hidden:`

```yaml
recipes:
  line_item:
    hidden_columns: [F]        # on an item recipe
    units: [...]

book:
  - sheet_name: Back
    hidden: true               # the whole sheet -- book sheets only
    hidden_columns: [B]        # on a book sheet
```

`hidden_columns:` (a list of column letters, A through XFD) hides those
columns on an item recipe's sheets, or on one book sheet. `hidden: true`
hides a book sheet entirely (its `sheet_state` becomes `"hidden"`) — there
is no item-recipe equivalent, since every item sheet is meant to be seen.

### `freeze:` and `print:` — panes and page setup

```yaml
recipes:
  line_item:
    freeze: A2                 # rows above A2 stay in view while the sheet scrolls
    print: { orientation: landscape, fit_to_width: 1, repeat_rows: "1:1" }
    units: [...]

book:
  - sheet_name: Bid Form
    freeze: A4
    print: { orientation: portrait, fit_to_width: 1, repeat_rows: "1:3" }
```

`freeze:` is Excel's freeze-panes cell: the rows above it and the columns left
of it stay in view (`A4` keeps rows 1–3; `C3` keeps rows 1–2 and columns A–B).
`print:` sets the page: `orientation` (`portrait` | `landscape`),
`fit_to_width` (print that many pages wide, and as many pages tall as it
takes) and `repeat_rows` (`"FIRST:LAST"`, printed at the top of every page);
any subset of the three. Both go on an item recipe or a book sheet, are
checked at load (a cell reference; known keys and values, by name) and change
nothing on a sheet that does not set them.

### `concat:` — one list from several, de-duplicated

A unit param may be built from several lists at once:

```yaml
params:
  codes:
    unique: code                        # keep the first element per code
    concat:
      - for_each: config.cost_codes     # the org's list first...
        as: { code: "{it.code}", listed: 1 }
      - concat:                         # ...then every item's task codes
          for_each: config.items
          as: { for_each: it.labor, as: { code: "{it.cost_code}", listed: 0 } }
```

`{concat: V}` resolves `V` to a list and splices each element that is itself a
list into one flat list, one level deep, in order — so a `for_each` whose `as:`
is another `for_each` (a list of lists) comes out flat. `unique: FIELD` then
keeps only the first element per value of that field, compared as text (`31`
and `"31"` are one value); an element without the field is always kept, and
`unique: true` compares whole (scalar) elements. Any other key is refused.

### `validation:` — Excel dropdowns

```yaml
D: { value: "{it.uom}", validation: { list: ["LF", "TON", "DAY"] } }
E: { value: "{it.unit_price}", validation: { list: "='Rates'!$A$2:$A$6" } }
```

A cell may carry `validation: {list: [...]}` (a literal set of text choices
— no commas or double quotes in a choice, and the Excel formula it builds
must stay under Excel's own 255-character cap, quotes included) or
`validation: {list: "=<range>"}` (placeholders allowed; the range must
resolve, once every placeholder expands, to a single cell, a single column,
or a single row — never a rectangle, which Excel's List validation refuses
as a source). A defined name or a formula like `OFFSET(...)` is not
shape-checked — there is nothing to check its shape against before Excel
opens it, so it fails open rather than guessing.

A dropdown is applied to a blank **optional** cell exactly as to any other:
an optional cell may render empty, but it does not excuse a bad list — a
range that resolves empty, or to a rectangle, still stops the build even
though the cell's own value would have been allowed to go blank.

A dropdown is **strict** by default: Excel stops a typed value that is not on
the list ("Not on the list — Pick a value from the list."). Add
`strict: false` to let the cell take other values too, the list then being
only a suggestion:

```yaml
D: { value: "{it.uom}", validation: { list: ["LF", "TON", "DAY"], strict: false } }
```

`list` and `strict` are the only keys `validation:` accepts, and `strict` must
be a real boolean.

On a pack that protects its sheets (`protect: {sheets: true}`), a dropdown
cell must be unlocked — its effective style (the composite style plus the
cell's own overrides) must say `locked: false`. Excel will not let anyone
pick from a locked cell's list, so the build refuses a dropdown on a locked
cell by name rather than ship one nobody can use.

### `ref_error:` — a pack-authored message when a cell's value fails to resolve

```yaml
G: { formula: "={ref:markup_grid.{it}}",
     ref_error: "fieldbook lays out markup rows overhead, insurance and profit only (got '{it}')" }
```

When a non-`optional:` cell's value or formula fails to resolve (an unknown
`{ref:...}`, `{row:NAME}` or `{p.x}`), the build normally re-raises the bare
`KeyError`/`ValueError` from whatever failed. `ref_error:` names a friendlier
message instead — itself a template, resolved the same `{it}` / `{p.x}` / etc.
way, which still works even though the cell's own `{ref:...}` could not — and
raises it as a `RecipeError`. It does not apply to a cross-sheet
`{ref:SHEET!...}` failure, which always names its own site (see "Referring to
another sheet" below) and is never swallowed or renamed.

### A leading zero marks text, not a number

A resolved cell value that looks like a bare integer (`"10"`, `"-5"`) is
written as a number — except when it is zero-padded: a digit string longer
than one character and starting with `"0"` (`"010"`, `"007"`) is written as
text instead. A single `"0"` still becomes `0`. This matters for item numbers
and other codes whose leading zero carries meaning (`"010"` is a label, not
the number ten).

## New optional spec fields

A handful of fields any pack's estimate config may now carry — generic
across every pack, since they live in the engine's own schema skeleton, not
a pack's `vocabulary.yaml`:

- **`shift_hours`** (top-level, default 8): hours in a crew-day. A pack that
  prices a crew by the hour, rather than by the day, multiplies days by
  this.

- **`rate_table[].kind`** (`labor` | `equipment`, default `labor`):

  ```yaml
  rate_table:
    - { trade: Laborer, rate: 81.89, base: 48.10, burden_pct: 0.32, fringe: 18.40 }
    - { trade: "Excavator, 320 class", rate: 145.0, kind: equipment, includes_operator: false }
  ```

  A `labor` row may break its `rate` down into `base` (hourly wage),
  `burden_pct` (payroll burden **as a fraction**, 0.32 = 32% — like every
  other percentage in the spec; BidManager's own percent form is a phase-2
  concern), and `fringe` (dollars/hour added after the burden). When any of
  the three is given, `base * (1 + burden_pct) + fringe` must reproduce
  `rate` within $0.01 — enforced before every build and by `validate_spec`.
  An `equipment` row instead may carry `includes_operator` (its hourly rate
  already pays for its operator); it may not carry `base` / `burden_pct` /
  `fringe`, and a `labor` row may not carry `includes_operator` — the schema
  refuses either mismatch.

- **`markup`** — besides a plain number or Excel-formula string, `markup`
  may be the object form, **on a pack that opts in** with
  `markup_by_type: true` in its `vocabulary.yaml`:

  ```yaml
  markup:
    overhead: { labor: 0.12, equipment: 0.10, material: 0.05, subcontract: 0.03 }
    profit:   { labor: 0.12 }
    bond_pct: 0.012
  ```

  Named rows (here `overhead`, `profit`) hold fractions by cost type
  (`labor` / `equipment` / `material` / `subcontract`, each `>= 0`);
  `bond_pct` is the bond as a fraction of the bid (`0 <= bond_pct < 1`).
  This form is usable only by a pack that lays out its own markup sheet to
  read the fractions into cells, which is what `markup_by_type: true`
  promises. On every other pack the schema accepts only a number or formula,
  and the build refuses an object markup by name ("markup by cost type needs
  a pack that opts in (vocabulary markup_by_type: true) and lays out its own
  markup sheet"). `summarize()` (the pure-Python pricer) refuses it on any
  pack, by name: "summarize prices a markup number or formula; markup
  by cost type is priced in the workbook by a pack that lays out a markup
  sheet".

  A pack that sets `markup_by_type: required` instead goes further: the
  schema renders ONLY the by-type object (no `oneOf` with a plain
  number/formula), so a plain `markup` is refused outright at
  `validate_spec` — and, independently, the builder itself refuses a non-dict
  `markup` by name, in case something ever calls `generate()` without
  validating first. Fieldbook sets `required`: it lays out its own Markup
  sheet and nothing else makes sense there.

- **`cost_codes`** (top-level, `[{code, description}]`): the org's cost-code
  list. `scaffold` copies it from the pack seed's `cost_codes`. A pack that
  lays it out reads it — fieldbook's Codes sheet makes it the task headers'
  code dropdown (plus any task code not on it) and its check 9 flags a task
  whose code is not on it; every other pack ignores it.

- **`items[].unbalance`**: dollars moved **onto** this item's bid (negative:
  off it). There is no engine-level check that an estimate's unbalances net
  to zero — a pack's own Checks sheet is where that belongs.

- **`labor[].notes`** (a list of strings): task notes, meant to be shown
  under the task's header row — distinct from `note`, the single aside meant
  for the title row itself. The engine renders neither on its own: a pack
  shows them only if one of its units prints `p.notes` / `p.note` (for
  example a `repeat: p.notes` row in the task-block unit).

- **`labor[].lines`** (the task's own cost lines, shaped like a
  `cost_detail`'s own `lines:`): `cost_type` (`material` | `subcontract` |
  `equipment` | `other`), `name`, `uom`, `qty`, `unit_price`, and the
  `source` / `vendor` below. A unit that prints a task's lines by
  cost-type column reaches the right column with `if_it: {cost_type:
  material}` (see `if_it:` above).

- **`cost_details[].lines[].source`** (`quote` | `plug`, default `plug`
  when absent) and **`.vendor`** (free text): `quote` means the line is
  priced from a named vendor's quote; `plug` means it is still the
  estimator's own number, yet to be chased. The same two keys are legal on
  a `labor[].lines` task line.

## `vocabulary.yaml` — required keys

| key            | required                  | what it is |
|----------------|---------------------------|------------|
| `trades`       | always                    | list of trade codes a crew row may name |
| `cost_blocks`  | always                    | list of cost-block codes an item may carry |
| `slot_pattern` | always                    | regex a labor slot must match (e.g. `"^[0-9]{2}$"`) |
| `defs.takeoff` | always                    | JSON Schema for an item's `takeoff:` block |
| `defs.spreads` | always                    | JSON Schema for an item's `spreads:` block |
| `foreman_trade`| only with `supports: summarize` | the trade whose days roll up as foreman days |
| `item_rules`   | optional                  | extra conditional schema rules (e.g. "a line item requires a takeoff") |
| `defs.rebar_spread` | optional             | omit it and the field is not permitted at all |
| `defs.schedule`| optional                  | omit it and a plain object is accepted |
| `markup_by_type` | optional (`true` \| `false` \| `"required"`, default `false`) | `true`: `markup` may be a plain number/formula OR the by-type object (see "markup" below). `"required"`: the schema renders ONLY the by-type object — a plain number/formula markup is refused, both at `validate_spec` and (independently) by the builder. `false`/omitted: plain number/formula only, as every pack had before this. |

Schema you supply may only `$ref` within the composed document (a `$ref` must
start with `#`).

## `seed.yaml` — required blocks

Both blocks below are **required**. `scaffold`, `apply-takeoff` and `compact`
read their keys directly, so a pack missing either is refused at load rather
than failing partway through someone's scaffold.

### `seed.scaffold`

| key                   | what it is |
|-----------------------|------------|
| `default_item_recipe` | recipe a scaffolded bid item uses (must name a recipe in `recipes.yaml`) |
| `rate_host_recipe`    | recipe for the injected rate-table host sheet (must name a recipe) |
| `rate_host_sheet`     | that sheet's name |
| `rate_host_prefix`    | sheet-name prefix for the rate host |
| `default_prefix`      | sheet-name prefix for every other item |
| `first_slot`          | the labor slot a skeleton block starts at (must match `slot_pattern`) |
| `placeholder_takeoff` | *optional*: `{kind, fields}` for a zeroed takeoff block, when the default item recipe needs one. `kind` must be in `defs.takeoff`'s `kind` enum. Omit it when the recipe carries its own takeoff shape. |
| `first_cost_code`     | *optional*: the `cost_code` scaffold gives its skeleton task. Set it when the vocabulary requires a cost code on every labor block (fieldbook does); without it a scaffolded spec fails the pack's own schema. |
| `rate_host_is_bid_recipe` | *optional*, `true`/`false` (default `false`): set it when `rate_host_recipe` is also an ordinary bid-item recipe because the rate table lives elsewhere (fieldbook: `lump_sum`, rates on its Rates book sheet). Then only the scaffold-injected host (item_no `RATES`) is the rate host, so `scaffold-save` saves the pack's lump-sum bid items (mobilization among them) and `apply-takeoff` lists them when no takeoff row matches. Unset, every item of `rate_host_recipe` is the rate host and is skipped by both. Checked at load. |
| `default_markup`      | *optional*: the `markup` value a fresh scaffold starts with, in place of the plain `0` every other pack keeps. Set it when the vocabulary requires markup by cost type (`markup_by_type: required`, fieldbook does) — a non-empty object such as `{bond_pct: 0}` is enough, since every other percentage defaults to 0. |

### `seed.takeoff_mapping`

| key             | what it is |
|-----------------|------------|
| `kind`          | the takeoff kind apply-takeoff writes (must be in `defs.takeoff`'s `kind` enum) |
| `line_fields`   | non-empty list of field names; every line is zero-initialised across all of them |
| `section_types` | non-empty map of a CanonicalTakeoff `section_type` -> `{cy: <field>, cf: <field>}`, optionally `label_prefix`. Both fields must appear in `line_fields`. |

### Other seed keys (optional, read by scaffold)

| key                 | what it is |
|---------------------|------------|
| `rate_table_trades` | the scaffold's rate table, every row at rate 0: a resource name (a labor rate row) or `{trade: NAME, kind: equipment}` (an equipment rate row; `kind: labor` is the default). Checked at load. |
| `cost_codes`        | `[{code, description}]`, the org's cost-code list; scaffold copies it into the spec's own `cost_codes`. Checked at load. |
| `default_crew`      | the skeleton task's crew |
| `crews`             | the spec's crew table |

`compact`'s new-row stub carries the same skeleton task (`first_slot`,
`first_cost_code`, `default_crew`) when the vocabulary requires every item to
carry `labor` (an unconditional `item_rules` entry with `required: [labor]`, as
fieldbook's is); otherwise its `labor` is empty.

## Referring to another sheet

Inside a unit, `{ref:UNIT.EXPORT}` reads an address published by a unit on the
**same sheet**. Put a sheet name and a `!` in front of it and it reads another
sheet instead:

```yaml
B: { formula: "=ROWS({ref:'Crew Rates'!rate_sheet.table})" }
C: { formula: "={ref:{p.target_sheet}!item_total.grand_total}" }
```

The sheet may be written bare or quoted, and may arrive in a param (params
expand first, the ref resolves after). It expands to `'Crew Rates'!$A$2:$B$6`
— always a sheet-qualified address. An apostrophe in a sheet name is doubled
on the way out and undoubled on the way in, as Excel spells it, so
`Bob's Sheet` renders `'Bob''s Sheet'!$A$1`.

**Order does not matter.** Every sheet is laid out first, publishing its
`exports:`; cells are resolved afterwards in a single pass. A reference may
name a sheet that lands *later* in the workbook as readily as an earlier one.

**It never fails quietly.** A reference that does not resolve raises, naming
the reference, the sheet/cell/unit it was written in, the pack, and what the
target sheet actually publishes. `optional:` does not swallow it. When a cell
should render only if its target exists, say so: `if_ref: "SHEET!UNIT.EXPORT"`.

**Cross-sheet ref, or a `globals:` entry?** A declared global is a *name*: one
address, promoted from exactly one sheet (the engine refuses a second
promotion), spelled identically everywhere, and re-pointed by editing
`recipes.yaml` alone — that is what the rate table wants to be. A cross-sheet
ref is an *address written where it is used*: it names its target sheet on the
spot, so it can differ cell by cell and can read a sheet whose name comes from
the estimate config. Many units sharing one anchor → a global. One unit
wanting one particular other sheet → a cross-sheet ref.

## The fieldbook pack

`packs/fieldbook/` is a complete estimate format, designed from scratch
(spec: `docs/superpowers/specs/2026-10-16-fieldbook-format-design.md`). Every
dollar is classified Labor / Equipment / Material / Subcontract from the crew
row up to the bid; cost codes are the unit of work; the Bid Form matches the
agency's arithmetic; live checks say what is wrong. It is the bundled default,
so its example builds with no `--format`:

```bash
est-estimate build packs/fieldbook/examples/demo-pipeline.estimate.yaml -o demo.xlsx
```

**Sheets**, in order: Bid Form (unit price = `ROUND(bid / qty, 2)`, amount =
qty × unit price, a status strip of passing checks — no internal cost figure,
not even a plug total, appears here) · Cost Summary (per item: MH, the four
cost types, direct, plugs, markup, unbalance, bid; its totals also carry the
plug $ and plug % of direct that the Bid Form carries none of) · Markup
(overhead / insurance / profit by cost type, the bond, per-item unbalance) ·
Checks · Rates (one table, labor and equipment by full name) · Codes (hidden:
the org's code list — the spec's `cost_codes` — then each task code not on it,
every code once; the task headers' code dropdown) · one sheet per bid item.

**An item sheet** is a header band, scope notes, the takeoff (with a plan
reference per row and a ✓ tie to bid qty), a recap of each task, and one task
block per cost code: header (code and description), notes, crew rows, cost
lines, subtotal, and an `END` marker row. Inputs are blue on cream; everything
else is a formula. A crew row's cost lands in Labor or Equip by the resource's
Kind on the Rates sheet; a cost line's in Equip, Matl (also `Other`) or Sub by
its Type cell.

**Round-trip tags.** Every laid-out row carries a hidden kind tag (column Q:
`ITEM`, `NOTE`, `HEAD`, `TAKEOFF`, `RECAP`, `TOTAL`, `TASK`, `CREW`, `LINE`,
`END`, `SUBTOTAL`). Rows inside a task block also carry the block's cost
code, as a formula in column R — `=A{r}&""` on the TASK row, `=R{r-1}` below
it — so a task block copied and pasted in Excel follows its own header's
code. The `END` row (a calm, italic "insert new lines above this row" cue,
no amounts) closes every task block, placed so that a copied CREW/LINE row
pasted in right above it lands inside the subtotal's range — Excel grows a
range whose end anchor sits at the insertion point, which is what makes
"insert, don't append" actually total the pasted row. The Rates table ends
with its own insert-above marker row the same way, so a rate pasted in
above it lands inside both the crew-resource dropdown and the crew VLOOKUP
range (the Markup sheet's three rows are fixed by design — see "Limits,
today"). Columns S and T are helper flags the Checks sheet sums. The code,
resource, Type and Source cells are strict dropdowns. No sheet is
protected: the workbook is edited by copy and paste.

**Checks** (one row per rule per item, except rule 4 which is pooled): 1
takeoff total = bid qty · 2 every crew resource has a rate · 3 every cost
line has a qty and a unit price · 4 unbalance nets to zero (all items at
once) · 5 the recap ties to the detail rows (a `SUMIF` over the item's kind
tags) · 6 per item, Bid Form amount = Cost Summary bid (within the
unit-price rounding) · 7 no cost line without a code · 8 no crew pairs an
operator-included machine with an Equipment Operator row · 9 every task's
cost code is on the org's code list (laid out only when the spec carries
`cost_codes`).

**Panes and printing:** an item sheet keeps its header band in view
(`freeze: A2`) and prints landscape, one page wide, with the band on every
page; the Bid Form prints portrait, one page wide, its heading and column
heads repeated; Cost Summary, Checks and Rates keep their column heads in
view.

**What it asks of a spec:** every item has at least one task and every task a
`cost_code`; a `line_item` has a takeoff (`linear`, `count`, or the
`measured` lines apply-takeoff writes), a `lump_sum` none; cost lines live in
tasks (`labor[].lines`) — item-level `cost_details` and `spreads` are refused;
`markup` must be the by-type object (`markup_by_type: required`) — a plain
number or formula is refused outright, not merely unread.

**Limits, today:** the Markup sheet lays out exactly three rows — overhead,
insurance, profit — and refuses to build a spec whose markup names another
(fieldbook lays out markup rows overhead, insurance and profit only); unlike
the Rates table, those three rows are fixed by design — inserting a row on
the Markup sheet does not add a markup row, there is no insert-above marker
there, and there is no plan to add one; read-back does not read the Codes
sheet — a code typed onto it in Excel is offered by the dropdown, but reaches
the spec only as the code of the task that uses it (add it to `cost_codes` to
put it on the org's list); every
task needs at least one crew row, so a subcontract-only task (cost lines, no
crew) cannot be expressed — read-back reports deleting a task's last crew row
as a problem; no `supports:` — `summarize` would price a different bid.

**Round trip: reading Excel edits back.** Estimators edit the workbook, not the
YAML; `est-estimate read-back` turns their edits back into the spec, which stays
the source of truth for rebuilds and `bm-sync`:

```bash
est-estimate read-back bid.estimate.yaml bid.xlsx                 # report only
est-estimate read-back bid.estimate.yaml bid.xlsx --write         # then write the spec
```

It prints a Markdown report (`--report FILE` saves it too) and writes nothing
unless `--write`, which first saves `bid.estimate.yaml.bak-YYYYmmdd-HHMMSS` and
then edits the spec in place with ruamel.yaml's round-trip mode: comments, key
order, quoting and line endings survive; whitespace ruamel re-emits its own way
does not — padding and alignment inside and before a one-line `{ ... }` or
`[ ... ]`, and blank lines between list rows where rows were added or deleted;
with nothing to change, nothing is written. It reads and writes the spec exactly
as `build` (PyYAML, YAML 1.1) reads it: a plain `includes_operator: no` is
`false`, and a value typed in Excel that YAML 1.1 would misread written plain
(`Yes`, `Off`, `1:30`) is written double-quoted; a write that would not read back
as the merged spec is refused. It reads workbooks built with fieldbook or with a
pack that declares `derived_from: fieldbook` (see the manifest section), and
resolves the pack the way `build` does: `--format PATH`, then the org profile's
`estimating.format`, then the bundled fieldbook. It refuses (exit 2) a file that
is not a workbook, a workbook without an `estimate_format` stamp, one stamped by
another pack than the one resolved (pass `--format`, which also takes the bare
name `fieldbook`, or set the profile) or by
another version of it, a pack outside the fieldbook family, one whose item
sheets are not the spec's items, and a spec that does
not itself build or that YAML 1.1 reads in a way that cannot be reconciled (a
mapping key `yes:`). `build` also stamps the workbook with the spec's
fingerprint (`estimate_spec_sha`); a workbook built from an older version of the
spec — another read-back, a hand edit or a `bm-sync` fetch since — would
silently undo those newer edits, so that is a problem unless `--force` (then a
notice). A YAML anchor shared by two places (`crew: &c` … `crew: *c`) is
expanded, with a notice, so an edit to one place does not land in both. It walks each item sheet by the kind tag — a
`TASK` row opens a block, `END` closes it — never by the code formulas, so
nothing needs recalculating. A pasted block whose header shows a new code is a
new task; a code retyped in a block's header (exactly one code gone and one new
code at the same position in the item) is a rename — "task 02-100 renamed to
02-150" — that keeps the task's slot and the fields the workbook does not show;
a whole-block reorder (nothing else edited) is reported and applied, never
silently dropped; crew rows, cost lines, takeoff rows and rates
are matched to the spec by name, in order — a task's crew rows or cost lines
that only changed places read as "crew reordered" / "lines reordered" — (number-like text matches the way the
builder's own conversion reads it back, so a cost code `"31.20"` still matches
the cell `31.2`), so a new, deleted or retyped row reads as exactly that, and a
tagged crew or cost-line row cleared down to all-blank cells reads as removed
(one notice) rather than a pile of blank-field problems; an input is unchanged
while it holds what the build wrote, so an untouched workbook reads back to the
same spec. Fields the workbook does not show (a task's `slot`, an item's
recipe) carry over unchanged. The report lists:

- **changes** — new, removed and reordered tasks, crew rows, cost lines,
  takeoff rows and rates, and every changed input (bid qty, takeoff rows, task
  description and notes, count, days, qty, unit, unit price, Type, Source,
  vendor, unbalance, markup %, bond, rates with their Kind and breakdown, hours
  per crew-day, bid date — clearing the bid date removes it from the spec
  rather than leaving a blank string);
- **needs you** — crew resources with no rate row (matched case-insensitively,
  the way Excel's own `VLOOKUP` does): applied as typed, and check 2 stays ✗
  until a rate is added above the Rates marker row;
- **formula cells typed over** — ignored, the rebuild restores them (item
  sheets by row kind; Bid Form, Cost Summary, Markup and Checks against a fresh
  build of the spec); a plainly inserted Rates row's blank $/hr is not reported
  as "cleared" — nothing was there to clear;
- **untagged rows** — pasted from outside the workbook: listed, never read;
- **notices** (non-blocking) — text that looks editable but is not read back
  (the item description and unit on an item sheet, the project name on the Bid
  Form: change those in the spec / bid schedule); a resource typed in another case; a flat rate
  or "includes operator" typed where it is ignored (a breakdown rate's flat
  rate column, a labor rate's operator column); a row below the Rates marker,
  outside the rate table; a missing "Bid date" row or Markup Total row (the
  rest of each sheet is still read correctly); an expanded YAML anchor; a stale
  workbook applied with `--force`;
- **problems**, any of which blocks `--write` (exit 1): a blank or non-numeric
  required input (a blank markup %, bond or unbalance simply means 0; a blank
  Source on a cost line is a problem, never a silent plug), free
  text in the bid date that is not a date, an input
  formula that refers to cells, a Type/Source/Kind not on its
  dropdown, two blocks showing one code, a resource the pack does not name, a
  Markup grid row other than Overhead/Insurance/Profit (Excel still prices it,
  so it must be folded in or deleted, never silently dropped), a workbook built
  from an older version of the spec (unless `--force`), or an updated spec the
  pack would refuse to build (explained where the refusal is a known one — "task
  02-510 has no crew rows left" — with the schema message under it).

A resource typed in another case (`pipelayer`) reads as the rate row's name —
Excel's dropdown and `VLOOKUP` ignore case — with a notice. The reader's map of
the grid lives in `readback/layout.py`; a test reads `units.yaml` and fails if
the two drift apart.

Its tests evaluate the built workbook with `pycel` (the `test` extra) and
fail, not skip, without it under `CI=true`.

## Checking your pack

```python
from estimating_tools.estimate_spec.format_pack import load_pack

pack = load_pack("path/to/my-pack")     # raises FormatPackError, naming the defect
```

Then render the pack's own example and look at it:

```bash
est-estimate build my-pack/examples/sample.estimate.yaml -o /tmp/sample.xlsx \
    --format my-pack
```

The workbook's `estimate_format` custom document property records
`<name> <version>`, so any file traces back to the pack that produced it.
