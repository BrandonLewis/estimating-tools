---
name: intake-project
description: Start a bid in one command — scaffold a Work-layout project (project dirs + B<bid>-<date> bid working dir) from a BidSheet.ai project ref, snapshot its bid schedules/items into the project manifest (the pricing frame for takeoff → estimate), register plans/specs/addenda and conformed.ai conformance artifacts, then hand off to project-briefing. Via the BidSheet.ai + conformed MCPs; writes local files only.
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Intake a Project ("start a bid in one command")

Use this to stand up a new bid workspace from a BidSheet.ai project. It
produces: the Work-layout folder tree (project shared dirs + bid working
dir), `manifest.json` (documents + bid frame), a seeded
`<bid dir>/Takeoff/takeoff_map.skel.yaml`, and (via `project-briefing`) the
briefing pack. Requires the BidSheet.ai MCP; conformed MCP optional.

## Why the bid frame matters
Official bid-item quantities are the agency schedule — immutable (BM #984;
canonical rule: the `estimator-agent` agent's BidSheet.ai write safety).
Downstream, takeoff quantities land as **estimate structures** resolved to
estimate items by `(schedule, item_number)` (`push-takeoff`,
estimate-structures target), pricing creates estimate items from the same
keys (`price-estimate`), and the model-vs-official advisory check compares
against the frame's `estimated_quantity`. Snapshotting the bid frame at
intake is what lets every later artifact — DXF layers, IFC quantities,
takeoff rows, structure sections — carry keys that resolve to real BidSheet.ai
rows. Rollup bid items (many structures paying into one item) are mapped in
the briefing pack's `structures.yaml`, not here — the bid frame is
BidSheet.ai's truth only.

## Workflow
1. **Resolve the project:** ask the user for the BidSheet.ai project (name or
   id); `mcp__bidmanager__search_projects` / `mcp__bidmanager__get_project` to confirm. Note `project_id` and the
   `organization_id`. Ask for the bid number and bid date (they name the bid
   working dir, e.g. `B1042-2026-07-16`; the CLI accepts letters, digits,
   `.`, `_`, `-` for the number and requires `YYYY-MM-DD` for the date).
2. **Scaffold + manifest:** if working inside the Work repo and its `work` CLI
   is available (`Tools/.venv/Scripts/work`), run `work project new` and
   `work bid new` first — they seed the takeoff/bid-item xlsx templates that
   est-intake deliberately does not replicate. Verify the seeded templates
   are blank of prior-project content (see `scaffold-project`'s
   stale-scaffold guard) before continuing. Then (either way):
   `est-intake init "<Project-Name>" --parent <dir> --bid-number <NNNN>
   --bid-date <YYYY-MM-DD> --organization-id <org> --bm-project-id <id>
   --project-ref "<short ref>"`. est-intake layers safely over existing
   dirs/files. If it refuses (manifest exists), this project is already
   intaken — switch to updating it (steps 3–5 are all idempotent).
3. **Snapshot the bid frame:** `mcp__bidmanager__list_bid_schedules(project_id)` and
   `mcp__bidmanager__list_bid_items(project_id)`; save the raw items list to a temp JSON file;
   `est-intake bid-frame <project-dir> --items <file>`. Review the seeded
   `Takeoff/takeoff_map.skel.yaml` with the user — flag bid items that landed
   in the "no cost code" comment block (they can't receive BIM quantities
   until coded) and any in the "sharing an already-mapped cost code" block
   (rollup items needing a manual split) or the "pay unit est-bim cannot
   convert" block (take off by hand or choose a proxy unit). If the project
   has no bid items yet, skip and tell the user to re-run this step after
   `push-estimate`/manual item entry.
4. **Register documents:** for each plans/specs/addenda file the user has
   downloaded (BidSheet.ai has no document-download API yet — see the upstream
   ask in docs/superpowers/specs/2026-08-02-bm-document-endpoints-ask.md),
   copy it into the project's `Plans/`, `Specs/`, or `Addenda/` dir and run
   `est-intake register <project-dir> <file> --kind <plans|specs|addenda> --source local`.
   The file must live inside the project root — register refuses paths
   outside it.
5. **Conformance (optional):** if the conformed MCP is connected, run the
   project's plans/specs conformance check with the conformed tools, save the
   report under `Supplemental-Info/Conformance/`, run the audit checks in
   "Conformed output is advisory" below, and register it with
   `--kind conformance --source conformed`.
6. **Brief:** invoke the `project-briefing` skill to build the briefing pack
   from what was intaken.
7. **Report:** show the tree created, the manifest summary (document count by
   kind, bid-frame size + snapshot time), and anything skipped.

## Conformed output is advisory — audit before trusting

A first-party audit of conformed.ai output against its seven source PDFs
(2026-08) found five failure modes. Run these checks on every conformance
artifact before registering it, and record exceptions in the briefing
pack's `risks.md`:

1. **Numeric fields may flatten ranges.** A working-day RANGE (65–90) came
   back as the scalar "90" — and propagated into BidSheet.ai. Re-read every
   time- or money-bearing value (working days, liquidated damages, phasing
   durations) from the source spec pages; never carry a conformed scalar
   into the bid frame or an estimate unverified.
2. **Blank-page rate.** 82 of 234 pages — 64% of the document's total
   bytes — were silently `is_blank: true`: no OCR, no warning; scanned
   sheets are invisible.
   Count the artifact's `is_blank` pages, report the ratio, and spot-check
   a few flagged pages against the source PDF.
3. **Coverage is sparse.** Only 2/234 pages were summarized, and there is
   no page→sheet mapping (token-splitting also defeats heading search).
   Treat summaries as pointers, not coverage — never conclude "not in the
   specs" from conformed search alone; search the registered source PDFs.
4. **`confidence_score` is meaningless** (0.0 on every page observed). Do
   not use it as a quality signal.
5. **Size metadata is unreliable** (`total_size_mb: "0.00"` observed). Do
   not use it as a completeness check.

## Notes
- Local files only — this skill never writes to BidSheet.ai.
- Re-running is safe: `register` replaces by path, `bid-frame` re-snapshots,
  and the briefing builder never overwrites existing prose.
