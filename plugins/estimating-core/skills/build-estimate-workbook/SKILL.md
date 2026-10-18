---
name: build-estimate-workbook
description: Generate an Excel estimate workbook from a YAML estimate spec using the estimate_spec builder — choose recipes/units, resolve placeholders, and write the .xlsx. The deliverable is a local spreadsheet file, not BidSheet.ai writes (for assembly breakdowns on BidSheet.ai items use build-assemblies instead).
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

> **Display contract:** Show `render` output to the user **verbatim in a fenced code block** — never reformat it, add/remove columns, or substitute your own table; `parse` depends on the exact shape. If the `open_artifact_editor` tool (artifact-editor server) is available, ALSO call it — `open_artifact_editor(markdown=<rendered, verbatim>, title="<title>", editable=<false for read-only plan renders>)` — and tell the user to edit in the inline panel and click **Save & send to chat**; their edits arrive as a chat message. In the terminal, the same tool instead opens the editor in the user's web browser and returns the saved block directly in the tool result — parse and push it when it returns (Save = the user's consent). If the wait expires, call `collect_artifact_edits` after the user says they've saved. If the tool is missing or errors, show the live page built by:
>
> ```python
> from estimating_tools.artifacts_html import to_editable_html
> page = to_editable_html(rendered, title="<title>")
> ```
>
> Prefer the host's native artifact mechanism (present `page` as a live HTML artifact); if the host only renders files, write it to `<slug>.artifact.html` (named after the artifact so successive renders don't overwrite each other). For editable artifacts, point the user at the page's **Copy edited artifact** button; for read-only plan renders, pass `editable=False` (the page has no button). Run `parse` only on text the user provides — the Save message, the pasted export, or their edited block — never on your own restatement of it.

# Build an Estimate Workbook

Use this when asked to produce a spreadsheet estimate from a structured spec. Also
drives inline edits of one item at a time — see the alternative workflow below.

See also, in this skill's `references/` directory:
- `estimate-spec-model.md` — the estimate-spec four-layer model (tokens /
  units / recipes+spec / schema), the placeholder mini-language, landmarks,
  and why the generator is two-pass.

## Which generator

Two workbook generators ship here. Choose by audience — neither supersedes
the other:

- **`~/.estimating/bin/est-estimate build <spec.yaml>`** (the spec-YAML builder; workflows
  below) — the org-native template workbook. Layout and styling come from
  the shipped four-layer model (see `references/estimate-spec-model.md`)
  and are profile-governed: the output is the workbook shape the org's
  estimators build in by hand.
- **`~/.estimating/bin/est-estimate cip-buildup <config.json>`** — the BM-aligned CIP
  structure-buildup workbook: a normalized `Rates` sheet, one buildup
  sheet per structure with generic cost blocks, and a sub-spread that
  mirrors BidSheet.ai work-package quotes. Use when the deliverable is a
  structure-by-structure cast-in-place buildup meant to line up with the
  BidSheet.ai estimate model. See "CIP buildup usage" below.

## Inputs
- A `*.estimate.yaml` config (see `packages/estimating-tools/estimating_tools/estimate_spec/packs/fieldbook/examples/` for a sample) — hand-authored, or scaffolded from an intake briefing (preferred, below).
- A **format pack** decides what the workbook looks like: a directory with `format.yaml`
  naming its `units.yaml` (structure), `tokens.yaml` (style), `recipes.yaml` (composition),
  `vocabulary.yaml` (permitted trades, cost blocks, takeoff kinds) and `seed.yaml` (what a
  fresh spec starts with). Packs are data only. Resolution: `--format <dir>` on the command,
  else the org profile's `estimating.format`, else the fieldbook pack bundled with the tool. A pack
  that is named but missing or invalid is an error, never a silent fall back.
  A pack declares which extra tools (`summarize`, the artifact editor) it supports in
  `format.yaml`'s `supports:` list; those tools refuse any other pack.
- With no pack named, an estimator gets **fieldbook**, the bundled default
  (`estimate_spec/packs/fieldbook/`, example at
  `packs/fieldbook/examples/demo-pipeline.estimate.yaml`): a complete, generic format — a
  Bid Form that matches the agency's arithmetic, a Cost Summary by cost type, Markup by
  cost type, live Checks, one Rates table (labor and equipment by full name), the org's
  cost-code list as the code dropdown, and one sheet per item with a task block per cost
  code. The estimator edits the workbook in Excel and you read the edits back into the
  spec (see "read Excel edits back" below). It declares no `supports:`, so `summarize` and
  the inline item editor refuse it.
- An org adopts its own format by naming its own pack — in its profile's
  `estimating.format` (the `create-org-profile` skill sets it), or per command with
  `--format <dir>`. The quickest start is a copy of `packs/fieldbook/` with the org's own
  trades (`vocabulary.yaml`) and its rate-table trades and cost-code list (`seed.yaml`);
  `packs/README.md`, shipped beside it, is the full contract. `scaffold`,
  `apply-takeoff` and `scaffold-save` write files, so they refuse the bundled pack unless
  something names a pack — `--format <estimate_spec>/packs/fieldbook` is a valid choice.
  The demo pack that used to be the default is retired.

## Workflow — scaffold from a briefing (preferred)

When the project went through `intake-project` / `project-briefing` (there is a
`manifest.json` with a bid frame and a `Briefing/structures.yaml`), never
hand-build the frame — scaffold it:

1. **Optional — fetch BM bid-item scaffolds to `scaffolds.json`.** If the
   BidSheet.ai MCP is connected, prefill labor/crews/cost_details from the org's
   scaffold catalog. Collect the bid frame's item codes (`manifest.json` →
   `bid_frame[].item_code`), then call `list_bid_item_scaffolds` (or
   `lookup_bid_item_scaffold` per item_code) and transform each hit into one
   entry of OUR schema — fragments of the estimate-spec item schema itself:

   ```json
   [{"item_code": "FTG-CONC",
     "source": "bm:scaffold:<id>",
     "labor": [ {"slot": "A", "description": "...", "crew": [{"trade": "FORE", "days": 0}]} ],
     "crews": [ {"id": "...", "members": [{"trade": "FORE", "count": 1}]} ],
     "cost_details": [ {"name": "EQUIPMENT", "lines": []} ]}]
   ```

   Write the list to `scaffolds.json`. The CLI validates this schema and
   rejects drift — if the server shape differs, transform, don't pass through.
   Skip this step entirely when offline; the org profile's
   `estimate_scaffolds.yaml` (same entry shape, `scaffolds:` list) and the
   blank skeleton are the fallbacks, in that order.

2. **Scaffold the spec:**
   ```bash
   ~/.estimating/bin/est-estimate scaffold --manifest <project>/manifest.json \
       --structures <bid_dir>/Briefing/structures.yaml \
       [--scaffolds scaffolds.json] [--items all|structures|<csv>] \
       -o <bid>.estimate.yaml
   ```
   Default `--items structures` selects rollup-referenced items plus
   mobilization — the self-perform frame. Item `qty` is the OFFICIAL agency
   quantity; each item carries a `scaffold_meta` provenance block. Re-running
   onto an existing file requires `--merge` (updates scaffold-owned fields
   only; hand edits are never touched).

3. **Review the skeleton with the user** — recipes, sheets, prefilled labor.

4. **Apply the measured takeoff** (after `quantity-takeoff` / `bim-to-takeoff`, the latter from the calc-bim plugin):
   ```bash
   ~/.estimating/bin/est-estimate apply-takeoff <bid>.estimate.yaml \
       --takeoff <takeoff.json> --report apply-report.md
   ```
   Quantities become the measured figures and each item's takeoff geometry is
   rebuilt from the takeoff's per-element breakdown. Hand-edited items are
   skipped (pass `--force` to overwrite); show the report — it carries the
   official-vs-measured deltas and every unmatched row/item.

5. **Build** (step 2 of the hand-authored workflow below) and price: enter
   labor days/rates on the generated blocks — no frame surgery.

## Workflow — hand-authored spec (fallback)
1. Confirm or draft the estimate YAML: top-level sheets, the recipes each sheet
   composes, and the unit rows. Validate with `~/.estimating/bin/est-estimate scaffold`'s validator
   (the schema is composed from the plugin skeleton and the pack's vocabulary).
2. Build the workbook:
   ```bash
   ~/.estimating/bin/est-estimate build <path/to/your.estimate.yaml> -o <output.xlsx> [--format <pack-dir>]
   ```
   (run `~/.estimating/bin/est-estimate --help` for exact flags; `~/.estimating/bin/est-estimate <spec.yaml>`
   without the subcommand still builds). `--format <pack-dir>` renders against
   a specific format pack instead of the org profile's `estimating.format` or
   the bundled default — see `## Inputs` above. `--no-lint` skips
   consumer-registered pre-render config checks.
3. Open the result and sanity-check totals, exports, and landmarks.
4. Iterate on the YAML and re-run to regenerate — or, on a fieldbook workbook, let the
   estimator edit it in Excel and read the edits back into the spec first (below).

## Workflow — edit one item inline (alternative)

**Requires a pack declaring `supports: artifact`.** `render_item` and `parse_item`
refuse any other pack with a `FormatPackError`, and the bundled fieldbook pack declares
no capabilities at all — so on a default install this workflow errors on the first
call. Resolve the pack first and check, before offering the workflow:

```python
from estimating_tools.estimate_spec.format_pack import resolve_pack

pack = resolve_pack(format_dir_or_None)      # --format, else the profile, else bundled
if "artifact" not in pack.supports:
    ...   # say that this pack does not support inline item editing, and edit the
          # YAML directly (the hand-authored workflow above) instead
```

Use this when the user wants to tweak one item (a single Excel sheet's worth of estimate
— quantities, crew, cost-detail lines) without opening the YAML in an editor.

1. Load the spec:

   ```python
   import yaml

   spec = yaml.safe_load(open(spec_path).read())
   ```

2. Pick the item and render it:

   ```python
   from estimating_tools.estimate_spec.artifact import find_item, render_item

   item = find_item(spec, item_no)              # raises KeyError with a locator if missing
   print(render_item(item, pack))               # the pack from the gate above
   ```

3. The user edits and sends it back — the Save message, or a pasted block. Parse it with the caller's `item_no`:

   ```python
   from estimating_tools.estimate_spec.artifact import parse_item, replace_item

   edited = parse_item(user_edited_text, item_no=item_no, pack=pack)
   spec = replace_item(spec, item_no, edited)
   ```

   `parse_item` runs `jsonschema.validate` against the item subschema; surface any
   `ValueError` to the user and ask them to correct.

4. Write the spec back to disk and re-run `est-estimate` to regenerate the workbook:

   ```bash
   ~/.estimating/bin/est-estimate <path/to/spec.yaml> -o <output.xlsx>
   ```

## Workflow — read Excel edits back into the spec (fieldbook)

A workbook built with the fieldbook pack (the bundled default, or a copy of it named with
`--format` / `estimating.format`) is edited in
Excel: the estimator types inputs and copies and pastes rows and whole task blocks. The spec
stays the source of truth, so those edits are read back into it before the next rebuild or
`bm-sync`. When the user says "read it back" (or hands you an edited fieldbook workbook):

1. **Dry run.** Nothing is written:
   ```bash
   ~/.estimating/bin/est-estimate read-back <bid>.estimate.yaml <bid>.xlsx --report readback.md
   ```
   Exit 2 means refused — the file is not a workbook, was not built by fieldbook, was built by
   another fieldbook version, was built from a spec with other items, the spec itself does
   not build (or cannot be read the way `build` reads it), or `--report` names the spec or the
   workbook. Say why and stop; never edit the spec
   by hand to force it. Tell the user not to edit or re-save the workbook between this dry run
   and the `--write` in step 3: the write reads the workbook again, and must apply exactly what
   they reviewed.

2. **Show the report** verbatim in a fenced block, then walk the user through it:
   - **Problems** (exit 1): nothing will be written. Each line names a sheet row and what to fix
     there (a blank count, a formula in an input, two blocks with the same code, a blank
     Source, two Markup rows with one label, a Bond row whose label was changed). The user fixes them in Excel, saves, and you run step 1 again.
     One problem is not fixed in Excel: **"built from a different version of the spec"** — the
     spec changed after this workbook was built (another read-back, a hand edit, a `bm-sync`
     fetch), so applying it would quietly undo those newer edits (the Changes list shows them
     being reverted). Default: rebuild the workbook from the current spec and redo the edits
     there. Only if the user explicitly wants this workbook to win, add `--force` to steps 1
     and 3 (the problem becomes a notice) and walk them through every change it reverts first.
   - **Changes**: what the spec will take — new tasks (a pasted block with a new code), renamed
     tasks (a code retyped in place), new, removed and reordered crew rows, cost lines, takeoff
     rows and rates, and every changed input.
   - **Needs you**: crew resources with no rate row. Ask for each one's kind (labor or
     equipment) and $/hr. Best: the user adds the rate on the Rates sheet, above the "insert
     new rates above this row" row, saves, and you read back again. They may also go ahead —
     the resource is applied as typed and check 2 stays ✗ until a rate exists.
   - **Formula cells typed over**: ignored; the rebuild restores each formula, so what was
     typed there is lost. Say so.
   - **Untagged rows**: pasted from outside the workbook, so not read — never guessed. Ask the
     user to re-enter them into a copied crew or cost-line row inside a task block.
   - **Notices**: read, but worth a word — e.g. an edited item description, item unit or
     project name is not read back (change it in the spec / bid schedule), or a shared YAML
     anchor was expanded.

3. **Confirm, then write.** Only after the user says yes:
   ```bash
   ~/.estimating/bin/est-estimate read-back <bid>.estimate.yaml <bid>.xlsx --write
   ```
   It saves `<bid>.estimate.yaml.bak-YYYYmmdd-HHMMSS` next to the spec first, then edits the
   spec in place: comments, key order, quoting and line endings stay as they were; padding and
   alignment inside and before one-line `{ ... }` / `[ ... ]` are normalised, and blank lines
   between list rows can move where rows were added or deleted. Text YAML 1.1 would misread
   (`Yes`, `Off`, `1:30`) is written quoted, so `build` reads it as typed. With nothing to change
   it writes nothing, backup included.

4. **Rebuild** with the same pack the workbook was built with (step 2 of the hand-authored
   workflow above), and tell the user to reopen the workbook: the new tasks appear in the
   recap and the Checks sheet reads the rebuilt numbers.

5. **Optionally sync to BidSheet.ai** with the `bm-sync` skill. Its base snapshot is the spec
   as of the last BidSheet.ai fetch; when this read-back is the only edit since then, the
   `.bak-*` file from step 3 is that snapshot.

## CIP buildup usage

```bash
~/.estimating/bin/est-estimate cip-buildup <config.json> [-o <output.xlsx>]
~/.estimating/bin/est-estimate cip-buildup --init <path>   # write a sample config to start from
```

The config is JSON; start from `--init` and edit. Key behaviors:

- **`Rates` sheet is the single source of truth.** Every buildup formula
  pulls trade, equipment, material, and waste rates from it. Change a rate
  there; every structure follows. Never inline a rate on a buildup sheet.
- **One buildup sheet per structure**, with labor as seven lettered phases
  A–G, priced as crew-composition × days × hrs/day (from `Rates`, default
  8; crew $/hr = Σ trade-count × trade rate; no productivity factors).
- **Two takeoff modes** per structure: closed-box `L`/`W`/`H` with
  wall/base/deck thicknesses, or a component list of
  `{name, count, L, W, H}` prisms. A component `count` may be **negative**
  to deduct openings (box-outs, blockouts). The waste fraction applied on
  top comes from the `Rates` sheet.
- **EQUIPMENT and MATERIAL blocks** per structure, rates from `Rates`.
- **SUB-SPREAD** — subcontracted scope, mirroring BidSheet.ai work-package
  quotes. Shorthand: `rebar_cost` + `rebar_vendor` synthesizes a rebar
  subcontract line. Explicit form: a `subs` list of
  `{name, vendor, qty, unit, unit_price|amount, kind}` lines (`kind` tags
  e.g. rebar / earthwork). Rebar leaves the MATERIAL block only when it is
  actually subbed — `rebar_cost` set or a `kind: rebar` sub present; an
  earthwork-only `subs` list keeps the per-$/CY rebar line in MATERIAL.
- **Per-phase `days` overrides** — `days: 0` prices the phase to zero on
  that structure (the row remains, at $0 — e.g. no reinforcing phase on an
  unreinforced pad).
- **`labor_sections`** replaces the A–G phase taxonomy wholesale when the
  default doesn't fit (e.g. a five-phase breakdown).
- **Summary sheet**: per structure, Each × Qty = Extended.
- **Unknown config keys are refused.** A typo (`labour_sections`) would
  otherwise silently price the defaults — a silent-wrong-bid class — so
  the generator errors instead of ignoring.
- All inputs are yellow-filled literals; every total is a live formula —
  which means the verification rule below applies.

## Verify before trusting the totals

A freshly generated `.xlsx` has **unevaluated formulas**: openpyxl writes
formulas but never computes them, so every total cell is empty until Excel
(or LibreOffice) opens the file and recalculates. Never read a bid number
out of a just-generated workbook, and never tell the user a total you got
by parsing one.

For the spec-YAML path, get the number before anyone opens Excel by
pricing the spec in pure Python:

```bash
~/.estimating/bin/est-estimate summarize <spec.yaml>
```

**Requires a pack declaring `supports: summarize`.** The command refuses any
other pack with a `FormatPackError` naming it, and the bundled fieldbook pack
declares no capabilities — so `summarize` is not available on a default
install. When the pack does not support it, say so and fall back to opening
the workbook in Excel or LibreOffice to recalculate; never quote a total read
from the unopened file.

It prints the per-item totals and the grand total, mirroring the workbook's
arithmetic (crew × days × hrs/day, waste, cost-detail carries, sub
bundles, markup). The waste factors and the crew factor come from the pack,
not from this tool. It takes the estimate-spec YAML, not a `cip-buildup`
config — for a CIP buildup workbook, recalculate by opening the file in
Excel or LibreOffice before quoting any total.

**Caveat — state it to the user:** `summarize` proves the spec's internal
arithmetic is consistent, NOT that the rates are current. An independent
rate check (e.g. against the BidSheet.ai rate library) is still the
estimator's job.

## Notes
- `measure-plans`, `dxf-to-bim`, `bim-to-takeoff`, and `show-structure-earth` ship in the **calc-bim plugin** (same estimating-platform marketplace as this plugin). If they are not among your available skills, tell the user this workflow needs the calc-bim plugin installed (`/plugin` -> estimating-platform -> calc-bim) and offer to continue with the bundled `est-bim` CLI directly.
- The builder is deterministic; all judgment is in choosing recipes/units and
  reviewing outputs.
- Do not hardcode org rates here — rates belong in the user's estimate YAML or
  the BidSheet.ai rate library (see the `estimating-reference` skill).
