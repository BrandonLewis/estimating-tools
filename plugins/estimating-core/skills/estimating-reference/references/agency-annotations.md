# Agency bid-schedule annotations & payment semantics

Agency bid schedules carry a semantic layer on top of item/quantity/unit —
annotations and payment conventions that change what a quantity MEANS and
where cost must be carried. The meanings below are the commonly observed
(Caltrans-style) ones; **always confirm against the issuing agency's own
glossary** — the discipline is checking, not memorizing.

## Item annotations

- **(F) — final-pay quantity.** The listed quantity is the paid quantity;
  it is not re-measured. Over/under-run risk is the bidder's: verify (F)
  quantities by takeoff BEFORE pricing, and treat a measured mismatch as a
  finding to raise pre-bid, not a number to quietly absorb.
- **(N) — no separate payment.** The work is real but pays inside other
  items. Identify WHICH items carry it and make sure the cost lands there —
  work that pays nowhere is work priced nowhere.
- **Lump-sum vs unit-price taxonomy.** LS items carry quantity risk (yours),
  unit items carry rate risk. For an LS structure item with no stated
  quantity, build a rough envelope-volume estimate purely as a SCALE check
  ("treat that as a scale check — not a takeoff") before accepting any
  quote or plug number.
- **Plan work with no pay item** (e.g. embankment shown but unlisted): find
  the item it pays under, or RFI it — never assume it's someone else's.

## Payment envelopes vs measured work

Structural excavation and backfill are commonly **measured to standard-plan
payment envelopes** (e.g. A62C/A62E), not as dug. Everything outside the
envelope — sloping back a deep bank, shoring, over-excavation — is unpaid:
price it deliberately in the affected items; do not assume it disappears
into the excavation unit price. The takeoff must carry BOTH numbers (pay
envelope and actual dig) — same cost-vs-pay discipline as
`quantity_override` in the push-takeoff skill.

## Regulatory-hazard pricing

When a regulated hazard applies (e.g. naturally-occurring asbestos /
serpentine soils: air-district dust-control minimums, Class II asbestos
work rules, posted vehicle-speed limits, wind-speed work stoppages), carry
its costs EXPLICITLY in the affected unit prices (grading, haul): dust
control, segregation, capping, monitoring, PPE, and the productivity hit
from speed/wind limits are significant — never leave them implicit in a
unit price where they vanish.
