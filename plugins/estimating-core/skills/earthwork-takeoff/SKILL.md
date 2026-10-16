---
name: earthwork-takeoff
description: Read grading plans and earthwork specs into bid-ready numbers — the lift/compaction/moisture table, benching and keyway triggers, consolidation-factor mass-haul (cut/fill balance, borrow, import/export), rippability from seismic velocity, and pay-basis discipline ((F) final-pay, payment envelopes, OSHA Subpart P cross-check). Use for mass grading, canal/channel earthwork, borrow, and excavation bid items. Triggers include "mass grading", "earthwork takeoff", "cut and fill", "rippability", "consolidation factor", "mass haul", "read the grading plans".
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

# Earthwork Takeoff

Judgment for turning a grading plan set, an earthwork spec section, and a
geotech report into quantities and risk notes a bid can carry. Every number
below is a **worked example from a real project — extract the equivalent
value from THIS project's spec/geotech and cite the section; never carry a
worked-example value forward as a default.** For station-detailed plan
tables and section geometry, the reading discipline is the calc-bim
plugin's `read-station-plans` skill; for flat-measure items, the
`quantity-takeoff` skill.

## 1. Read the mass-grading spec into a table first

Before computing anything, transcribe the spec's earthwork sections into
one lift/compaction/moisture table with a spec-section citation per row.
Worked example (a mass-grade geotech + spec, values illustrative only):

| Parameter | Worked-example value |
|---|---|
| Lift thickness | ≤ 12 in uncompacted; ≤ 6 in where handheld equipment |
| Relative compaction — general fill | 90% (ASTM D1557) |
| Relative compaction — subgrade / trench backfill / base | 95% (ASTM D1557) |
| Moisture conditioning | 0 to +3% of optimum |

Then hunt for the clauses that change the price, not just the density:

- **Benching/keyways trigger on slope.** Fill placed on slopes steeper
  than a stated ratio (worked example: ≥ 5H:1V) requires a keyway at the
  base (example: trench ≥ 2 ft into firm material, ≥ 10 ft wide) and
  benches cut as the fill rises (example: level surface ≥ 6 ft
  horizontally into firm soil, 4 ft into rock, max 36 in rise between
  benches). That is excavation and recompaction the grading surfaces never
  show — find the trigger slope and the bench dims in the spec and take
  off the benched volume separately.
- **Oversize rock has depth zones.** Example: rock > 24 in prohibited in
  the upper 5 ft of grades and utility corridors; upper 2 ft predominantly
  < 12 in; oversize goes to deep fill or is mechanically reduced /
  off-hauled. On a rocky site this is a processing (breaker/crusher) and
  double-handle cost hidden inside the excavation item.
- **The non-testable → method-spec pattern.** Soils above a stated rock
  fraction (example: > 30% rock by mass) cannot be density-tested, so the
  spec switches to a method specification — a minimum number of covering
  passes with a NAMED compactor (example: ≥ 6 passes with a stated
  steel-wheel compactor class, last three passes at 90°). A method spec is
  priced as equipment hours per covered acre-lift, not as a testing
  allowance — recognize the pattern and price the passes.

## 2. Consolidation-factor mass-haul

Neat fill is not the fill you buy. Compacted-in-place volume divides by
`(1 − consolidation)` to get required borrow/loose volume — the division
convention, `neat / (1 − f)`, not a multiplication by `(1 + f)`.

Worked example (a canal job's earthwork summary sheet — worked example
values; extract per project, never defaults): 640,600 CY cut against
537,200 CY neat fill reads as a **103,400 CY net export** on raw volumes.
Apply the sheet's stated 25% consolidation factor and the 537,200 CY of
neat fill becomes **716,200 CY of required borrow volume — flipping the
job to a 75,600 CY net IMPORT** from borrow pits. A bidder who prices the
raw net is pricing the wrong direction of haul entirely.

- **Work reach by reach, not project-total.** On that same example one
  reach was fill-hungry (−65,100 CY net) while the surplus sat in reaches
  miles away — the mass-haul plan must move surplus across the alignment
  AND import the balance. **Haul distance, not excavation, is the cost
  driver** on lump-sum earthwork items; build the reach table before
  putting a number on the item.
- **Read the borrow constraints.** Engineer-identified pits, equal-draw
  rules, or no-stockpile clauses set the average haul; they are spec text,
  not bidder choices.

Library (`estimating_tools.takeoff.earthwork`):

```python
from estimating_tools.takeoff.earthwork import fill_required_cy, mass_haul

fill_required_cy(537_200, 0.25)   # neat/(1-f) -> ~716,267 CY required borrow
mass_haul(reaches, 0.25)          # per-reach nets + totals, net_import_cy
```

`mass_haul` takes the reach-by-reach cut/fill table (transcribed from the
plans, cited) and returns per-reach raw nets plus consolidated totals with
an explicit `net_import_cy` (positive = must import).

## 3. Rippability — the velocity decision rule

When the geotech includes a refraction-seismic (P-wave) study, the rip vs
blast line is a velocity threshold — but **the thresholds are calibrated
to a stated dozer/ripper class and travel WITH that equipment assumption.**
Worked example (calibrated to a large ripper-equipped dozer named in the
study): rippable < 7,300 ft/s; marginally rippable ≈ 7,300 ft/s;
drill-and-blast ≥ 8,500 ft/s. Quote the study's numbers with its equipment
basis; a smaller spread moves every threshold down.

- **Trench vs mass-grading split.** Standard excavators meet refusal at
  only ~3,500–4,500 ft/s — far below a big dozer's rip limit — so a site
  that mass-grades fine can still need special rock-trenching equipment
  (or blasting) for deep utilities. Price the two operations against
  different velocity horizons.
- **Blasting posture.** Where the documents put blasting on a T&M basis,
  the rip/blast boundary is a bid assumption to state and an RFI/
  qualification topic, not a risk to bury in the unit price. The geotech
  is typically contacted before any blasting — note the procedural cost.
- Specs may also define "rock" contractually (e.g. whatever conventional
  equipment cannot rip, Engineer decides) — a definition that shifts the
  entire classification risk to the bidder. Flag it.

## 4. Pay-basis discipline

- **(F) final-pay items pay the neat plan quantity, never re-measured.**
  Everything you must dig beyond the neat lines to actually build the work
  — the bench, the lay-back, working room — earns nothing: **the bench
  earns nothing; it is priced as hours and equipment only.** Compute the
  real dig for cost, the neat volume for pay, and never let the two swap
  places.
- **Payment envelopes.** Structural excavation/backfill are measured to
  the standard-plan pay envelopes (e.g. a Caltrans A62C/A62E-class limit
  diagram), not as dug. Sloping back a deep bank or shoring outside the
  envelope is unpaid work — price it deliberately; do not assume it
  disappears into the excavation unit price.
- **Benched-dig volumes** (`estimating_tools.takeoff.earthwork`):

  ```python
  from estimating_tools.takeoff.earthwork import (
      prism_cy, wedge_cy, bench_increment_cy)

  prism_cy(length_ft, width_ft, depth_ft)          # neat pay prism
  wedge_cy(length_ft, depth_ft, run_ft)            # one-face lay-back
  bench_increment_cy(length_ft, width_ft, depth_ft, run_ft)
  ```

  `bench_increment_cy` is the benched pit prismatoid MINUS its own neat
  prism — the unpaid increment only. Returning the raw pit volume
  double-counts the pay volume (a real bid's bench check came out 640 CY
  against a real dig of 372 CY until the neat prism was subtracted).

## 5. OSHA Subpart P cross-check

Whatever slope the takeoff assumes, check it against 29 CFR 1926 Subpart P:
**Type A soil caps BOTH sloping and benching at 3/4H:1V**, and lesser soils
are flatter still. A modelled estimating proxy steeper than the cap cannot
be dug that way — it means the real means-and-methods (shoring, trench
box, engineered PE design) is **unpriced scope. Flag it** as a finding on
the takeoff; never silently keep the too-steep proxy as if it were a plan.
