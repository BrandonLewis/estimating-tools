# The estimate-spec model

How the spec-YAML workbook builder (`est-estimate build`) is put together:
a data-only description of an estimate workbook, rendered via openpyxl by
editing YAML, not Python. The shipped layer files live in
`packages/estimating-tools/estimating_tools/estimate_spec/`.

## The four layers

```
 tokens.yaml ─────────────┐   "fill = role, font = data-kind", named once
                          │
 units.yaml ──────────────┤   parametric functional units (item_header,
 recipes.yaml ────────────┤   labor_block, takeoff, …) + sheet archetypes
                          │
 <bid>.estimate.yaml ─────┤   the ONE hand-authored file: quantities,
                          │   crews, prices  (everything else is supplied)
                          │
 schema/estimate.schema.json   validates the hand-authored config
```

| File | Layer | What it owns |
|------|-------|--------------|
| `tokens.yaml` | 1 — style | Every fill/font/border/number-format, named (`input_yellow`, `rate`, `double_top`, …). Re-skin the whole estimate from here. |
| `units.yaml` | 2 — structure | The parametric units. Each is a stack of rows whose cells reference **style names only** (never hex). The repeating `labor_block` is the heart. |
| `recipes.yaml` | 3a — composition | Sheet archetypes (`cover`, `mob_item`, `standard_item`) = ordered lists of units. |
| `<bid>.estimate.yaml` | 3b — content | The only file an estimator edits (see `examples/`). |
| `schema/estimate.schema.json` | 4 — validation | JSON-Schema (Draft 2020-12) for the config. |

**Why this split:** a template workbook's two real conventions — *fill
encodes a cell's role*, *font color encodes the kind of number* — live in
exactly one place (`tokens.yaml`). Structure lives in `units.yaml`.
Estimator-specific numbers live in the config. Change a style once; every
sheet follows.

## How the generator works — and why two passes

```
config.yaml ──validate──▶ schema        (reject bad input early)
     │
     ▼
PASS 1 (layout): for each item, walk its recipe; drop each unit at the
     running cursor, recording every cell's row + each unit's landmarks
     and exports.
     │   (two-pass is required: SUMMARY references cost-detail blocks
     │    BELOW it, and the cover references each item sheet — all
     │    forward references.)
     ▼
PASS 2 (resolve + write): resolve every cell's {placeholders} against the
     now-complete export table, look up style names in tokens.yaml →
     openpyxl Font/Fill/Border, and write.
     ▼
  openpyxl Workbook ──▶ .xlsx
```

The generator never hard-codes a row number, color, or formula shape — it
reads them from these files. A handful of cross-sheet-shape decisions (the
TOTAL = sum-of-present-components, the SUMMARY lines built from the
cost-detail blocks, the `{rate_table}` address taken from wherever the MOB
sheet landed) are assembled by the builder because the sheet shapes
genuinely differ.

Note the generated `.xlsx` carries formulas that openpyxl never evaluates
— see the SKILL's "Verify before trusting the totals" section.

## Placeholder mini-language (resolved at build time)

| Token | Resolves to |
|-------|-------------|
| `{p.NAME}` | a unit **parameter** (`{p.slot}`, `{p.description}`) |
| `{it.NAME}` | current **repeat-item** field |
| `{r}`, `{r-1}`, `{r+2}` | the **absolute row** a cell lands on (arithmetic ok) |
| `{row:NAME}` | resolved row of a **landmark** (`mark:` / `mark_first:` / `mark_last:`) in this unit instance |
| `{rate_table}` | global anchor → the MOB sheet's embedded rate-table range, wherever it landed |
| `{item_qty}` / `{item_uom}` | this sheet's quantity / UOM cell |
| `{ref:UNIT.EXPORT}` | another unit's published `exports:` address **on this sheet** (e.g. `{ref:takeoff.total_cy}`) |
| `{ref:SHEET!UNIT.EXPORT}` | the same, on **another sheet** — expands to `'SHEET'!$A$1` (e.g. `{ref:Crew Rates!rate_sheet.table}`) |

## Cross-sheet references

`{ref:NAME}` reads the sheet it is written on. Adding a sheet before a `!`
reads another sheet instead: `{ref:'Crew Rates'!rate_sheet.table}` (quoted or
bare, and the sheet may be supplied by a param — `{ref:{p.target}!x.y}`).
It expands to a sheet-qualified address, `'Crew Rates'!$A$2:$B$6`; an
apostrophe in a sheet name is doubled the way Excel spells it, so `Bob's Sheet`
renders `'Bob''s Sheet'!$A$1`.

Order does not matter. Sheets are all laid out first, publishing their
`exports:`; every cell is resolved afterwards in one pass, so a reference may
name a sheet that comes **later** in the workbook as readily as an earlier one.
A reference that does not resolve is an error naming the reference, the sheet,
cell and unit it was written in, the pack, and what the target sheet does
publish — it is never a blank cell, and `optional:` will not swallow it. To
render a cell only when the target exists, say so with `if_ref:
"SHEET!UNIT.EXPORT"`.

**Cross-sheet ref or a declared global?** A `globals:` entry is a *name*: one
address, promoted from exactly one sheet, spelled the same everywhere it is
read, and re-pointed by editing `recipes.yaml` alone (the rate table is the
canonical case). A cross-sheet ref is an *address written at the point of
use*: it names its target sheet right there, so it can differ from one cell to
the next and can read a sheet whose name comes from the estimate config. Reach
for a global when many units want one shared anchor; reach for a cross-sheet
ref when one unit wants one specific other sheet.

## Landmarks

Landmarks are how a unit refers to its own rows without knowing where it
landed. A row tagged `mark: subtotal` can be referenced anywhere in that
unit instance as `{row:subtotal}`; `repeat:` rows expose `{row:NAME_first}`
/ `{row:NAME_last}`. This is what makes the units position-independent and
stackable.

## The repeating unit, generalized

`labor_block` (in `units.yaml`) is the lettered labor slot. Five parts:
**A** title → **B** production-factor table → **C** "Unit" driver row →
**D** crew composition (rate via `VLOOKUP` to the master rate table) →
**E** double-bordered subtotal + guard. The slot letter is just a label,
so an item may legitimately use only a subset of the slots.
