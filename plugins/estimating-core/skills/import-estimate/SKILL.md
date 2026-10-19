---
name: import-estimate
description: Free a legacy estimate export (e.g. an HCSS HeavyBid Excel file) into the open canonical estimate model — schedules, line items, item codes — saved as JSON.
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

> **Related:** the four spreadsheet importers (`import-rates`, `import-assemblies`,
> `import-directory`, `import-cost-codes`) share a `ProposedMapping` editable artifact for
> the column-mapping step (`estimating_tools.importers.mapping_artifact`). This importer
> currently parses legacy estimate formats directly; adopting the same artifact is a
> follow-up (see `docs/superpowers/specs/2026-07-05-editable-live-artifacts-design.md`;
> when adopted, apply the display contract from
> `docs/superpowers/specs/2026-07-12-artifact-display-contract-design.md`).

# Import an Estimate

Use this when asked to import or "liberate" an estimate from a legacy tool's
export file.

## Workflow
1. Confirm the export file path (e.g. an HCSS HeavyBid `.xlsx`).
2. Parse it into the open canonical model:
   ```bash
   ~/.estimating/bin/est-import <path/to/export.xlsx> -o <out.canonical.json>
   ```
   (run `~/.estimating/bin/est-import --help` for flags). The output is a `CanonicalEstimate`:
   a project plus one or more `schedules`, each a list of line items with
   `item_number`, optional `item_code`, description, quantity, unit, unit_price.
3. Review the summary (schedule count + item count) and open the JSON to spot-check.
4. The data is now free of the source app — offline, in an open format.

## Work packages and quote files (read-back)
When the estimate came from a fieldbook workbook with `Sub <package>` sheets, reading it back
(`~/.estimating/bin/est-estimate read-back <spec> <xlsx>`; `--format <pack-dir>` when the pack was derived from
fieldbook) carries the package choices into the spec's `work_packages` and writes vendor quotes typed
into the sheets as `CanonicalQuote` files in the quotes directory on `--write`. `~/.estimating/bin/est-estimate
packages init | sync | coverage` manage the packages themselves. Details: the
`build-estimate-workbook` skill.

## Notes
- Format detection is automatic; the importer dispatches to the matching adapter
  (HCSS HeavyBid today; more adapters are added on the same framework).
- This produces the open model only. To load it into BidSheet.ai (as a project
  with bid schedules and bid items), use the `push-estimate` skill — a separate,
  available step.
- Rates and persistence are not part of import — the canonical estimate is plain
  data you own.
- Full chain: `est-import` (parse) → `push-estimate` (structure into BidSheet.ai) →
  `price-estimate` (price the bid items from the import).
