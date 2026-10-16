---
name: save-scaffolds
description: Save a priced estimate's items as BidSheet.ai bid-item scaffolds — est-estimate scaffold-save extracts name/cost-codes/production per item, the estimator confirms (plus optional assembly-template refs), then lookup → create-or-update via the BidItemScaffold MCP CRUD so scaffold-from-template prefills the next bid. Writes.
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Save Priced Items as Bid-Item Scaffolds

Use this after an estimate is priced and confirmed (`price-estimate`), to
bank each item's reusable structure — name, org cost codes, production
defaults, assembly refs — as `BidItemScaffold`s keyed
`(agency, bid_item_code)`. The next bid's scaffold-from-template
(`build-estimate-workbook` step 1) prefills from exactly these. Requires
the BidSheet.ai MCP.

## Inputs
- The priced `*.estimate.yaml` (the workbook spec the estimator confirmed).
- The agency slug and, when `cost_code` on the spec items is the org code
  rather than the agency code, the code map from the pricing session.

## Workflow
1. **Extract:**
   `est-estimate scaffold-save --spec <file>.estimate.yaml --agency <slug>
   [--code-map codes.json] [-o scaffold_saves.json]` → `{saves, skipped}`.
   Surface EVERY skipped item and its reason (mob item / no bid_item_code /
   no description) — skips are reported, never silent. `default_production`
   is present only where quantity and all crew days were numeric; the
   extractor never invents production.
2. **Propose assembly refs (optional, per save).** `assembly_ids` are org
   assembly-TEMPLATE ids the extractor cannot know. For items worth the
   linkage, `mcp__bidmanager__list_assemblies` (template context) and propose matches by
   name/description; the estimator confirms each. No match confirmed = no
   `assembly_ids` on that save.
3. **Check what exists.** For each save,
   `mcp__bidmanager__lookup_bid_item_scaffold(bid_item_code=..., agency=...)`:
   - no scaffold → this save is a CREATE;
   - a scaffold exists at the SAME agency tier → it's an UPDATE (show the
     field-by-field diff against the existing values);
   - only the org-generic tier matched while saving agency-specific →
     still a CREATE (the lookup falls back across tiers; check the
     returned scaffold's own `agency` before calling it an update).
4. **Preview and get explicit confirmation.** Show creates vs updates,
   each save's fields (name, cost_codes, default_production, assembly_ids,
   notes), and the skipped list. Do not write until the user confirms —
   updating a scaffold overwrites org-shared prefill defaults, so updates
   get extra care and old values shown in the diff.
5. **Write.** `mcp__bidmanager__create_bid_item_scaffold(...)` per new save;
   `mcp__bidmanager__update_bid_item_scaffold(scaffold_id, ...)` per confirmed update. Pass
   only the scaffold fields — `source_item_no` in `scaffold_saves.json` is
   preview provenance, not an MCP kwarg. The `(agency, bid_item_code)` key
   is immutable: a key change is a create plus an explicit, user-confirmed
   `mcp__bidmanager__delete_bid_item_scaffold` of the old one. Surface per-call errors;
   never silently drop a save.
6. **Verify:** re-`mcp__bidmanager__lookup_bid_item_scaffold` each written key and confirm
   the returned scaffold matches what was confirmed (count + spot-check
   fields). Report created / updated / skipped totals.

## Notes
- One scaffold per `(agency, bid_item_code)` per org; blank agency is the
  org-generic fallback tier — save agency-specific unless the user asks
  for a generic default.
- `cost_codes` from the extractor is `[spec cost_code]` only when a code
  map supplied a distinct agency code; `[]` means the org codes are
  unknown, not "no codes" — add them in the preview if the user wants.
- `waste_factor` is never extracted (spec waste fields are
  geometry-specific); set it in the preview when the user knows the
  item's convention.
- Rate-series repricing of historical breakdowns is NOT this skill and
  remains blocked upstream (BM #974's as-of query surface is not yet in
  the MCP).
