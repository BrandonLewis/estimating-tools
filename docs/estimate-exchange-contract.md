# The estimate exchange contract

**Contract version:** 1.0
**Verified against:** BidSheet.ai's server repository (BidManager) at commit `dfa841ea19b7f2a0640ee19bc851588141cb010a` on `master`, and estimating-tools 0.1.98.

**Audience:** anyone building a surface that reads an estimate from
BidSheet.ai, lets an estimator change it, and sends the change back -- a
workbook pack, a desktop application, a script. HeavyBook and fieldbook, the
workbooks this repository ships, are packs of this contract, not the
contract. Nothing here depends on how a surface is built.

The contract is the import and the export: the read model coming in (part 2),
the change set going out (part 3), and the rules every surface honours
(part 4). How a surface keeps itself consistent between those two moments is
its own business, except for workbooks, which part 5 gives a binding
convention. Part 6 says how the contract changes and part 7 how a surface
proves it conforms. BidSheet.ai is described as built at the commit above;
where it and this document disagree, BidSheet.ai is right and this document
has a bug. The tables this document cites are checked in beside it, in
`docs/estimate-exchange-contract/`, and `tests/test_exchange_contract_doc.py`
fails when they and this document disagree. BidSheet.ai's op tables there
(`docs/estimate-exchange-contract/server-tables.json`) are a snapshot,
regenerated from BidSheet.ai's source at the commit above by a maintainers'
script that is not part of the public distribution. This repository's CI
checks the document against that snapshot, not against BidSheet.ai's live
source; BidSheet.ai's own contract test holds the server to the golden plans
(part 7).

## The one-paragraph version

A client fetches an estimate's read model over REST as the user, to a file:
every row an estimator can see, each editable row with an integer `id` and a
fingerprint `v`. A surface lays it out, the estimator edits, and the surface
turns the edits into a change set: a list of ops, each naming a row by `id`
(or by a `new:` token for a row created earlier in the same set), carrying
the `v` it read, and writing only the fields that op may write. BidSheet.ai
runs the whole set in one transaction under the estimate's lock and refuses
all of it if any touched row's `v` has moved. By default it then rolls back
and returns the plan -- what every op would change, what each delete takes
with it, the totals before and after -- which the surface shows the
estimator before sending the same set again with `dry_run` false and a
`request_id` that makes a retry safe.

## 1. Parties and transport

- **BidSheet.ai** owns the estimate model and every operation on it. It
  prices; a surface never does.
- **A pack** knows one layout: how to lay the read model out, and how to read
  that layout back into a change set (part 5 for workbooks).
- **A client** executes: fetch, build, read, apply, patch, refresh. It is this
  repository's `est-estimate` (`packages/estimating-tools/estimating_tools/exchange/cli.py`,
  with its REST client `packages/estimating-tools/estimating_tools/exchange/client.py`),
  a desktop application, or any program holding the user's token.
- **An agent** orchestrates the client: it runs commands, reads summaries and
  plans, and asks the user to confirm. It does not carry data.

<!-- table: transport -->
| Direction | Bulk (a client) | Conversational (an agent) |
|---|---|---|
| Read | `GET /api/estimates/{id}/workbook/` to a file | `get_estimate_workbook(estimate_id, item_ids=None)` |
| Apply | `POST /api/estimates/{id}/workbook/apply/` from a file | `apply_estimate_workbook_changes(estimate_id, ops, dry_run=True, request_id=None)` |

Both legs carry the same payloads and run the same services. **The bulk leg
is normative for a surface:** a conforming surface moves the read model and
the change set over REST, through files, losslessly. A payload that crosses a
language model is transcribed, and one mistyped `v` is a false conflict while
one mistyped unit cost is a silent misprice. The conversational leg is for
questions about an estimate and for change sets small enough to read.

**The read.** `GET /api/estimates/{id}/workbook/` returns part 2's document.
`?item_ids=1,2` pages it (part 2, Paging); `?item_ids=` with nothing after it
is an empty page, and leaving the parameter out reads the whole estimate.
Each id is between 1 and 2^63 - 1. This repository's client asks for
at most 100 ids per request and merges the pages, recording the ids it asked
for under `_fetch`.

**The apply.** `POST /api/estimates/{id}/workbook/apply/` takes
`{"ops": [...], "dry_run": true, "request_id": "..."}`. `dry_run` defaults to
true and must be a JSON boolean. `request_id` may come instead as the
`Idempotency-Key` header; when both are sent they must be equal. The answers:

| Status | Body | When |
|---|---|---|
| 200 | the plan (part 3) | the set ran (and, on a dry run, rolled back) |
| 400 | `{error, op_index}` | an op was refused, or the set is malformed; `op_index` is null for a whole-set problem (not a list, over the cap, a bad `dry_run` or `request_id`) |
| 403 | `{error}` | the user may not edit this estimate |
| 404 | a not-found error | the estimate does not exist or the user cannot see it |
| 409 | `{error, conflicts}` | rows the set touches changed since they were read (part 3, Conflicts) |
| 409 | `{error}` | the `request_id` was used with another change set, or is sent with a dry run after its apply committed (part 3, Idempotency) |

The MCP tools return the same documents; an error is `{"error": ...}` with
the same extra keys.

**Authentication** is BidSheet.ai's and is referenced, not restated: an
approved personal API token for REST (`Authorization: Token <token>`), held
by the client on the user's machine and never shown to an agent; OAuth 2.1
for MCP. The apply runs as the user and only when the user may edit the
estimate; the read follows the estimate's visibility.

## 2. The read model

One JSON document: amounts as decimal strings (`"1465.74"`), ids as
integers, absent values as `null`. Every editable row carries `v`. Below,
each field is marked **id**, **key** (it names a row of another section),
**in** (an input: the op in brackets writes it) or **computed** (BidSheet.ai
derives it; never sent). A field marked **read-only** is shown and never
written. `docs/estimate-exchange-contract/read-model.json` is one real
document.

**`estimate`** -- the estimate itself.
- id: `id`; `v`.
- in: `markup_percentage`, `markup_amount` (`estimate.update`); the
  bid-total definitions in `bid_totals` (`bid_totals.set`).
- read-only: `name`, `status`, `project`
  (`{id, project_id, project_reference, display_project_id, title}`),
  `organization` (`{id, name}`), `schedule` (the calendar: `start_date`,
  `working_weekdays` with 0 for Monday, `holidays`), `takeoff` (null, or the
  takeoff the estimate is linked to).
- computed: `totals` (`bid_total`, `direct_cost`, `indirect_cost`,
  `markup_total`, `total_estimated_cost`, as stored), `bid_factor` (what the
  item rows were priced at, from the stored totals), `live_bid_factor` (what
  a recalculation now would give; equal to `bid_factor` unless the stored
  totals are stale), `excluded_cost`, each bid total's `amount`.
- `sections`: each `{id, name, schedule_id, display_order, v}`, written
  through `section.upsert` and `section.delete`.
- `bid_totals`: each `{id, name, schedule_ids, includes_unscheduled,
  is_primary, display_order, amount}`; `schedule_ids` null means every
  schedule. The ids are reissued on every `bid_totals.set`.

**`items`** -- the estimate's bid items, in item-number order.
- id: `id`; `v`.
- in (`item.update`): `estimated_unit_price`, `bid_unit_price_override`,
  `quantity_override`, `scope` (`included` or `excluded`), `scope_note`; key
  and in: `section_id` (a row of `estimate.sections`, or null).
- read-only: `item_number`, `item_code`, `description`, `unit`, `schedule`
  (`{id, label, name}`), `schedule_quantity`, `quantity_source` and
  `quantity_ref` (cleared with `quantity_override`).
- computed: `quantity` (effective), `calculated_unit_price`, `unit_price`,
  `pricing_source`, `total`, `bid_unit_price` and `bid_total` (at
  `bid_factor`).

**`elements`** -- the estimate's elements, in display order.
- id: `id`; `v`.
- in: `name`, `element_type`, `structure_id`, `ifc_global_id`
  (`element.create`, `element.update`); `display_order` (`element.update`);
  `source` (`element.create` only).
- read-only: `global_id` and `global_id_assigned` (the IFC GlobalId, assigned
  when none is stored), `ifc_class`, `from_takeoff`, `takeoff_element_id`,
  `section_backed` (true when a structure section owns the element: writing
  its `name` or `structure_id`, or deleting it, is refused).
- `quantities`: one per quantity key, each `{key, label, unit, formula,
  derived, override, effective, pay_item_id, v}`, addressed by its element
  and `key`, never by an id of its own. in (`element.set_quantity`):
  `override`, written as `override_value`; key and in: `pay_item_id` (an
  item, or null for work only). computed: `derived`, `effective`.

**`activities`** -- the whole assembly tree, one entry per activity
(including a container with no cost of its own), ordered by item, then
`sort_order`, then id.
- id: `id`; `v`.
- key: `parent_id` (an activity; null for a root), `estimate_item_id` (an
  item), `crew_id` (a crew; it may name one `crews` does not carry),
  `element_ids` (elements), `spread.items` (items), `activity_code`
  (`{id, code}` or null; written as `activity_code_id`).
- in (`activity.update`): `name`, `description`, `count`, `sort_order`,
  `production_rate`, `production_unit`, `hours_per_shift`, `crew_factor`,
  `duration_shifts`, `basis_quantity`, `basis_unit`, `activity_code_id`, and
  on a `STRUCTURE` row the geometry inputs `dimensions`, `structure_count`,
  `structure_quantity`, `waste_factor`, `concrete_section_type`;
  `assembly_type` (`activity.create` only). Placement through
  `activity.move` (`parent_id`, `item_id`, `sort_order`); links through
  `activity.set_links` (`element_ids`, `measured_by`, `paid_as_part_of`); the
  spread through `activity.set_spread` (`spread.basis`, `spread.scope`, and
  `spread.items` as `item_ids`); the crew through `activity.set_crew`.
- read-only: `basis_source_measure`, `basis_source_groups`, `geometry` (null
  except on a `STRUCTURE` row).
- computed: `duration_days` (one pass's duration); the extended figures --
  multiplied by `count` and every counted ancestor's -- `cost`,
  `cost_split`, `manhours`; `start_date`, `end_date`, `finish_date` (null
  until the schedule has dates); `warnings`.
- `steps`: each `{id, name, duration, duration_unit, activity_code_id,
  sort_order, notes, v}`. in (`step.add`, `step.update`): `name`, `duration`,
  `duration_unit`, `activity_code_id`. `sort_order` and `notes` are
  read-only.

**`resources`** -- the lines (components) under the page's activities.
- id: `id`; `v`.
- key: `activity_id` (an activity; placement on `resource.create`),
  `parent_component_id` (read-only), and the rate links `labor_rate_id`,
  `equipment_rate_id`, `material_cost_id` (rows of `rates`).
- in (`resource.create`, `resource.update`): `name`, `description`,
  `component_type` (`labor`, `equipment`, `material`, `subcontractor`,
  `other`), `quantity`, `unit`, `unit_cost`, `trade`, `time_value`,
  `time_unit`, `includes_burden`, `burden_percentage`, `labor_cost_basis`,
  `pieces`, `sort_order`, `activity_code_id`, and the three rate links.
- computed: `cost`.
- `managed_by`: `"allocation"` for a line a subcontractor allocation posts,
  else null (Managed rows, below).

**`crews`** -- every crew local to the estimate, and every library crew a
page activity uses that the estimate may use.
- id: `id`; `v` (over the crew and its whole roster).
- read-only: `name`, `code`, `scope` (`estimate` or `library`),
  `hours_per_shift`, `crew_factor`; computed: `hourly_rate`.
- `members`: each `{id, classification, count, labor_rate_id,
  hourly_rate_override, effective_hourly_rate, sort_order}`, ordered by
  `sort_order`, `classification`, id. The roster is written whole through
  `crew.update_members` (`classification`, `count`, `labor_rate_id`,
  `hourly_rate_override`, `sort_order`); `effective_hourly_rate` is
  computed. Every roster write reissues the member ids.

**`rates`** -- the library rows the page's resources and crews reference,
and only those: `labor` (`{id, classification, unit, rate}`, unit `HR`),
`equipment` (`{id, name, unit, rate}`, unit `HR`) and `material`
(`{id, name, unit, cost}`). Read-only; no `v`.

**`shares`** -- the cost allocation, the way the bid is priced: each
`{activity_id, activity_key, item_id, element_id, fraction, cost, manhours,
reason}`. Display only. An excluded item's shares are left out.

### Normative rules

**Identity is per kind, and not always one integer.** A client never
invents an id; new rows use `new:` tokens (part 3).

<!-- table: identity -->
| Kind | Identity | Whose `v` conflicts |
|---|---|---|
| estimate | the estimate's `id` | its own |
| section, item, element, activity, step, resource, crew | integer `id`, unique within the kind | its own |
| element quantity | `(element_id, key)` | its own, once it exists; a first write has none |
| crew member | `(crew_id, id)` | the crew's |
| bid total | position within `estimate.bid_totals`; ids are reissued on every set | the estimate's |
| estimate input (`markup_percentage`, `markup_amount`) | field name | the estimate's |

**`v` is opaque.** It is a 16-character fingerprint over the row's input
fields and its parent and link keys, leaving computed fields out, so a
reprice changes no `v`. That much is said so a reader knows when a conflict
can and cannot occur, and no more: a client compares `v` for equality and
never computes it. The recipe is BidSheet.ai's and may change without
notice. What a surface may send is each op's writable fields (part 3).

**Source takeover.** Two inputs become computed when a source takes them
over, and a write to them is then refused: `basis_quantity` and
`basis_unit` while an activity's `basis_source_measure` is set (the takeoff
measure restamps them), and `duration_shifts` while an activity has steps
(the steps' durations restamp it), through `activity.update` and
`activity.set_crew` alike. Neither counts in the activity's `v` while taken
over.

**Paging.** `item_ids` narrows the payload to those items and what hangs
off them: `items`, `activities` and their `resources`, `elements` (an
element stays when one of its quantities pays a page item or a page
activity links it) and `shares` (a share stays when its item or its
activity is in the page). `estimate` always comes whole. `crews` carries
every estimate-local crew and the library crews the page's activities use;
`rates` follows the page's `resources` and `crews`. A page is a complete
read for its items. A surface that holds several pages records which items
each covers (part 5) and never merges two pages' copies of the same row; a
row that changed between pages is caught at apply by its `v`. Paging limits
the payload, not the work: every computed figure is the whole estimate's.

**Managed rows.** A resource with `managed_by` set is posted by a
subcontractor allocation. It is read, never written: `resource.update` and
`resource.delete` refuse it, and so does an `activity.move` to another item
of a subtree that holds one.

**Numbers.** Two numbers are the same input when they are equal to 15
significant digits. A surface that reads a spreadsheet applies this before
deciding a cell changed: a cell comes back as a binary float.

## 3. The change set

A change set is a JSON list of ops, run in the order sent. An op is

    {"op": "<name>", "ref": <id> or "new:<token>" or null, "v": "<16 hex>" or null, "fields": {...}}

`ref` names the row: its integer id, or `new:<token>` for a row created
earlier in the same set (a create may name its own token, or none). `v` is
the row's fingerprint from the read. `fields` holds only the op's writable
fields and, on a create, its placement fields; any other field is refused by
name. Writing `null` clears a field where BidSheet.ai has a clearing
spelling for it and is refused ("can't be cleared") where it has none --
never a silent no-op.

The 23 ops as built. **`v`** says when an op carries one: *required* on an
update or delete of an existing row, *never* on a create (nor on any op
whose `ref` is a `new:` token). **Placement fields** say where a created row
goes (for `element.set_quantity`, which of the element's quantities the op
writes); they are not fingerprinted.

<!-- table: ops -->
| Op | Row kind | `v` | Writable fields | Placement fields | Preconditions and cascade |
|---|---|---|---|---|---|
| `estimate.update` | estimate | required | `markup_amount`, `markup_percentage` | none | `ref` is the estimate's id. Neither field can be cleared. |
| `item.update` | item | required | `bid_unit_price_override`, `estimated_unit_price`, `quantity_override`, `scope`, `scope_note`, `section_id` | none | `null` clears `bid_unit_price_override`; `null` on `quantity_override` also clears `quantity_source` and `quantity_ref`; `estimated_unit_price` cannot be cleared. `scope` is `included` or `excluded`. `section_id` is a section's id, a `new:` section, or `null`. |
| `section.upsert` | section | on an update | `display_order`, `name`, `schedule_id` | none | No `ref`, or a `new:` token, creates; an id with its `v` renames or reorders. `schedule_id` is create-only. A section the set does not name is left alone. |
| `section.delete` | section | required | none | none | Its items are left unsectioned, not deleted. |
| `bid_totals.set` | estimate | required | `totals` | none | `ref` and `v` are the estimate's. `totals` replaces the whole list, each `{name, schedule_ids, includes_unscheduled, is_primary, display_order}` (the last three optional); exactly one is primary; `[]` restores the single implicit Bid Total. The ids are reissued. |
| `element.create` | element | never | `element_type`, `ifc_global_id`, `name`, `source`, `structure_id` | none | A new element is appended; set its order with `element.update`. |
| `element.update` | element | required | `display_order`, `element_type`, `ifc_global_id`, `name`, `structure_id` | none | `name` and `structure_id` are refused on a section-backed element. |
| `element.delete` | element | required | none | none | Refused on a section-backed element. Its quantities go with it; activity links to it are removed. |
| `element.set_quantity` | quantity | when the quantity exists | `override_value`, `pay_item_id` | `key` | `ref` names the element (an id or a `new:` element); `key` names the quantity (`concrete_cy`, `form_contact_sf`, ...). `v` is the quantity's, given only when it already exists. `null` on `override_value` clears an override; `null` on `pay_item_id` makes it work only. |
| `activity.create` | activity | never | `activity_code_id`, `assembly_type`, `basis_quantity`, `basis_unit`, `count`, `crew_factor`, `description`, `hours_per_shift`, `name`, `production_rate`, `production_unit`, `sort_order` | `estimate_item_id`, `parent_id` | `assembly_type` `STRUCTURE` is refused. No `parent_id` makes a root. `duration_shifts` is not a create field: send an `activity.update` on the `new:` row after it. |
| `activity.update` | activity | required | `activity_code_id`, `basis_quantity`, `basis_unit`, `concrete_section_type`, `count`, `crew_factor`, `description`, `dimensions`, `duration_shifts`, `hours_per_shift`, `name`, `production_rate`, `production_unit`, `sort_order`, `structure_count`, `structure_quantity`, `waste_factor` | none | None can be cleared. Source takeover (part 2) refuses `basis_quantity` and `basis_unit` on a measure-sourced activity and `duration_shifts` on a stepped one. A new `hours_per_shift` on a stepped activity restamps its `duration_shifts`, and the plan shows it. |
| `activity.delete` | activity | required | none | none | Deletes the subtree: child activities, their resources and steps. Refused when the subtree holds a `STRUCTURE` row. |
| `activity.move` | activity | required | `item_id`, `parent_id`, `sort_order` | none | Keeps the id. `item_id` (never with `parent_id`) makes it a root of that item, carrying its subtree; element links and spreads stay. Refused on a `STRUCTURE` row; an `item_id` move is refused when the subtree holds a `STRUCTURE` row or managed lines. Both items are repriced. |
| `activity.set_links` | activity | required | `element_ids`, `measured_by`, `paid_as_part_of` | none | `element_ids` replaces the set (`[]` unlinks); `""` clears either quantity key. Moves money between pay items. |
| `activity.set_spread` | activity | required | `basis`, `item_ids`, `scope` | none | `basis` is `direct_cost`, `labor_cost`, `even` or `""`; `scope` is `all` or `chosen`; `item_ids` are the chosen items. Refused on an activity linked to elements. |
| `activity.set_crew` | activity | required | `crew_id`, `duration_shifts` | none | `crew_id` is an estimate-local crew or a library crew usable on this estimate, never `new:`. `duration_shifts` is refused on a stepped activity. Refused when a later `crew.update_members` in the set first copies the same library crew: edit its members, then assign it. |
| `step.add` | step | never | `activity_code_id`, `duration`, `duration_unit`, `name` | `activity_id` | `duration_unit` defaults to `DAYS`; `activity_code_id` must sit under the activity's own code. The step goes after the activity's last step. |
| `step.update` | step | required | `activity_code_id`, `duration`, `duration_unit`, `name` | none | A field left out keeps its value. |
| `step.delete` | step | required | none | none | The step only. |
| `resource.create` | resource | never | `activity_code_id`, `burden_percentage`, `component_type`, `description`, `equipment_rate_id`, `includes_burden`, `labor_cost_basis`, `labor_rate_id`, `material_cost_id`, `name`, `pieces`, `quantity`, `sort_order`, `time_unit`, `time_value`, `trade`, `unit`, `unit_cost` | `activity_id` | `includes_burden` is strictly `true` or `false`. |
| `resource.update` | resource | required | `activity_code_id`, `burden_percentage`, `component_type`, `description`, `equipment_rate_id`, `includes_burden`, `labor_cost_basis`, `labor_rate_id`, `material_cost_id`, `name`, `pieces`, `quantity`, `sort_order`, `time_unit`, `time_value`, `trade`, `unit`, `unit_cost` | none | `quantity`, `unit_cost`, the three rate links, `activity_code_id`, `sort_order` and `labor_cost_basis` cannot be cleared; `time_value`, `burden_percentage`, `pieces` and `time_unit` can. Refused on a managed line. |
| `resource.delete` | resource | required | none | none | Refused on a managed line. |
| `crew.update_members` | crew | required | `members` | none | `members` replaces the roster, each `{classification, count, labor_rate_id, hourly_rate_override, sort_order}`, all but `classification` optional. A library crew is copied into the estimate first (part 4, rule 5); the copy's id is the plan's `created["crew:<library id>"]`. Refused on a library crew no activity of this estimate uses. Member ids are reissued. |

A creating op must also carry the fields below. BidSheet.ai checks `activity.create`'s three, `element.create`'s `name`, and `resource.create`'s and `step.add`'s `activity_id` with the set's shape, before the database is touched; `resource.create`'s and `step.add`'s `name` and `step.add`'s `duration` are checked when the op is applied, a 400 naming the op that rolls the whole set back.

<!-- table: required -->
| Op | Requires |
|---|---|
| `activity.create` | `estimate_item_id`, `name`, `assembly_type` |
| `element.create` | `name` |
| `resource.create` | `activity_id`, `name` |
| `step.add` | `activity_id`, `name`, `duration` |

### Normative rules

- **Refs and tokens.** A `new:` token is `new:` followed by 1 to 64 letters, digits, `_`, `.` or `-`. It is defined once, by the op that creates the row, before any op that uses it -- in its own `ref`, or in a field that names a row (`estimate_item_id`, `parent_id`, `activity_id`, `element_ids`, `item_ids`, `pay_item_id`, `section_id`). A token used before its create, defined twice, or naming the wrong kind of row ("new:e1 is an element, not an item.") is refused. `crew_id` and `activity.move`'s `item_id` are always ids: no op creates a crew or an item. `element_ids` and `item_ids` are lists; every other reference is one value.
- **Moves.** Only activities move: `activity.move` keeps the id. A step, a resource or a crew member placed under another owner is a delete and a create: the row gets a new id, and the surface says so in what it shows. This is as built; move ops for steps and resources are BidSheet.ai #1682.
- **Order.** Ops run in the order sent, so a surface emits creates before the updates, links and children that reference them (an `activity.create`, then the `activity.update` of its `duration_shifts`, then its `step.add` and `resource.create`); a `crew.update_members` of a library crew before an `activity.set_crew` that assigns the same crew (the reverse is refused); and deletes last. The first op naming a row has its `v` checked; a later op on the same row must carry the same `v`, or it is refused naming the first.
- **All or nothing.** One transaction under the estimate's lock. Any refusal refuses the whole set, naming the op index and the reason. The shape -- op names, refs, tokens, `v` syntax, writable fields, the cap -- is checked before the database is touched.
- **Dry run by default.** `dry_run` true runs everything, builds the real plan and rolls back. Its totals are computed fresh, so they equal what the apply produces when nothing else changes in between. A surface shows the dry run's plan before it applies.
- **Conflicts.** Every update and delete carries the `v` the surface read (16 hex characters). A mismatch refuses the set with 409 and lists `{op_index, ref, kind}` for every conflicting row: `ref` is the row's id; for an element quantity it is the element's id and `kind` is `quantity`. Rows not touched are never checked, so a server change elsewhere in the estimate is not a conflict. A delete's cascade is not `v`-checked: the plan lists what went with it, and a surface shows that list.
- **Idempotency.** Every apply carries a `request_id`: a client-chosen string of 1 to 128 of `A-Z a-z 0-9 . _ : -` (a UUID fits), unique per change set, in the body or as the `Idempotency-Key` header. A committed apply is remembered with its plan for 24 hours. The same id with the same ops (key order ignored) returns the stored plan with `replayed: true` and runs nothing; the same id with other ops is refused (409). A dry run is never remembered, so a preview and its commit share one id; a dry run under an id already committed is refused (409), so a client replaying an unknown outcome that forgot `dry_run` false is told rather than shown a fresh plan. After an unknown outcome -- a timeout, a dropped connection, a 5xx -- a surface resends the same ops with the same id and `dry_run` false, and never retries under a new id. A server that predates request ids (BidSheet.ai #1676) ignores the field over REST: there, after an unknown outcome, re-read the estimate and look for the set's creates before resending.
- **Position.**
  - *Storage and order.* `activity.create` and `resource.create` take a `sort_order` and store it as sent: BidSheet.ai never renumbers siblings, and without one it is 0. Rows list by `sort_order`, then id, and a created row's id is higher than every existing row's.
  - *Placing a create.* A surface sends the place it shows, chosen against the siblings' current orders: a created activity or line takes the `sort_order` of the existing sibling it follows (its id sorts it after that sibling and after the creates before it), one less than the first sibling's when it goes first (it may be negative), or 0 when its block has no existing sibling. Orders are integers.
  - *Ties and renumbering.* Where the sibling after it ties with the one before, no order fits between them: the surface renumbers the siblings from there down with `activity.update` or `resource.update` `sort_order`, each to the least order that keeps it after the row above, stopping where a gap opens, and merged into that row's own update when it has one. A renumbering carries the row's `v` like any update (rule 3) and the surface shows it.
  - *Managed lines.* A managed line (rule 6) that would need renumbering is never written: the surface refuses the edit before anything is sent (HeavyBook's reader refuses the read and asks for the new line below it).
  - *Reorders.* Existing siblings are never reordered: a row the user moved within its block is not sent, and the surface says BidSheet.ai keeps its order.
  - *Steps.* `step.add` takes none: a created step goes after its activity's last step. Positions for steps are BidSheet.ai #1681.
- **The cap.** More than 5,000 ops is refused whole.
- **The plan.** The response holds `dry_run`; `ops`, one `{index, op, ref, before, after}` per op in order, `ref` being the op's id or the `new:` token it was sent with, and `before` and `after` holding the fields the op wrote (a create has `after` only, a delete neither), each value as the server formats it, a string: decimals as stored (`"32.000"`), booleans as `"True"` or `"False"`, and a `resource.create`'s rate link as a string id (`"material_cost_id": "1"`). An update's values are read back as stored; a create's `after` is the row as it was created, not re-read, so a value comes back as sent (`"quantity": "1"`). The row ids `activity.create` reports (`estimate_item_id`, `parent_id`) and those in the fixed sets below are integers. Some ops report a fixed set: `section.upsert` always reports `id`, `name`, `schedule_id` and `display_order` after and the three besides `id` before, `activity.move` always `parent_id` and `sort_order`, `activity.set_crew` always `crew_id` and `duration_shifts`, `crew.update_members` adds `crew_id`, and `bid_totals.set`, though an update, returns `after` only, the stored totals with their ids and amounts; `created`, `{"new:<token>": id}` for every row a creating op made, plus `"crew:<library id>": <copy id>` for each library crew a `crew.update_members` copied; `deleted`, `[{index, kind, id, cascade}]`, where an activity's `cascade` lists its `child_activities`, `components` and `steps`, the `element_ids` and `item_ids` whose links went with it and a count of `package_members`, and an element's lists its `quantities` (a count) and the `activities` it was linked to; `warnings`, plain strings -- a library crew's copy note, then the link and spread warnings of every activity an activity op named (`activity <id>: ...`); `totals`, `{before, after}`, each `{bid_total, total_estimated_cost, markup_total, bid_totals}`; and, when one was sent, `request_id` echoed and `replayed`.

## 4. Rules every surface honours

A numbered list a conformance reviewer can tick.

1. Never send a computed field (part 2).
2. Send `v` on every update and delete; never on a create. Compare `v`; never compute it.
3. Conflict only on a row the user touched, or a row the surface renumbers to place a create (part 3, Position): send ops for what changed and nothing else, bar that renumbering.
4. Library rates are read-only. A rate link on a resource is sent as the link -- `labor_rate_id`, `equipment_rate_id` or `material_cost_id`, the id of a row in `rates` -- never as a number typed into `unit_cost`.
5. Editing a library crew's members copies the crew into the estimate: BidSheet.ai makes the copy, repoints every activity of this estimate that used the library crew, and edits the copy; the library crew and other estimates are untouched. The surface sends the edit against the library crew's id and reads the copy back on its next refresh (the plan's `created` names it as `crew:<library id>`). A library crew no activity of this estimate uses is refused.
6. Managed rows are not written.
7. A row moved to another parent is a move where the kind has a move op (activities, `activity.move`) and a delete plus a create where it does not (steps, resources, crew members). The surface says which happened.
8. A row deleted in the surface is a delete. Its cascade is BidSheet.ai's, appears in the plan's `deleted`, and the surface shows it before applying.
9. Nothing is sent that BidSheet.ai would price differently from what the surface showed. The proof is BidSheet.ai's dry-run totals, shown before the apply. A workbook additionally compares its live figures with the server's (a Checks sheet) and refuses to read when a bound formula has been overwritten, but those are the pack's guards, not the proof.
10. A surface that cannot tell a user's edit from a server change since its read must not guess. For a workbook this is why the baseline travels in the book (part 5).
11. A copied resource keeps its rate link only while it still is its source: a surface keeps the link when every input it binds on the row, bar the quantity, equals its source's (a field the surface does not bind is carried from the source, so it cannot differ; HeavyBook's reader applies this); an edited copy is sent as a plain resource with a typed unit cost. A resource cut and pasted under another activity keeps its link.
12. Every apply carries a `request_id`. A surface never retries blind.
13. A push never discards what the estimator typed, in bound cells or out of them. A surface that writes server results back into its document patches it; it does not regenerate it.
14. The read model and the change set move over the bulk leg. An agent orchestrates and does not transcribe.

## 5. The binding convention (workbook surfaces)

Normative for a workbook pack; a client that is not a workbook ignores it.
It is what lets a layout be read back without the reader knowing the layout
in advance. This repository's engine
(`packages/estimating-tools/estimating_tools/exchange/`) implements it from a
pack's declaration, which is pure data: the schema is
`packages/estimating-tools/estimating_tools/exchange/schema/declaration.schema.json`,
and HeavyBook's `packages/estimating-tools/estimating_tools/heavybook/template/pack.yaml`,
with the `template.xlsx` beside it, is the worked example. A declaration
names each sheet's tab, its role (`blocks`, `flat`, `rates` or `display`),
its header and first rows, its tag columns, the column each writable field
is bound to, its formula columns, its blocks and their markers, and the
book's prototypes and stamp.

- **Derived structure, stored identity, position wins.** Every row carries
  its `kind` in a hidden tag column: a contract kind (`ITEM`, `ACTIVITY`,
  `STEP`, `RESOURCE`, `CREW`, `MEMBER`, ...), a marker kind, or a display
  kind. A row inside a block also carries tags derived by formula from the
  rows around it, so they heal when the row is cut, copied or pasted: its
  owner row, the nearest owner above (HeavyBook's `owner_row`, `AJ`, holds
  `=IF(W<r>="ACTIVITY",ROW(),MAX(AJ$4:AJ<r-1>))`), and its owner's id
  (`parent`, `Z`: `=INDEX($X:$X,MAX($AJ<r>,1))`). Every row that
  corresponds to a server row also carries stored values: its `id` and `v`
  (part 2's identity table), its `key` for an element quantity, and in `ref`
  a linked resource's rate link (`labor:<id>`, `equipment:<id>`,
  `material:<id>`) or a crew member's labour rate id. Stored values travel
  with a row unchanged, so they say where the row came from, not where it
  is. A reader decides what a row is from the block it sits in, and uses the
  stored tags to decide whether it is the original (an id seen once, or, of
  several, the occurrence under its baseline owner), a copy (an id seen
  again elsewhere), a move (an id gone from its baseline block and present
  in another, for a kind that moves: activities), a delete and a create (a
  step or a resource whose id left its block; part 3, Moves) or a delete
  (an id gone). A row with a kind and no id, or a row typed into a block
  with neither, is new. A resource whose id the baseline does not hold was
  pasted from another book and is new too; any other row with an id the
  baseline does not hold is refused. The reader never sends the `v` stored
  in a row: every op's `v` comes from the baseline, and the `v` cells are
  informational.
- **The stamp.** One custom document property for detection,
  `estimate_format: <pack name> <pack version>` (HeavyBook: `heavybook 2`),
  with `estimate_id`, `bidsheet_host` and `exported_at` beside it. Excel
  truncates a document property at 255 characters, so nothing larger goes
  there; the stamp itself lives in a cell. The stamp is JSON in one cell
  under the workbook-scoped defined name `exchange.stamp` (the engine puts
  it in `_wb!A1`, on a hidden sheet; the declaration's `stamp` section names
  the cell): `contract` (the contract major, `"1"`), `pack`
  (`{name, version}`), `schema` (the declaration schema's version) and
  `declaration` (the declaration as loaded), `host`, `estimate_id`,
  `estimate_v`, `exported_at`, `page` and `item_ids` (the items a page
  covers; `null` when they do not fit the cell, the baseline then listing
  them), `baseline`, `extra` (what only the pack reads), and `stale`.
  `stale` is absent on a book as built; a patch adds to it when it takes a
  new baseline while the book still shows, as of export, something
  BidSheet.ai changed that the layout cannot take in place (`shares`,
  `crews`, `rates`, or a display sheet's source). It is about what the book
  displays only: the book stays readable, every later patch and refresh
  reports the list as a note, and only a rebuild clears it. This is not
  `exchange_stale`, which a patch sets only when its copy does not read back
  clean, and which makes every read refuse the book. The baseline is the
  read-model payload the book was built from: canonical JSON (sorted keys,
  no spaces), zlib-compressed and base64-encoded (`zlib+base64`), cut into
  chunks of at most 32,000 characters in column B beside it (`_wb!B1`
  downward), with the SHA-256 of the JSON bytes as `baseline`'s `sha256`.
  Readers accept HeavyBook's `hc.layout` and fieldbook's `est.layout` as the
  stamp's name in books stamped before this document.
- **Markers.** Every block that may grow -- an activity's steps and its
  resources, a crew's members -- is bracketed by marker rows (HeavyBook:
  `STEPS` to `START` around steps, `START` to `END` around resources, the
  `CREW` row to `CREW_END` around members), and every formula over a block
  sums the bracketed range, so a row inserted anywhere between its markers
  counts. A reader refuses a marker that is missing, repeated, out of order
  or under the wrong owner, and a value typed on a marker row.
- **Prototypes.** Rows a user may insert exist once as prototypes on a
  hidden sheet the declaration does not declare (`_templates`), each under a
  workbook-scoped defined name over whole rows that the declaration's
  `prototypes` names (HeavyBook: `hc.tpl.activity`, `hc.tpl.stepped`,
  `hc.tpl.resource`, `hc.tpl.step`, `hc.tpl.member`; fieldbook's are
  `est.tpl.*`). A template pack's build fills its sheets from prototypes of
  its own on the same sheet (HeavyBook's `hb.fill.*`). The declaration's
  `navigator.templates` lists the ones Estimate Navigator, or any other
  tool, offers for insertion. An inserted copy carries a kind and no id, so
  it reads as new wherever it is put; a prototype copied by hand reads the
  same.
- **Defined names, not addresses,** for anything a tool must find after the
  user inserts rows: tables (HeavyBook's Checks table, `hc.checks`), totals
  (`hc.bid_totals`), the stamp.
- **Baseline over re-fetch.** A reader diffs the book against its embedded
  baseline, never against a fresh read, because a fresh read cannot separate
  the user's edit from a server change since export. The fresh read's job is
  the `v` check at apply.
- **Patch, never rebuild.** The change set records the sheet and row each op
  came from (`rows`: `{op_index, sheet, row}`, one or more per op, the row
  null for a delete; a `crew.update_members` lists the member rows its
  summary names, in sheet order and each once, then one null row per
  removed member, never the crew's header row).
  After an apply the pack writes the `id`, `v` and stored `parent` tags of
  the rows the ops came from (a created activity's block takes its new id
  as its parent; a row typed with no kind gets its kind and its prototype's
  formulas, in blank cells only; a crew whose roster was replaced or copied
  from the library gets its new ids), takes other users' changes since the
  read as a refresh would, and replaces the baseline, `estimate_v` and the
  export time. All of it is written to a copy that is read back, and the
  book takes the copy only when that read is clean (no problems, no ops).
  When it is not, only the identity cells are written, the old baseline
  stays, and the book is stamped with the document property
  `exchange_stale`, which every read refuses until the book is rebuilt. A
  refresh fetches, compares the server with the baseline (server changes)
  and the book with the baseline (user changes), patches the bound cells of
  rows changed only on the server, inserts rows new on the server from their
  prototypes at the end of their block, removes rows deleted on the server
  and untouched in the book, and reports rows changed on both sides -- and
  changes the layout cannot take in place -- writing nothing when it reports
  anything. Charts, notes, formats, extra sheets and anything outside bound
  cells survive both.
- **What a pack provides.** The pack interface
  (`packages/estimating-tools/estimating_tools/exchange/pack.py`, registered
  under the `estimating_tools.packs` entry point): `detect` a book, `build`
  one from the read model, `read` one into a change set, `patch` it after an
  apply, `refresh` it from a fresh read, name its insert `templates`, and
  give its `declaration`. A template pack -- a `pack.yaml` and a
  `template.xlsx`, no code -- gets all of them from the engine.

## 6. Versioning and change

- **The version.** The read model will carry `contract_version` as
  `MAJOR.MINOR` (BidSheet.ai #1680). Until it does, this document declares the
  version it describes (its header), and a reader treats an absent field as
  `1.0`.
- **Minor:** a new op, a new field, a new section, a loosened precondition.
  Readers ignore what they do not know. **Major:** a changed rule, a removed
  or renamed op or field, a change in what `v` covers.
- **Who declares what.** A pack declares the contract major it targets
  (`pack.contract` in its declaration; the book's stamp carries it as
  `contract`), and a reader refuses a book stamped with another major ("this
  book targets contract N"). Once the apply accepts a version field
  (BidSheet.ai #1680), it refuses a change set that names another major.
- **Change process.** A change to BidSheet.ai that changes an op, a field,
  what `v` covers or a rule updates this document in the same release.
  Drift is caught by:
  1. a maintainers' script that is not part of the public distribution,
     which regenerates `docs/estimate-exchange-contract/server-tables.json`
     from BidSheet.ai's source and reports when the two differ; and
     `tests/test_exchange_contract_doc.py`, which holds this document to
     that snapshot;
  2. BidSheet.ai's read-back test, which holds its read of the fixture
     estimate to its own copy of `read-model.json`;
  3. BidSheet.ai's contract test, which dry-runs every golden change set
     and compares the result with its golden plan (part 7).

  The aim is that both repositories' CI fail on drift. The header names the
  BidSheet.ai commit this document was last verified against.

## 7. Conformance

The goldens are checked in beside this document:

    docs/estimate-exchange-contract/
      read-model.json                  the golden read model
      server-tables.json               BidSheet.ai's op tables at the verified commit
      scenarios/<name>.changes.json    HeavyBook's change set for a scenario's edits
      scenarios/<name>.plan.json       BidSheet.ai's dry run of it, in the read model's ids
      scenarios/<name>.refused.json    a scenario HeavyBook's reader refuses: its problems

- **Golden read model.** `read-model.json` is BidSheet.ai's read of one
  fixture estimate, built in BidSheet.ai's test suite by a factory that
  exercises every cost rule; it is also HeavyBook's parity fixture
  (`packages/estimating-tools/estimating_tools/heavybook/tests/fixtures/workbook.json`,
  held equal by `tests/test_exchange_contract_goldens.py`). Its ids and `v`
  values are those of the database it was generated on: a test that replays
  a golden pairs rows by stable keys (item number, activity path, names) and
  takes each `v` from its own live read, as BidSheet.ai's tests do.
- **Golden change sets and plans.** Each scenario is an edit an estimator
  makes in HeavyBook's book of the golden read model. Its `.changes.json` is
  what HeavyBook's reader produces (exactly what `est-estimate read` writes as
  `BOOK.changes.json`: `ops`, the `rows` each op came from, `summary`,
  `notes`), and its `.plan.json` is what BidSheet.ai's dry run returns for
  those ops, written by BidSheet.ai's contract test. A plan
  is stored in the read model's ids: a live id is written back as its fixture
  row's, a created row's id as the token that created it, and `created` maps
  each token to the kind of row it made.

<!-- table: scenarios -->
| Scenario | The edit | Ops |
|---|---|---|
| `changed-inputs` | an item's unit price, an element quantity, an activity's production, a resource's quantity | `item.update`, `element.set_quantity`, `activity.update`, `resource.update` |
| `bid-form` | the markup percentage, an item excluded, an item's bid price override | `estimate.update`, `item.update` |
| `typed-resource` | a resource line typed into an activity's block | `resource.create` |
| `stale-paste` | a resource row copied into another activity's block, its stored tags still naming the old one | `resource.create` |
| `cut-resource` | a resource row cut and pasted under another activity | `resource.create`, `resource.delete` |
| `copied-linked-resource` | a rate-linked resource copied, unchanged | `resource.create` |
| `edited-copy-of-linked-resource` | a rate-linked resource copied and its unit cost changed | `resource.create` |
| `reburdened-copy-of-linked-resource` | a rate-linked resource copied and its burden changed, its unit cost not | `resource.create` |
| `renumbered-resource` | a resource line typed between two lines that tie on sort order | `resource.create`, `resource.update` (the line below renumbered) |
| `reordered-activity` | an activity moved above its sibling within its item | none: noted, "is not where BidSheet.ai lists it among its rows" |
| `typed-step` | a step typed into a stepped activity | `step.add` |
| `edited-step` | a step's duration | `step.update` |
| `replaced-step` | a new step typed and the old one deleted | `step.add`, `step.delete` |
| `deleted-activity` | an activity's whole block deleted | `activity.delete` |
| `deleted-member` | a crew member's row deleted | `crew.update_members` |
| `edited-library-crew` | a library crew member's count | `crew.update_members` |
| `moved-and-copied-activities` | the markup, a resource quantity, a typed step, a copied resource, a deleted resource, an activity cut to another item, a crew-priced activity copied, a crew member's count | `estimate.update`, `activity.move`, `activity.create`, `activity.update`, `step.add`, `resource.create`, `resource.update`, `crew.update_members`, `activity.set_crew`, `resource.delete` |
| `formula-overwritten` | a formula cell typed over | refused: "held a formula and now holds a value" |
| `all-steps-deleted` | a stepped activity's only step deleted | refused: "all of its steps were deleted" |

**No scenario yet:** `activity.set_links`, `activity.set_spread`,
`bid_totals.set`, `element.create`, `element.delete`, `element.update`,
`section.delete`, `section.upsert` -- HeavyBook's reader emits none of them:
its book does not bind sections, bid totals, an element's own fields, links
or spreads.

- **A surface conforms by plan equivalence.** Given the golden read model
  and a scenario's edits, BidSheet.ai's dry run of the surface's change set
  yields a plan equivalent to the golden one. Write both in the read model's
  ids as above; they are equivalent when their `totals` are equal, the same
  rows are deleted with the same cascades (`deleted` compared as a set of
  `{kind, id, cascade}`), every existing row the ops touched ends with the
  same `after` value for each field, and the created rows are the same
  multiset of kinds with the same final fields. Token names, op indexes,
  grouping and order within part 3's constraints are the surface's own.
  Byte equality with HeavyBook's change set is HeavyBook's regression test
  (`tests/test_exchange_contract_goldens.py`), not the conformance bar. A
  workbook pack proves it through its build-then-read; an application
  through its own read.
- **Refusals.** A surface refuses, before anything is sent, what it cannot
  send correctly. The two refusal scenarios are HeavyBook's (a formula typed
  over, a stepped activity left with no step); a conforming surface's
  refusals are its own, but it never sends a change set that misstates the
  edit.
- **Regenerating.** Here: `UPDATE_GOLDEN=1 pytest tests/test_exchange_contract_goldens.py`,
  on purpose, after a reviewed change. In BidSheet.ai: a maintainer copies
  this directory into its contract test's fixtures and runs it with the
  plans' output directory set to this directory's `scenarios/` to write the
  plans, or without one to compare them. A golden that changes is a contract
  change (part 6).
- **Compact copy.** The `apply-estimate-workbook` skill
  (`plugins/estimating-core/skills/apply-estimate-workbook/SKILL.md`)
  carries a one-screen summary of parts 3 and 4, the way `bim-to-takeoff`
  carries the IFC contract's.

## Limits, published as numbers

<!-- table: limits -->
| Limit | Value | Where it bites |
|---|---|---|
| Ops per apply | 5,000 | refused whole above it |
| `new:` token | 1 to 64 letters, digits, `_`, `.` or `-` after `new:` | a malformed token is refused |
| `request_id` | 1 to 128 characters of `A-Z a-z 0-9 . _ : -`, unique per change set | idempotent retry |
| `request_id` retention | 24 hours | the retry window |
| Page size (this client) | 100 item ids per read | this repository's client splits a longer list and merges the pages |
| Document property | 255 characters | why the stamp is a cell |
| Cell | 32,767 characters | why the baseline is chunked |
| Number equality | 15 significant digits | what counts as a changed input |
| Checks tolerance | the pack's, stated per measure | not the contract's |
