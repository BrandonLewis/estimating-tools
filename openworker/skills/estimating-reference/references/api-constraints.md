# BidSheet.ai API field constraints (field-discovered)

Write-path constraints first discovered on a live bid. **Most were fixed
upstream in BidManager#1027 (deployed 2026-08-06) and re-verified against the
live server 2026-08-07** — this file records the *current* state, with the
history noted so older guidance isn't mistaken for live behavior.

Two failure shapes remain worth knowing: some writes fail LOUD (a validation
error bubbles back — now field-named, no longer a raw Postgres error), and
some still fail SILENT (the write "succeeds" but the stored value differs —
rounded, or a zero rewritten).

| Model.field | Constraint | Failure mode | What to do |
|---|---|---|---|
| `WorkPackageQuote.contact_info` | max 200 chars | **LOUD** — validation error naming the field + limits (BM-6 fixed; was a raw Postgres error) | Keep it short (name / phone / email only); long scope text goes in `notes` |
| `WorkPackageQuoteLineItem.exclusion_notes` | max 500 chars | **LOUD** — validation error naming the field + limits (BM-6 fixed) | Summarize; long scope/exclusion text goes in `notes` |
| `allocation_percentage` | **4 decimal places**, max 7 total digits (BM-4 widened from 2 dp / 5 digits) | **LOUD** — validation error if exceeded | Splits can carry 4 dp now; round to 4 dp before writing |
| `quantity_override` | **4 decimal places**, max 16 total digits (BM-5 widened from 2 dp) | none — 4-dp takeoff quantities are kept | Send up to 4 dp; the tail is preserved (`update_estimate_item` docs: "up to 4 decimal places are kept") |
| `estimated_unit_price` | 2 decimal places | **SILENT** — value is rounded to 2 dp on write (NOT changed by BidManager#1027) | Round to 2 dp explicitly before writing so the stored value is the one you computed with |
| `Component.quantity` / `Component.unit_cost` | zero is not storable (`create_component` / `update_component`) | **SILENT** — `quantity=0` is coerced to `1.0`; `unit_cost=0` is ignored (AAR 2026-07-29 §2.1; unfixed as of 2026-08-15 — upstream ask BM#1136) | Never write a $0 placeholder line: omit the component and note it in the parent assembly/item description; when a zero matters, read the component back and compare |

## Tool-signature footguns (field-discovered, bm-sync executor)

Same table shape, but the constraint is the TOOL's signature, not a field
limit. Every caller of these tools inherits them — not just bm-sync.

| Tool.param | Constraint | Failure mode | What to do |
|---|---|---|---|
| `update_estimate_item` | The MCP tool literally named `update_estimate_item` edits estimate-item **PRICING** fields — quantity is not among them; `estimated_quantity` lives on the BID item | **SILENT** — a "quantity update" through it succeeds without touching quantity (or changes a pricing field you didn't mean to) | To change quantity, resolve the estimate item's underlying `bid_item_id` (`list_estimate_items` / `get_bid_item`), then `update_bid_item(bid_item_id=, estimated_quantity=)` |
| `create_bid_item.crew_assembly_id` | `0` is `update_bid_item`'s clear-sentinel (clears the crew assignment, BidManager #766), but `create_bid_item` validates any non-None value as a real assembly pk | **LOUD** — passing `0` on create errors | OMIT `crew_assembly_id` from `create_bid_item` when it is 0 / unset; use `0` only on `update_bid_item` to clear an existing assignment |

## Rules of thumb

- **Long text → `notes`.** The `notes` fields are unbounded in practice; the
  short varchar fields (`contact_info` 200, `exclusion_notes` 500) are not.
  Never pack scope narrative into a varchar field. Over-length now returns a
  clear field-named error (BM-6) instead of a raw Postgres exception, but the
  limits themselves are unchanged.
- **Precision, by field.** `quantity_override` and `allocation_percentage` keep
  **4 decimal places** now (BM-4/BM-5) — takeoff quantities and percentage
  splits carry their tails. `estimated_unit_price` still stores **2 decimal
  places** and rounds silently, so round it in your own arithmetic *before* the
  write, so downstream math (extensions, roll-ups, cost ÷ pay-quantity unit
  prices) uses the value BidSheet.ai will actually store.
- **Silent ≠ safe.** A write that returns success can still have changed your
  number — `estimated_unit_price` rounds to 2 dp. When a value matters to the
  bid math, read it back and compare.
- **Zeros don't survive.** `create_component`/`update_component` coerce
  `quantity=0` to `1.0` and ignore `unit_cost=0` — silent, directional,
  always inflating (a $0 placeholder became a phantom $300 charge). There is
  no way to store a legitimate zero: omit the line and annotate the parent
  description instead. This is the AAR's single highest-risk defect; if the
  upstream fix lands, re-verify before dropping the habit.

## History (pre-2026-08-06, for context)

Before BidManager#1027, `quantity_override` and `allocation_percentage` stored
only 2 dp (quantity_override *silently truncated* 4-dp takeoff values — the
dangerous one), and over-length `contact_info` / `exclusion_notes` surfaced as
raw Postgres `value too long` errors that didn't name the field. If you meet any
of that behavior, the server is running a pre-fix build — surface it.
