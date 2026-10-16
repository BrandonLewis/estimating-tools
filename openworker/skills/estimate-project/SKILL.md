---
name: estimate-project
description: Workflow for estimating a construction project — find project, review bid items, create estimate, price items, summarize
---

# Estimate a Project

Follow this workflow when asked to estimate a project or price bid items.

## Steps

1. **Find the project** — Use mcp__bidmanager__list_projects or mcp__bidmanager__get_project to find and confirm the project
2. **Review bid items** — Use mcp__bidmanager__list_bid_items(project_id) to see all items to price
3. **Check existing estimates** — Use mcp__bidmanager__list_estimates(project_id) to avoid duplicating work
4. **Create estimate** — Use mcp__bidmanager__create_estimate(project_id, name) if none exists
5. **Price each item** — For each bid item from `mcp__bidmanager__list_bid_items(project_id)` (its `id` is the
   ProjectBidItem id — pass it to both tools below, whose parameter names differ):
   - Use mcp__bidmanager__get_bid_item_pricing(bid_item_id) to check historical data
   - Use mcp__bidmanager__price_bid_item(estimate_id, project_bid_item_id, method) to set the price
   - For complex items, use mcp__bidmanager__build_assembly_breakdown to create detailed cost buildups
   - When building assemblies, use mcp__bidmanager__list_labor_rates, mcp__bidmanager__list_equipment_rates, mcp__bidmanager__list_material_costs for current rates
6. **Review** — Use mcp__bidmanager__prepare_estimate_summary(estimate_id) to review totals
7. **Competitiveness check** — Use mcp__bidmanager__analyze_bid_competitiveness(project_id, estimate_id) to flag outliers

## Tips

- Start with the largest dollar items — they have the most impact on the total
- Use historical pricing (method='median') as a starting point, then adjust
- Flag items with low confidence for review
- Check the rate library before manually entering labor/equipment/material costs
