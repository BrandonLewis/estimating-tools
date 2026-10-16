---
name: project-briefing
description: Generate the project prompt pack from an intaken project — scope summary, structure list (with rollup mapping to bid items), risk notes, and one per-structure briefing prompt whose frontmatter carries the pricing keys downstream sheet/BIM/estimate agents consume. Reads the manifest + registered documents; writes Briefing/ files locally.
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

# Project Briefing (prompt pack)

Use after `intake-project`. Input: a project directory containing
`manifest.json` and registered documents. Output, under the bid working dir:
`Briefing/scope.md`, `Briefing/risks.md`, `Briefing/structures.yaml`, and
`Briefing/prompts/<structure_id>.md` — the files later phases' agents assume
exist. Sheet and BIM agents read a structure's prompt frontmatter to know
which `(schedule, item_number)` pairs its quantities must key to, and the
`structure_id` becomes both `TakeoffRow.structure_id` and the estimate
structure's id when `push-takeoff` calls `create_structure`.

## Workflow
1. **Read the manifest:** `ProjectManifest.load(<project>/manifest.json)`
   (module `estimating_tools.intake.manifest`). Confirm documents and a bid
   frame are present; if not, run `intake-project` first.
2. **Survey the documents:** use the `pdf-extraction` skill on the registered
   plans/specs (sheet index, spec table of contents, bid schedule pages).
   If a conformance artifact is registered, it is advisory only — see
   intake-project's "Conformed output is advisory" gate (flattened ranges,
   silent blank pages, sparse summaries). Re-read working-day / liquidated-
   damages / phasing values from the source pages and note any conformed
   gaps in `risks.md`.
3. **Identify structures and their rollups:** propose the list of structures
   being bid (each a thing that gets its own sheets/BIM model in Phases 2–3:
   headwall type, culvert, outfall, pump station…). Rollup awareness is the
   point of this step — a bid item like "Structural Concrete (Headwalls)" may
   be paid by quantities from 30 headwalls. Model that as either one structure
   entry with `count: 30` (identical units priced once and extended, like the
   Work repo's structure_estimate.py "Each × Qty" summary) or several entries
   (distinct types) all pointing at the same bid item. For each structure
   gather: a kebab-case `id` — lowercase letters, digits, hyphens; the
   builder rejects anything else and rejects duplicates — (this becomes
   `TakeoffRow.structure_id` and the estimate structure's id), display name,
   `count`, the cost codes it will carry, and `bid_items` — the
   `[{item_number, schedule}]` pairs its quantities pay into (each must exist
   in the manifest's bid frame). Review the list with the user before
   writing.
4. **Write structures.yaml + skeletons:** save the agreed list as
   `{structures: [...]}` to a temp YAML, then
   `~/.estimating/bin/est-intake briefing <project-dir> --structures <file>`. Prose files and
   prompts are created once and never overwritten; `structures.yaml` itself
   is regenerated to stay in sync with the full list on every run.
5. **Author the prose:** fill in `scope.md` (what's bid, owner/agency,
   delivery method, key dates), `risks.md` (access, utilities, water control,
   schedule, escalation, unusual specs — plus the **conflict ledger**: one
   structured row per document conflict, per the conflict-ledger reference
   in the `estimating-reference` skill; unresolved rows become RFIs / open
   questions), and each structure prompt's sections
   (Scope / Geometry & layout / Materials / Quantities & pay items / Risks /
   Sources — cite plan sheets and spec sections). Leave frontmatter untouched.
   If an org/agency profile is active (ESTIMATING_PROFILES), honor its argot
   and terminology in the prose.
6. **Report:** list the structures with their counts and rollup targets, and
   flag (a) any bid item in the frame not covered by any structure (its
   quantity must come from somewhere else) and (b) any bid item covered by
   multiple structures — a rollup — so the user can sanity-check the split.

## Notes
- Re-runnable: to add a structure later, append it to `structures.yaml` and
  re-run step 4 — only the new prompt file (plus the refreshed
  `structures.yaml`) is written.
- The frontmatter is the machine contract; downstream skills parse it. Don't
  reformat it. When *reading* a prompt's frontmatter, extract it by the
  `---` delimiters on their own lines (first line to the next line-anchored
  `---`), never by substring-splitting on `---` — the authored prose may
  legitimately contain horizontal rules.

## Addenda invalidate derived artifacts

A substantive addendum re-opens every artifact derived from what it
changed — not just the briefing pack. Three first-party staleness
instances motivate this: satellite research docs still asserting a design
an addendum had removed; a dimension-control doc internally stale against
the project's own RFI record; a partially revised geometry set whose
sheets no longer agreed with each other. On each addendum:

1. **Enumerate every derived artifact touching the changed topic** —
   briefing prose, structure prompts, research notes, location-data
   scripts, dimension-control docs, takeoff rows — and re-verify each one
   individually. Partial regeneration is how stale satellites happen.
2. **Regenerate with a banner, archive the originals.** Rewritten docs
   carry a "Regenerated — incorporating Addenda N…" banner; superseded
   versions move to an `_archive/` dir, never deleted.
3. **Watch the relettering trap.** A bid schedule's letter can be renamed
   between the base documents and an addendum while its total line still
   cross-references the old label — verify a schedule's identity by its
   total-line cross-reference and item content, not its letter.
4. **Geometry-touching addenda** get the dependent-element re-verification
   rule in the `read-station-plans` skill (calc-bim plugin).
