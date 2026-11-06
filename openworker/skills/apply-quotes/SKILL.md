---
name: apply-quotes
description: Carry a work package's chosen vendor quote (or self-perform) into the estimate with mcp__bidmanager__carry_work_package_quote, set its carry mode, and roll up the estimate package — via the BidSheet.ai MCP. Confirms before writing; idempotent; adjusts on bid-day revisions. Writes.
---

# Apply / Carry Vendor Quotes

Use this after `compare-quotes` to carry the chosen vendor pricing into the estimate. The
estimate carries **one quote per work package** (`mcp__bidmanager__carry_work_package_quote`); BidSheet.ai
prices the package from it. This **writes** to BidSheet.ai, but only after you confirm,
and nothing runs against production without the estimator's go-ahead. Partial bids are
normal on bid day and quotes get revised; re-run to change the carry.

For a spec-driven bid (`work_packages` in the estimate spec, quote files on disk), use
`sync-work-packages` instead: it pushes the whole choice from the file and records it.
This skill is the by-hand path in BidSheet.ai.

**Precondition:** the project has a priced estimate (`price-estimate`) and BidSheet.ai
returns `carry_mode` from `mcp__bidmanager__get_work_package`. If it does not, BidSheet.ai is not yet on the
carried-quote model: stop and say so.

## Inputs
- The target `project_id` and the work package (by name or `work_package_id`).
- The decision (gathered below).

## Workflow
1. **Resolve the work package:** `mcp__bidmanager__list_work_packages(project_id)` -> match by name, or
   use the given `work_package_id`. Record it.
2. **Read its state:** `mcp__bidmanager__get_work_package(work_package_id)` -> `carry_mode`
   (automatic or pinned), `selected_quote`, `self_perform`, `new_quotes_since_carry`.
   Rebuild the spread as `compare-quotes` does when the estimator wants to see it.
3. **Get the decision** from the user:
   - a vendor's quote (`quote_id`, the current revision) to carry, and which of its
     alternates (if any) to accept; or
   - **self-perform** (the GC prices the package itself); or
   - back to **automatic** (BidSheet.ai carries its own lowest quote).
4. **Forbidden-mix guard (before any write):** a carried quote is taken whole, so the
   guard bites only when the estimator also wants a hand allocation of part of a vendor's
   items. In that case read the vendor's `separate_acceptance_permitted` and
   `acceptance_notes` from the quote (BM-primary; the offline journal
   `<bid working dir>/Subquotes/quote-conditions.jsonl` otherwise).
   - `false` -> **STOP**; quote `acceptance_notes` verbatim.
   - unknown -> warn and require explicit confirmation of the risk.
5. **Confirm BEFORE writing.** Show the package, today's carry (`carry_mode`,
   `selected_quote`), what will be carried, and any `new_quotes_since_carry`. Make NO
   writes until the user explicitly confirms.
6. **Carry** (on confirmation):
   - a vendor: `mcp__bidmanager__carry_work_package_quote(work_package_id, quote_id, pin=True)`;
   - self-perform: `mcp__bidmanager__carry_work_package_quote(work_package_id, quote_id=0, pin=True)`;
   - a vendor alternate the estimator wants carried: add
     `accept_alternate_line_ids=[<line ids>]` to the vendor call. The ids come from
     `mcp__bidmanager__list_work_package_quote_line_items(quote_id)`, the lines with `is_alternate` true;
     confirm each line and its price first;
   - back to automatic: `mcp__bidmanager__update_work_package(work_package_id, carry_mode="automatic")`.
   Setting `carry_mode` by hand is only for this return to automatic or an explicit ask;
   a pin comes from `mcp__bidmanager__carry_work_package_quote`.
7. **Read `carry_warnings`** in the result and show them to the estimator verbatim; none
   of them is cosmetic. An error comes back as `{"error": ...}`: report it, do not retry
   blindly.
8. **Acknowledge** new quotes only when the estimator has looked at them:
   `mcp__bidmanager__acknowledge_work_package_quotes(work_package_id)`.
9. **Roll up the estimate package:** `mcp__bidmanager__list_estimates(project_id)` ->
   `mcp__bidmanager__list_estimate_packages(estimate_id)` -> the package whose `work_package_id` matches ->
   `mcp__bidmanager__recalculate_estimate_package_totals(package_id)`. If none exists, skip and say so.
10. **Report:** what is now carried (re-read `mcp__bidmanager__get_work_package`), the `carry_warnings`, and
    the refreshed estimate-package totals.

## Notes
- Re-running is safe: carrying the quote already carried changes nothing. A vendor's
  revision is a new current revision (`capture-quote`); carry it again and
  `new_quotes_since_carry` clears once acknowledged.
- The old allocation-based award (`mcp__bidmanager__allocate_subcontractor` per quote line) is not used
  here. A hand allocation by item is `sync-work-packages`' `picks` form.
- Any plug component left on an item the vendor now covers double counts; `sync-work-packages`
  offers its removal and warns when one remains.
- This cycle does NOT change quote status (the carry is recorded on the package).
- Quote revisions preserve history (BidManager #556); prior revisions remain for audit
  (`mcp__bidmanager__list_quote_revisions`).
- BidSheet.ai write constraints: see `../estimating-reference/references/api-constraints.md`.
