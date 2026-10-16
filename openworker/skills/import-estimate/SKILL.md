---
name: import-estimate
description: Free a legacy estimate export (e.g. an HCSS HeavyBid Excel file) into the open canonical estimate model — schedules, line items, item codes — saved as JSON.
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

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
   est-import <path/to/export.xlsx> -o <out.canonical.json>
   ```
   (run `est-import --help` for flags). The output is a `CanonicalEstimate`:
   a project plus one or more `schedules`, each a list of line items with
   `item_number`, optional `item_code`, description, quantity, unit, unit_price.
3. Review the summary (schedule count + item count) and open the JSON to spot-check.
4. The data is now free of the source app — offline, in an open format.

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
