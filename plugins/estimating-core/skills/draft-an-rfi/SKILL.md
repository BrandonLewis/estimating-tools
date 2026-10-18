---
name: draft-an-rfi
description: Draft a pre-bid RFI (Request for Information) as an evidence-backed letter — numbered sheet/spec references, a worked derivation, pre-refuted alternative readings, quantified dollar impact, and a bid-deadline ask — written to the bid working dir's Correspondence/drafts and logged; the estimator reviews and sends, never the skill. Triggers include "draft an RFI", "write a bidder inquiry", "raise this with the Engineer", "RFI the quantity", "pre-bid question".
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

# Draft an RFI

An RFI is an evidence-backed argument, not a question. The discipline that
makes one land: every assertion cites a numbered reference, the defensible
figure is derived (not asserted), the alternative readings are refuted
BEFORE writing so the request is specific rather than open-ended, and the
dollar impact makes the timing argument for answering pre-bid. The
deliverable is a DRAFT — **sending stays a human act.**

## Where RFIs come from

- **The conflict ledger.** Unresolved rows in the briefing pack's
  `risks.md` (see the `estimating-reference` skill's `conflict-ledger.md`)
  are the standing queue — two conflicting values are a question for the
  Engineer, never a midpoint.
- **Takeoff findings.** A measured quantity that misses the paid quantity
  is a finding; when the gap survives re-measurement, it becomes an RFI.
- One RFI = one issue. State the scope discipline in the letter ("this
  request addresses quantity only") and raise the second issue separately.

## Workflow

1. **References first.** Build the numbered list — each entry
   `{num, reference, description}` where `reference` is a precise citation
   (sheet number + table name, spec item + page, report section) and
   `description` is a **verbatim quote** of the governing clause or the
   transcribed data. Every factual sentence in the body will cite a number.
   Where possible, make two independent documents corroborate each other —
   agreement between sources the Engineer's team produced separately is
   the strongest evidence you can cite.

2. **Work the derivation.** For a quantitative issue, compute the
   defensible figure element-by-element (support-by-support,
   span-by-span), then state the delta in absolute AND percent terms.
   A reviewer should be able to re-run the arithmetic from the letter
   alone.

3. **Refute the alternatives before writing.** Under an explicit heading,
   enumerate every reading that would close the gap and knock each down
   with a citation. This is what turns "please clarify" into a specific,
   answerable request. For a document-vs-document conflict where no single
   derivation exists, pit the cited values against each other and ask the
   Engineer to reconcile — **never average them.**

4. **Quantify the impact and make the timing argument.** Price the delta
   at engineer's-estimate or plausible unit prices. For unit-price,
   measured-at-final items the argument writes itself: bidders spreading
   fixed cost across the wrong quantity produces non-comparable bids —
   resolving it pre-bid removes that spread from every bid.

5. **Ask specifically.** Enumerate the asks: confirm the governing
   interpretation, provide the derivation or a corrected value, and close
   with the completeness move — *"if the shown values stand, say so
   expressly"* — so ANY answer leaves every bidder pricing the same thing.
   Tie `response_by` to a procurement milestone (before advertisement,
   with the addendum, N days before bid), not a bare date.

6. **Write the draft.** Markdown with letterhead frontmatter to
   `<bid working dir>/Correspondence/drafts/<bid>-RFI-<nnn> - <subject>.md`:

   ```yaml
   ---
   engine: letterhead
   rfi_no: <bid>-RFI-<nnn>
   date: <today>
   project_name: ...          # + project/owner numbers as known
   to: ...                    # Engineer of Record, Attn:, c: list
   sender: ...                # the prospective bidder
   discipline: ...
   response_by: <milestone-tied>
   subject: <the entire claim in one sentence — a thesis, not a label>
   signature_name: ...
   signature_title: ...
   references:                # the numbered list from step 1
     - {num: 1, reference: "...", description: "..."}
   ---
   ```

   The `subject:` is load-bearing: state the issue, the figures, and the
   ask in one sentence.

7. **Render letterhead docx (when a profile supplies a template).** If the
   active org profile carries `letterhead.template`:

   Rendering needs docxtpl, the `docgen` extra, which the base install omits.
   Install it into whichever interpreter runs `est-letterhead`, before the
   first render:
   - **Under the plugins**, it is the interpreter they keep under
     `~/.estimating/`, reached only by `~/.estimating/bin/ensure-extra docgen`;
     a bare `pip install` would land somewhere else and change nothing here.
   - **Installed by pip instead**, it is `pip install "estimating_tools[docgen]"`.

   ```bash
   ~/.estimating/bin/est-letterhead "<draft.md>" -o "<bid working dir>/Correspondence/word-docs/<name>.docx"
   ```

   (`--template <path.docx>` overrides the profile's template; run
   `~/.estimating/bin/est-letterhead --help`.) It parses the draft's frontmatter + body,
   merges the profile's letterhead fields under the draft's frontmatter,
   and renders via docxtpl. The same call in Python, when you need to
   assemble the context yourself:

   ```python
   from estimating_tools.profiles import load
   from estimating_tools.profiles.wires import to_letterhead
   from estimating_tools.docgen.docxtpl_engine import render_letterhead

   template, lh_front = to_letterhead(load())   # ESTIMATING_PROFILES cascade
   render_letterhead(template, out_docx, {**lh_front, **rfi_frontmatter},
                     body_md)
   ```

   Output lands beside the draft in `Correspondence/word-docs/`. No
   profile or no `.docx` template → the markdown draft IS the deliverable
   (agnostic fallback).

8. **Log it.** Maintain `<bid working dir>/Correspondence/rfi-log.md`:
   - **Lead with the one item carrying material dollar exposure** — the
     log's first paragraph names it and says it should close before the
     price goes out the door.
   - Log no-price-consequence items too, saying WHY they're logged (e.g.
     "the bar count is the engineer's decision, not ours to change").
   - Bucket Open items: **commercial / technical / arose during this
     implementation** (issues surfaced while building the model or
     estimate, kept so nobody downstream rediscovers them).
   - **Resolved items are retained, never deleted** — the trail of what
     was checked and cleared stays legible.

9. **The DO-NOT-SEND gate.** Drafts carry `status: DRAFT — HOLD` until
   the estimator clears them. The skill (and any mail integration) creates
   drafts only — **never send.** A draft mooted by an addendum is marked
   "(DO NOT SEND — mooted by Addendum N)" and kept, not deleted.

## Notes

- Not every conflict earns an RFI: the conflict ledger's which-governs
  ladder resolves most rows on a stated rule. An RFI is for the rows where
  no rule closes the question — or where the money says the Engineer must
  own the answer in writing.
- Bid the more stringent reading while the RFI is open, and take the
  independent measurement regardless of the answer received.
