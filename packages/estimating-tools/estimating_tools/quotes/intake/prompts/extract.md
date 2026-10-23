# extract — instructions

You are given a work file listing quote documents and the work packages the
estimate buys from vendors. Read each document and transcribe its header
fields and every priced line, mapped onto the package lines. Write a results
file:

```json
{"stage": "extract", "schema_version": 1,
 "results": [
  {"sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
   "doc_type": "quote", "reason": null,
   "vendor_name": "Dirt Movers", "work_package_name": "Hauling",
   "quote_date": "2026-10-20", "quote_ref": "Q-1042", "surcharge": 0.04,
   "conditions": {"Fuel surcharge": "4% of invoice"},
   "needs_review": [],
   "lines": [{"description": "Haul import and export", "item_number": "2",
              "line_name": "Haul, import + export", "unit_price": 16.5,
              "quantity": 460, "unit": "CY", "extension": 7590.0, "page": 1}],
   "extras": [{"description": "Standby time", "printed_price": 125.0,
               "printed_unit": "HR", "page": 1}]},
  {"sha256": "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
   "doc_type": "not_quote", "reason": "a plan sheet, no prices"}]}
```

A `text` document carries `text_path` — read that file. A `vision` document
carries `image_paths` — open the PNGs. A results file that fails the schema
loads **nothing**.

## The rules that matter most

**1. Transcribe `unit_price` and `extension` exactly as printed.**
Never compute either from the other. Never back-solve
`unit_price = extension / quantity`. Never recompute
`extension = quantity × unit_price`. Never reconcile them, never round, never
"fix" arithmetic that looks wrong.

If a line's printed unit price and printed extension contradict each other,
**report both as printed**. The contradiction is the signal: it is what flags
the quote for human review. Silently correcting it erases the only evidence
anyone will ever have that the vendor's document was inconsistent — and the
number that then lands in the spread is one no vendor ever quoted.

The same holds for a total that does not equal the sum of its lines. Transcribe
what is printed.

**2. A document you cannot read is returned as `unreadable`, never as an empty quote.**
If you got to a document and cannot read it — `image_paths` is empty or
missing, the text file is empty, the pages are illegible — return it with
`doc_type: "unreadable"` and a `reason`. It is listed in the report for the
estimator and is not offered again. Do **not** return it as a `quote` with
`"lines": []`: that is a failed read, and it is held. Omit a document from the
results only when you did not get to it in this batch; an omitted document is
offered again on the next batch.

**3. `"lines": []` is only for a genuine lump-sum quote with no itemisation** —
one price for the whole scope and no line breakdown. When you return it, set
`total_amount` to the printed lump sum. A zero-line quote with no
`total_amount` is treated as a failed read and held.

## Package and line mapping

`packages` in the work file lists each work package: its `name`, its `scope`,
the `conditions` it wants answered, and its `lines` (`item_number`,
`line_name`, `uom`, `qty`).

- `work_package_name` is the `name` of the package the quote prices, exactly as
  listed.
- Each priced line names the package line it prices with `item_number` +
  `line_name`, copied from that package's `lines`. `line_name` is null only
  when the item has one line.
- A vendor line that fits no package line, or a second price on a mapped one
  (freight, a size split, an adder), goes in `extras` as printed:
  `description`, `printed_price`, `printed_unit`, `printed_quantity`, `page`.
  Do not force it onto a line.
- The mapping is a judgment; the price is a transcription. Choose the package
  line that the vendor's line covers, but never change what the vendor printed.
- The price keeps the denominator the vendor printed. `unit` names that
  denominator and `quantity` is kept in that unit. When the page prints the
  quantity another way (lb for a $/cwt price, pieces × length for a $/ft price)
  convert the **quantity** and record the printed form in `quantity_basis`.
- When the unit the vendor prices in differs from the package line's `uom`, add
  a `needs_review` reason naming both units. Never restate the **price** per the
  package line's unit.

## `doc_type`

- `quote` — a vendor price for work or material.
- `not_quote` — a drawing, a spec, a cover letter, a bid form with no prices;
  say why in `reason`.
- `unreadable` — you could not read it; say why in `reason`.

Return **one result per package a document covers**: a quote that prices
Hauling and Valves is two results with the same `sha256` and different
`work_package_name`. Two results may not cover the same document and package.

## Line state

- `unit_price` is the printed price, per the printed denominator named in `unit`
  (not converted to the package line's `uom`; see the mapping rules above).
- `folded_into` — set it to the `line_name` of another line when the vendor
  rolls this scope into that line's price. The line carries no price of its own.
- `is_included: false` with the vendor's words in `exclusion_note` for a written
  exclusion. Leave `is_included` out when the document says nothing.
- `is_alternate: true` for an option priced outside the base bid.
  An alternate may repeat the priced line's `item_number` and `line_name`
  (an option on the same scope); only one non-alternate line per key.
- `lines: []` plus `total_amount` for a lump sum (rule 3).
- `total_covers_unpriced: true` when a printed `total_amount` covers lines you
  did not itemise.
- `conditions` — an object of short phrases from the document. Keys that match a
  package's `conditions` land under exactly those keys; other terms the vendor
  states keep the vendor's own key.
- `needs_review` — a list of reasons, set whenever you are unsure, whenever the
  document covers more than one project, or whenever something about the pricing
  does not add up. Add a per-line `review` note on the line concerned. Flagging
  costs a human a minute; a wrong price taken silently costs a bid.

## Fields

- `vendor_name` — the vendor as printed on their letterhead. Required for a
  `quote`. A `.docx` whose letterhead is a logo image prints no name anywhere a
  text reader can reach it. Those files carry a block marked
  `[docx file metadata -- not printed on the page]` holding the package's own
  `author` / `last_modified_by` / `company`. Use it as a **last resort** and add
  a `needs_review` reason when you do: `last_modified_by` is whoever saved the
  file last, which on a quote we have annotated is us, not the vendor. Never
  prefer it over a name that is on the page.
- `surcharge` — a fraction of the invoice (0.04 for 4 %), only when the vendor
  prints a percentage fuel/energy surcharge as a rate; otherwise null.
- Any header field not stated on the document is `null`. Do not infer it.
- `quote_date` — write it as `YYYY-MM-DD`. Quotes are compared by date, and the
  comparison is a string comparison, so `1/15/2026` sorts before `2025-01-01`.
  Numeric dates on these documents are US month-first (`03/04/2026` is 4
  March). Transcribe an unreadable or partial date as `null` rather than
  guessing at it.
- **`quantity` and `unit` must match what the unit price is printed *per*.**
  This is the rule that makes a line checkable and comparable, and the one
  most often got wrong. Read the denominator on the printed price and put the
  quantity in that unit:

  | printed price | quantity to store | unit |
  |---|---|---|
  | `$108.00/cwt` beside `112,860.00 lb` | `1128.6` | `CWT` |
  | `$83.00/ft`, 2 pieces @ 19.00 ft | `38` | `FT` |
  | `$5,332.00/ea`, 4 pieces | `4` | `EA` |
  | `$125/hr`, `9 DAYS x 8 HRS` | `72` | `HRS` |
  | `$2.85/LB`, 12,400 lb | `12400` | `LB` |

  A steel mill's table prints Pieces, Length, **and** Weight; which column is
  the quantity depends entirely on the price's denominator, and it can differ
  line to line **within one quote**. Never assume the piece count is the
  quantity.

  Put the printed form in **`quantity_basis`** whenever the quantity you store
  is not the number printed in one cell — `"54 pieces @ 19.00 ft; 112,860.00
  lb"`, `"9 DAYS x 8 HRS"`. Nothing is lost that way, and a later reader can
  see where the number came from.

  Converting lb to cwt, or pieces × length to feet, is **not** the forbidden
  computation: those are printed quantities in printed units, and the printed
  extension proves the reading. What you must never do is derive a *price*.
  If the resolved quantity times the printed rate does not reproduce the
  printed extension, transcribe the cells as printed and add a `needs_review`
  reason — do not hunt for a quantity that makes it work.

- **`freight_unit_price` — a second rate on the same basis.** Steel mills print
  a Freight Price column beside the unit price, and the Extended Price covers
  **both**: `1,128.60 cwt × ($108.00 + $18.00)` is the $142,203.60 they print.
  Transcribe each rate into its own field, exactly as printed. Never add them
  into one combined rate — `$126.00/cwt` is a number the vendor never wrote,
  and once stored it is indistinguishable from one they did.
- `is_included` — `false` **only** when the document marks that line excluded
  or not-in-contract. Leave it out (or `null`) when the document says nothing.
- `exclusion_note` — the vendor's own words, ≤500 chars.
- `page` — the page the line was read off, so an OCR dispute is traceable.

Copy each `sha256` exactly as given.
