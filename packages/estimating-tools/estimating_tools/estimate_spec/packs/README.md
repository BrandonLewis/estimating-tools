# Writing a format pack

A **format pack** is the data that decides what an estimate workbook looks like.
The engine (`estimating_tools.estimate_spec`) supplies the mechanism; the pack
supplies the shape, the styling and the vocabulary. Packs are **data, never
code**: every document is read with `yaml.safe_load` / `json.loads`, and nothing
a pack names is imported or executed.

Two packs ship with the tool. `packs/demo/` is the default and the shortest
complete pack there is — read it alongside this page. `packs/fieldbook/` is a
full estimate format built on every feature below; see "The fieldbook pack" at
the end. Name it with `--format` (it becomes the default in a later release).

A pack is resolved, in order, from `--format <dir>`, then the org profile's
`estimating.format`, then the bundled demo pack. **A pack that is named but
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
```

Every `files:` path must stay inside the pack directory. An unknown `files:`
key is refused.

`provenance: authored` is asserted of every pack under `estimate_spec/packs/`
in this repo, as a guard against a customer's real format being committed here
by accident. `load_pack` does not require it, so your own pack need not carry
it.

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

Six more engine features, all pack-opted and all inert unless a pack (or the
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
`units`, `hidden`, `hidden_columns` — the same shape a recipe has, except a
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
| `default_markup`      | *optional*: the `markup` value a fresh scaffold starts with, in place of the plain `0` every other pack keeps. Set it when the vocabulary requires markup by cost type (`markup_by_type: required`, fieldbook does) — a non-empty object such as `{bond_pct: 0}` is enough, since every other percentage defaults to 0. |

### `seed.takeoff_mapping`

| key             | what it is |
|-----------------|------------|
| `kind`          | the takeoff kind apply-takeoff writes (must be in `defs.takeoff`'s `kind` enum) |
| `line_fields`   | non-empty list of field names; every line is zero-initialised across all of them |
| `section_types` | non-empty map of a CanonicalTakeoff `section_type` -> `{cy: <field>, cf: <field>}`, optionally `label_prefix`. Both fields must appear in `line_fields`. |

### Other seed keys (optional, read by scaffold)

`rate_table_trades`, `default_crew`, `crews`, `cost_codes`.

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
agency's arithmetic; live checks say what is wrong. Build its example with:

```bash
est-estimate build packs/fieldbook/examples/demo-pipeline.estimate.yaml \
    -o demo.xlsx --format packs/fieldbook
```

**Sheets**, in order: Bid Form (unit price = `ROUND(bid / qty, 2)`, amount =
qty × unit price, a status strip of passing checks — no internal cost figure,
not even a plug total, appears here) · Cost Summary (per item: MH, the four
cost types, direct, plugs, markup, unbalance, bid; its totals also carry the
plug $ and plug % of direct that the Bid Form carries none of) · Markup
(overhead / insurance / profit by cost type, the bond, per-item unbalance) ·
Checks · Rates (one table, labor and equipment by full name) · Codes (hidden:
the codes the estimate uses) · one sheet per bid item.

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
operator-included machine with an Equipment Operator row.

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
there, and there is no plan to add one; the Codes sheet lists the codes the
estimate's own items use, duplicates possible when more than one task shares
a code (de-duplicating it, and the dropdown it backs, is a later item); no
`supports:` — `summarize` would price a different bid.

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
