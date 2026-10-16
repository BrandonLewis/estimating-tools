# The conflict ledger — when bid documents disagree

The single most-recurring judgment lesson in the survey of record: when any
two bid documents disagree (plans vs specs, geotech vs structural, standard
plan vs project sheet, spec section vs spec section), record the conflict in
a structured ledger — never resolve it silently in your head, and NEVER
average the two values.

## Ledger shape

One row per conflict, in the briefing pack's `risks.md` (or its own table
when long):

| Topic | Source A | Source B | Effect | Which governs & why |
|---|---|---|---|---|
| compaction | specs §xx: 90% | geotech §y: 95% | +N hr roller time | 95% — spec §xx defers to the geotech report |

- **Source cells carry citations** (sheet / spec section / report page), not
  paraphrases.
- **Effect is quantified** where possible (CY, LF, $, crew-hours) so the
  exposure is visible — an unquantified conflict is easy to ignore and
  expensive to lose.
- **"Which governs" is picked on a STATED rule, never a preference.**
- Unresolved rows become RFIs / open questions before bid day; resolved rows
  keep their reasoning so a reviewer (or an addendum) can re-test it.

## Governing rules (in order of application)

1. **The contract's order-of-precedence clause**, when one exists — cite it.
2. **Site-specific beats boilerplate.** A stricter site-specific geotech
   recommendation (e.g. w/cm 0.50) overrides a general structural table
   (0.55): "the geotech report governs — site-specific rather than a
   boilerplate default."
3. **Standard governs minimums; the plan governs project-specifics.**
   Building below a standard's minimum is non-compliant; where the plan
   deliberately exceeds or particularizes the standard, the plan wins.
   Quantify the delta (e.g. in CY) and file the RFI when the choice moves
   money.
4. **Direct spec-vs-spec conflicts default to the most stringent** reading,
   escalated via RFI, with approved variances tabulated with citations
   (e.g. one section requiring 15–25% SCM for heat control while another
   prohibits SCM in hydraulic structures — a real, unresolvable-by-reading
   conflict).
5. **Never average.** Two conflicting values are a question for the
   Engineer, not a midpoint: "do not average them, and frame this as an
   RFI."
