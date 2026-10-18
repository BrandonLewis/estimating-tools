---
name: estimating-reference
description: Reference guide for the construction-estimating MCP tools — domain model, available tools, and key concepts for construction estimating
---

# Estimating Reference

See also, in this skill's `references/` directory:
- `api-constraints.md` — field-discovered API write constraints: varchar
  limits, silent rounding and zero-coercion, and how to write around them.
- `conflict-ledger.md` — the conflict-ledger discipline for disagreeing bid
  documents (ledger shape + which-governs rules).
- `agency-annotations.md` — agency bid-schedule annotation semantics ((F),
  (N), LS-vs-unit risk, payment envelopes, regulatory-hazard pricing).
- `temporary-barrier-criteria.md` — Caltrans K-rail/temporary-barrier
  layout and estimating criteria (MTD 14-19 + BDM 13.1): the
  advertise-before-2027-01-01 transition rule, the run-length estimate
  formula, crash-cushion triggers, and the MASH clear-area table.

## Domain Model

The construction-estimating MCP manages construction bid projects. Key entities:

- **Project** — A construction project with bid items, team, and estimates
- **ProjectBidItem** — A line item from bid documents with quantity and unit (linked to a BidItemTemplate); `description`/`unit` edits set per-item overrides, the shared template is untouched
- **Estimate** — A priced collection of bid items for a project (owned by org or user)
- **EstimateItem** — A single priced line in an estimate (links to a ProjectBidItem); carries pricing — `estimated_quantity` lives on the bid item, not here
- **Assembly** — A detailed cost breakdown (labor + material + equipment + subcontractor components), in one of three contexts (see below)
- **Component** — A single cost element within an assembly (e.g., 4 hours of Carpenter labor at $85/hr)
- **WorkPackage** — A grouping of bid items by execution strategy (self-perform, sub-out, hybrid); items assigned FULL or PARTIAL
- **WorkPackageQuote** — A vendor's quote against a work package: vendor identity (`vendor_id` linking to a directory organization, or free-text `vendor_name`), acceptance terms (`separate_acceptance_permitted` + `acceptance_notes`), and `scope_tags`
- **Quote revisions** — Changed pricing on a captured quote mints a new current revision (`create_quote_revision`); prior revisions are preserved for audit (`list_quote_revisions`); leveling and award operate on the current revision
- **QuoteLineItem** (WorkPackageQuoteLineItem) — One quoted line per work-package item: `unit_price` and/or `amount`, optional `quantity`. Three states via the pair `(is_included, is_alternate)`: `(true, false)` base (in the quoted price); `(false, false)` excluded (+ `exclusion_notes`, the vendor is not bidding it); `(false, true)` the vendor's **alternate** — priced, outside the quoted base total (an add/option). `is_alternate` wins: `plan_quote` forces `is_included=False` on a line that set both true rather than raising, so `(true, true)` never reaches the MCP call.
- **scope_tags** — Per-quote scope-condition groups (`{group, items, treatment: separate|folded, folded_into, notes}`) that gate leveling: groups compare all-in, folds redistribute coverage
- **SubcontractorAllocation** — An award: links a quote line item into the estimate (`allocation_type`/`value`, `allocation_percentage`); the remainder after a partial award is the GC's self-perform. Allocating an **alternate** line without `accept_alternate=true` is refused with an error ("Accept the alternate (`accept_alternate`) to allocate it."), same on `update_subcontractor_allocation`. Don't allocate an **excluded** line — unlike the alternate case, the server does NOT refuse it; it silently creates an allocation that posts $0.
- **EstimatePackage** — The bridge between an Estimate and a WorkPackage (`create_estimate_package`); allocations fail without it; totals refresh via `recalculate_estimate_package_totals`
- **LaborRate / EquipmentRate / MaterialCost** — Organization rate library entries
- **Organization / Person** — The vendor/sub directory: orgs deduped by name (with region, license, DBE fields), people by email; captured quotes resolve their vendor to an org's `vendor_id`
- **DBE** — Orgs carry `is_dbe` (+ `certification_number`/`certifying_agency`); set `is_dbe` true only for a confirmed DBE, never by default
- **CostCodeSystem / CostType / ActivityCode** — An org-scoped cost-code system: cost types (Labor/Material/Equipment/…) plus a hierarchy of activity (job-cost) codes, each resolving a `cost_type` and optional `parent`

## Key Concepts

### 3-Tier Pricing
- **Public** — Aggregated historical bid results (min/avg/median/max from past projects)
- **Organization** — Company-specific pricing
- **User** — Personal estimates

### Assembly Contexts
Assemblies exist in one of three contexts:
- **Template** — Org library (reusable across projects)
- **Project** — Project-specific customization
- **Estimate** — Attached to a specific estimate item for detailed cost buildup

### Estimate Lifecycle
draft -> review -> approved -> submitted -> awarded -> archived

### Work Package Strategies
- self_perform — Crew does the work
- sub_out — Subcontract to another company
- hybrid — Split between self-perform and subcontractor
- undecided — Not yet determined

## Available Tools

The connected BidSheet.ai MCP server's live tool list is the authority — a
hand-maintained catalog here goes stale (a prior version of this section
listed tools that no longer exist anywhere else in the plugin). To see the
real surface, enumerate the session's available MCP tools (the host lists
every connected server's tools; use the tool names exactly as THIS
session's inventory shows them — hosts differ on whether server-prefixed
or bare names resolve, and the skills here are written for the local
convention with the port rewriting names per surface).

High-level tool families (names follow list/get/create/update/delete
verb-noun conventions):

- **Projects / bid items** — project CRUD + search; bid items, bid-item
  templates and scaffolds (`update_bid_item` owns `estimated_quantity` and
  per-item overrides)
- **Estimates** — estimates, estimate items, summaries (`update_estimate_item`
  edits PRICING only — see `references/api-constraints.md`)
- **Assemblies / components** — assembly CRUD per context (template/project/
  estimate), component CRUD
- **Rate library** — labor / equipment / material rate reads and creates
- **Work packages & quotes** — work-package CRUD + item assignment;
  work-package quotes, quote line items, quote revisions, scope tags;
  subcontractor allocations and estimate packages
- **Directory** — organizations and people (find-or-create; orgs by name,
  people by email)
- **Cost codes** — cost-code systems, cost types, activity codes
- **Historical bank** — historical pricing records + competitor bids
- **Structures** — estimate-layer structures/sections (the push-takeoff
  target)
- **Feedback** — feedback reports (report-issue / triage-feedback)

Write-path field constraints and tool-signature footguns live in
`references/api-constraints.md` — read it before any write flow.
