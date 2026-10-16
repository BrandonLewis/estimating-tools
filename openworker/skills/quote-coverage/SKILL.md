---
name: quote-coverage
description: Show the quote-space board for a project — solicited/received/leveled/awarded per bid item x vendor, plus the zero-coverage gap list ("nobody is even bidding this"). Joins the local solicitation journal with live BidSheet.ai work-package/quote/allocation data. Read-only, via the BidSheet.ai MCP.
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Quote-Space Coverage Board

Use this on bid day (or any time) to answer "where are we on sub coverage?".
Leads with the gap list — bid items in sub-out/hybrid packages that no
vendor was even solicited for.

## Workflow
1. **Source solicitations (BM-primary).** When connected, list them from
   BidSheet.ai: `mcp__bidmanager__list_solicitations(work_package_id)` per package. Rows already
   carry `work_package_name` and `vendor_name` (no id→name resolution needed),
   so build the records directly:
   `SolicitationRecord.from_bm(row, work_package_name=row["work_package_name"],
   vendor_org_name=row["vendor_name"])`, and pass them to `build_coverage`.
   Offline, read the local journal with `read_journal` as today. Everything
   downstream — `build_coverage`, the board, gaps — is unchanged.

   **Locate the journal (offline path).**
   `<bid working dir>/Subquotes/solicitations.jsonl` (from the intake
   manifest). Missing journal is fine — the board still shows received/awarded
   from BM data.
2. **Export packages.** `mcp__bidmanager__list_work_packages` + `mcp__bidmanager__get_work_package` per
   package → packages JSON: `[{"name", "strategy", "items": [{"schedule",
   "item_number", "description"}]}]`.
3. **Export quotes.** `mcp__bidmanager__list_work_package_quotes` per package (rows
   `{"vendor_name", "work_package_name"}`) and, for ungrouped per-item
   quotes, `mcp__bidmanager__list_quotes` (rows `{"vendor_name", "schedule",
   "item_number"}`) → one combined quotes JSON list.
4. **Export allocations.** `mcp__bidmanager__list_subcontractor_allocations` → allocations
   JSON `[{"vendor_name", "schedule", "item_number"}]`.
5. **Leveled packages.** Packages with a current spread — ones leveled this
   session via compare-quotes, or with a written `spread-<package>.md` from
   the bid-day sweep — go in `--leveled` (comma-separated names).
6. **Build the board:**
   `est-quotespace coverage --journal <journal> --packages <packages.json>
   --quotes <quotes.json> --allocations <allocations.json>
   --leveled "<names>"` — stdout is the markdown board. Present it as-is:
   gaps first, then per-package tables, then the vendor summary. `--json`
   for machine use (automations).
7. **Call out** any gap items and any package where every solicited vendor
   has declined — those need new solicitations (the solicit-quotes skill).

## Notes
- Read-only: no BM writes, no journal writes.
- "leveled" is caller-decided (step 5) — the CLI does not guess.
