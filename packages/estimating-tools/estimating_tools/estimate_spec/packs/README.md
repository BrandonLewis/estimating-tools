# Writing a format pack

A **format pack** is the data that decides what an estimate workbook looks like.
The engine (`estimating_tools.estimate_spec`) supplies the mechanism; the pack
supplies the shape, the styling and the vocabulary. Packs are **data, never
code**: every document is read with `yaml.safe_load` / `json.loads`, and nothing
a pack names is imported or executed.

Only one pack ships with the tool — `packs/demo/`, a generic worked example.
Read it alongside this page; it is the shortest complete pack there is.

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
