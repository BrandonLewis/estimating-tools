---
name: subcontract-risk-review
description: Pre-signature commercial review of a GC's subcontract package — find the risk-shifting terms (pay-if-paid, notice waivers, markup caps, flow-down, damages, termination, retainage, T&M conditions), state each with its clause citation and cost consequence, and produce a consolidated negotiation-targets list. Every flagged term is priced, qualified in the proposal, or negotiated before signing — never silently absorbed. Triggers include "review the subcontract", "sub agreement terms", "pay-if-paid", "what's in their general conditions", "risk review before we sign".
---

# Subcontract Risk Review

A GC's subcontract package (agreement + general conditions + supplemental
conditions) allocates risk, and the allocation costs money whether or not
anyone reads it. This review finds the terms that move risk onto the sub
and forces a decision on each: **price it, qualify it in the proposal, or
negotiate it before signing.** Silently absorbing a term is the one
outcome this skill exists to prevent.

**This is an estimator's commercial review, not legal advice.** Its job is
to arm pricing and negotiation; the marked-up terms go to counsel before
anything is signed.

## How to read the package

Read the SUPPLEMENTAL conditions first — revisions and added sections are
where a standard form gets sharpened against the sub (a "Rev" that
replaces a base-form payment clause is usually the pay-if-paid). Then the
general conditions, then the agreement's blanks (retainage rate, markup
figures). For every finding record: the clause citation, the operative
language (quote the sharp phrases verbatim), the cost consequence, and the
proposed target.

## The checklist

- **Payment conditionality.** Pay-if-paid as a *condition precedent* —
  language like "payment by the Owner ... is a condition precedent" or the
  sub "expressly assumes the risk" of owner non-payment — puts the owner's
  credit risk on the sub. Target: convert to pay-when-paid (timing, not
  conditionality), or price the financing exposure.
- **Notice and claim windows.** Short fuses (2 business days is seen in
  the wild) framed as an "absolute and irrevocable waiver" of the change
  or claim — sometimes expressly "regardless of whether [the GC or Owner]
  had actual knowledge ... or was prejudiced." Also watch for a separate,
  earlier notice deadline keyed to the GC's own deadline to the owner.
  Cost consequence is operational, not hypothetical: the job needs a
  disciplined daily notice/claim process or it forfeits change rights —
  **put the PM/admin time in the bid.** Target: widen the windows; strike
  the no-prejudice waiver language.
- **Markup caps.** A cumulative overhead-and-profit cap across the sub
  AND all lower tiers combined (20% appears in the wild), often extended
  by a separate clause to all change-order pricing. Verify your standard
  markup PLUS any sub-tier markups (rebar, trucking) fit under the cap;
  if not, negotiate or price the compression.
- **Flow-down breadth.** Incorporation of the prime contract "as
  specifically and generally applicable," plus the conflict rule that the
  "more burdensome, costly, and stringent provision upon the Subcontractor
  shall govern." A clause noting that citing specific prime sections "does
  not affect the general nature" of the flow-down means everything flows
  down. Target: carve out expressly negotiated terms from the
  more-burdensome rule; obtain the prime contract and READ the sections
  that flow down (retainage, damages, schedule).
- **Consequential damages.** A "mutual" waiver with a one-sided
  exception — the GC does not waive third-party or owner consequential
  damages it may owe *because of the sub's* act or omission — leaves the
  sub exposed to pass-through consequentials. Target: carve back the
  exception or cap it.
- **Termination for default.** Completion costs plus attorneys'/experts'
  fees plus a markup (15% seen) charged back, liability beyond the unpaid
  balance, and a cure period as short as 2 business days to COMMENCE cure.
  Check whether a wrongful default termination converts to termination for
  convenience (it should — negotiate it in if absent).
- **Termination for convenience.** "At any time and for any reason,"
  recovery limited to actual cost plus a markup with **no lost profit** on
  uncompleted work. Price mobilization-heavy scopes accordingly.
- **Retainage.** Watch the greater-of trap: retainage at the agreement's
  rate "or the Prime Contract rate, whichever is greater." Confirm the
  prime's rate before assuming the agreement's figure.
- **T&M payment conditions.** Daily tickets signed by the GC's
  superintendent *or no payment*, one day's work per ticket — another
  operational discipline to staff, not a formality.
- **Withholding rights.** Broad rights to withhold for defective work,
  "doubt of completion," claims, penalties — including the
  GC's attorneys' fees.
- **Self-perform / back-charge rights.** The GC may reassign or
  self-perform scope "to avoid a critical path delay" in its sole
  discretion, with a deductive change order for replacement cost plus the
  GC's added costs — a schedule-pressure lever pointed at the sub.

(Clause numbers vary by form; the citations above describe where such
terms typically live, not fixed addresses. Quote the actual package's
sections.)

## Output

A review memo, one section per flagged term:

```
## <Term family> — <clause cite>
**Finding:** <operative language, sharp phrases quoted verbatim>
> Impact: <what it costs / what process it forces / what it forfeits>
> Target: <the negotiation ask, or "price it: <how>" or "qualify: <text>">
```

Close with the consolidated **negotiation-targets list** — the handful of
asks worth spending negotiating capital on, ranked — followed by the
price-or-qualify decisions for everything not worth a fight. Route the
memo to counsel with the package.

## When to run it

When a work package's strategy goes `sub_out` in `manage-work-packages`
the org is on the RECEIVING end of quotes and will countersign someone's
paper — run this before signing anything, including the GC's subcontract
when the org is the sub bidding to a prime (the exemplar case), and
before executing subcontracts downstream of `solicit-quotes`.
