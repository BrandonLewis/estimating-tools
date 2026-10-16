---
name: review-quotes
description: Workflow for comparing and managing vendor quotes for bid items
---

# Review Quotes

Follow this workflow when asked to compare quotes or manage vendor pricing.

## Steps

1. **List quotes** — Use mcp__bidmanager__list_quotes(project_bid_item_id) to see all quotes for an item
2. **Compare** — Review amounts across vendors for the same items
3. **Accept/reject** — Use mcp__bidmanager__update_quote_status(quote_id, 'accepted') or 'rejected'
4. **Find best** — Use mcp__bidmanager__get_best_quote(project_bid_item_id) to get the lowest accepted quote
5. **Update estimate** — Use mcp__bidmanager__update_estimate_item(item_id, unit_price=quote_amount) to apply the quoted price

## Tips

- Compare quotes for the same scope — make sure vendors are quoting the same items
- Check if quotes include mobilization, bonds, and insurance
- The lowest quote isn't always the best — consider vendor reliability
- Record notes on each quote explaining inclusions/exclusions
- This skill operates on the **per-bid-item** quote model (`mcp__bidmanager__list_quotes(project_bid_item_id)`); for **work-package** quotes captured via `capture-quote`, use `compare-quotes` or `apply-quotes` instead.
