---
name: manage-work-packages
description: Workflow for organizing bid items into work packages with strategies
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Manage Work Packages

Follow this workflow when asked to organize bid items into packages for subcontracting or self-performance.

## Steps

1. **Review items** — Use mcp__bidmanager__list_bid_items(project_id) to see all items
2. **Check existing packages** — Use mcp__bidmanager__list_work_packages(project_id) to see current organization
3. **Create packages** — Use mcp__bidmanager__create_work_package(project_id, name, strategy) to create groupings:
   - Group by trade (concrete, earthwork, electrical, etc.)
   - Group by scope area
   - Group by subcontractor capability
4. **Assign items** — Use mcp__bidmanager__assign_items_to_package(work_package_id, bid_item_ids) to assign items. Use allocation_type='PARTIAL' with partial_percentages for split assignments.
5. **Set strategies** — Use mcp__bidmanager__update_work_package(work_package_id, strategy=...) to decide self-perform vs sub-out
6. **Check coverage** — Look for unassigned items across all packages

## Strategies

The self-perform vs sub-out call is the biggest judgment this workflow
makes — a wrong one misprices the whole package. Decide it on:

- **Crew capacity and availability** — can the org's crews actually staff
  this scope in the project's window, alongside work already committed?
- **Historical self-perform cost vs the market** — compare the org's
  historical self-perform unit cost (the historical bank, `est-hist
  suggest` — the same source price-estimate consults) against quoted
  market pricing for the trade.
- **Risk fit** — means-and-methods exposure and schedule risk: scope the
  org controls well argues self-perform; specialty or high-liability work
  argues sub-out.
- **DBE-goal contribution** — on a project with a DBE (or similar)
  participation goal, subbing a package to a certified vendor contributes
  to the goal; self-performing it does not.

The strategy values:

- self_perform — The org's crew does the work. Need assemblies with labor/equipment/material.
- sub_out — Subcontract out. Need quotes from vendors. Before countersigning
  a subcontract, run the `subcontract-risk-review` skill.
- hybrid — Some self-perform, some subbed. Split the scope explicitly —
  which items (or what quantity share of each) go each way — never leave
  the split implied.
- undecided — Haven't decided yet. Flag for the estimator to decide; never
  silently default a package's strategy.
