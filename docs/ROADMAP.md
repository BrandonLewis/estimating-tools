# estimating-plugin roadmap

**Canonical as of 2026-11-06, main `ee4ed111` (0.1.96 released 2026-11-04; v0.1.97 cut in #449).** This file is the one
place that records what is built and what remains for the estimating platform: the `estimating_tools`
and `bimforge` packages, the `estimating-core` and `calc-bim` plugins, the Estimate Navigator add-in,
and the OpenWorker, OpenCode and public-repository ports. Specs and plans under `docs/superpowers/`
describe intent; they stay in the private monorepo and the public export omits them, so this file
states what each plan decides rather than linking it. This file records status.

**Destination:** an estimator at a firm other than the founder's installs the plugin, signs in to
BidSheet.ai, and takes a bid from plan sheets to a priced, reviewed estimate and back into BidSheet.ai
without the founder's help, in whatever surface they choose to work in.

**How this was built:** a survey on 2026-10-28 of every open issue (28), every open pull request (2),
every local branch and worktree, the 2026-08-01 BIM integration roadmap (phases 0 to 6, all shipped),
the deferred and out-of-scope sections of the last ten design specs, and the plugin-facing items of
BidManager epic #1486 and the roadmap `docs/ROADMAP.md` there. Revised 2026-10-29 after the owner's
ruling on D1, and 2026-11-04 after the quote sync (#416), the first exchange step (#425) and the
BIMForge 0.1.96 and 0.1.97 releases, which were made in the public repository (D7).

Sizes: **S** < 1 day · **M** 1–3 days · **L** 1–2 weeks · **XL** more.

Phase order is a recommendation for discussion, not a ruling.

---

## Order of work

The single list to pick the next task from. Phases below hold the detail; this section only orders it.
Update it in the same PR that finishes or adds an item.

**Now** (in flight or blocking a release)

1. ~~Move bimforge upstream (D7): BIMForge PR #4 (the contour work), bimforge 0.1.98 on PyPI, and the plugin taking it from PyPI.~~ **Done 2026-11-03: BIMForge #4, bimforge 0.1.98, #433.**
2. ~~Merge #430 (the #425 review fixes) and #429 (false pin-override notice, #427).~~ **Done: #430, #429.**
3. ~~Cut v0.1.96 (D8): carries the quote sync (#416, #422, #429, #432), the exchange step 1 (#425, #430) and the `bimforge>=0.1.99` dependency.~~ **Done: #434.** ~~The next release (0.1.97) carries exchange step 2 (#437, #440) and the Phase 0 fixes; the bundled wheels were rebuilt in place at 0.1.96 since, so the release must bump the version.~~ **Done: #449** (also carries exchange step 3, #444 and #446, and #436).
4. Move the open `bimforge` issues to BIMForge's tracker (D3), and port the catalog tests there (BIMForge #5).
5. Model exchange (4.12 to 4.14): the takeoff contract as IDS, the draft family dictionary and the IFC2X3 refusal were built 2026-11-11 and merged in BIMForge #48. Detail and next steps are in BIMForge's `ROADMAP.md`.

**Next** (in this order)

1. ~~Phase 0 field defects: 0.1 cached values (#370), 0.2 apply-takeoff merge (#376), 0.5 (#407), 0.6 modelling routes at briefing (#304).~~ **Done: #370 via #443, #445 and #448 (built-in cached values; the Excel pass is opt-in); #376 via #441; #407 closed; #304 via #447.** The takeoff workbook's cached values are upstream as BIMForge #11. The bimforge defects 0.3 (#314) and 0.4 (#399) are BIMForge's (D7).
2. Phase 1 engine: 1.3 step 3 done (#444, #446); step 4 next (template fill: prototype and package lint, expansion with reference shifting, a template version of HeavyBook's Cost Report), with #439 before the first template pack. Planned in three PRs (the implementation plan is a private design doc, not in the public export): PR A #439 and the writer pieces, PR B the fill, PR C HeavyBook's Cost Report as the first template pack.
3. 1.1 the contract document, written as 1.3 lands so the two cannot disagree.
4. BidManager ops for 1.4: #1676 request_id, #1680 contract_version, #1682 move ops, #1704 member ids, #1701 equipment over time.

**Later**

- 1.11 fieldbook on the contract (spec merged #418), then 1.7 quotes in the contract, which retires the fieldbook sidecar sync from #416.
- Phase 2 onboarding; it gates the destination sentence and D2.
- Phases 3 to 6 in their listed order, bimforge rows after D7 says where they are built.

## Where we are

| Area | State | Notes |
|---|---|---|
| Project intake and briefing | Built | `est-intake`, `intake-project`, `project-briefing`. The briefing records each structure's modelling route: a bimforge family, federated, or bespoke (0.6). |
| Plan-sheet measurement | Built | `est-bim calibrate/vectors/measure/contours`, geometric plus vision-hinted calibration, contour-to-terrain. Clip-path bug 0.4. |
| Sheet production | Built | Control, layout and structure sheets as DXF, PDF, KML. |
| BIM spine | Built, exactness partial | DXF to IFC to takeoff, KMZ, 4D staging, cost-loaded schedule, estimate-model round trip. Bundled bimforge is 0.1.95; BIMForge has released 0.1.96 (shared alignments, placement, station and offset in the IFC, barrier runs on a project line, developed elevations, true arcs) and 0.1.97 (section DXF with hatching, Blender sliders) in its own repository (D7). Square-ended sweeps are exact; skewed ends and lofts are still meshes (4.5, 4.6). |
| Standard-plan families | 14 built | Bridge, barriers (842, 732SW, handrail), box culverts, wingwalls, headwalls, approach slab, retaining walls, pipe supports. B11 barriers (4.1) and sheet piles (4.4) are not. |
| Estimate scaffold, historicals, templates | Built | Phases 4 and 5 of the BIM roadmap. BidManager's as-of rate query (#1018) shipped; repricing on it is unscheduled (3.6). |
| Estimate exchange contract | Specified; interface built | BidManager exposes the estimate read model (`get_estimate_workbook`, row fingerprints) and an all-or-nothing change set (`apply_estimate_workbook_changes`, dry run, 409 conflicts) over MCP and REST. Specs merged (#415, #418). Step 1 merged (#425): the pack interface, the REST client and HeavyBook as a code pack; review fixes merged (#430). Step 2 (follow-ups, declaration, generic reader) planned 2026-11-04: the declaration and the generic stamp shipped (step 2a, PR A); the generic reader reads HeavyBook from its declaration (step 2b, PR B). No published document or versioning yet (1.1, BidManager #1680); the declarative engine is 1.3. Step 3 shipped: patch is the engine's, and est-estimate refresh brings server changes into a book in place. |
| Reference packs: fieldbook, HeavyBook | Built | Fieldbook: `est-estimate build`, sub-spreads, work packages and the carried-vendor choice in the spec and the book. HeavyBook (renamed from HeavyCivil in #425, with a one-release shim): render (0.1.95), read-back (0.1.96), and the generic reader, patch and refresh (0.1.97); two builds from one payload differ only in the export timestamp. Both are reference packs of the contract, not products (D1). Cached-value bug 0.1 fixed (#443, #445, #448). |
| Quote space | Built, both directions (unreleased) | Solicit, coverage, capture, compare, apply, directory sync; quote intake from a watched folder (0.1.95). Fieldbook quote push and pull against BidSheet.ai's carried quote, and the assembly generator (#416, fixes #422, #429): first live push on a bid 2026-11-01. This sidecar sync is the interim path until 1.7 puts quotes in the contract. |
| Estimate Navigator add-in | Pack adapters merged | Reads a stamped workbook, panes and checks. Pack adapters (#411) and HeavyBook insert templates (#412) merged; the HeavyBook adapter and tree panes (1.5 PR 3) and declaration-driven adapters (1.6) remain. No store listing yet (1.10). |
| Plugin runtime and distribution | Built | One manifest, per-client configs, managed-settings templates, SessionStart hooks, bundled wheels, OpenWorker and OpenCode ports. Codex and Gemini adapters for `calc-bim` are not (6.1). |
| Public repositories | Built, manual merge, BIMForge diverged | Every merge to `main` opens or updates one export PR on `estimating-tools`; its PR #13 has waited since 2026-10-25 (6.2). `BIMForge` is exported by hand, and 0.1.96 and 0.1.97 were developed there directly, so the two copies diverged until the reconcile in Order of work (D7, 6.3). |
| Onboarding | Not built | A new user installs, signs in, and then has nothing to do but guess. Design drafted 2026-10-17 (Phase 2). |

## Decisions

| ID | Decision | Ruling, or options and recommendation |
|---|---|---|
| D1 | What the product is | **Decided 2026-10-29.** The product is the exchange contract between an estimating surface and BidSheet.ai: the read model, the change set, the conflict rules and the binding convention that lets any layout be read back. Fieldbook and HeavyCivil are reference packs, kept as examples and as the proof that the contract is complete. A user builds the workbook they want, or no workbook at all (a desktop app over REST), and the data still agree. Packs have two layers: a Python interface (an entry point, the way `bimforge.style_packs` works) that any surface implements, and a declarative binding engine that is the default implementation, so most workbook packs need no code. **Rulings 2026-10-31** (specs PR #415): HeavyBook is the reference pack and conformance oracle; fieldbook conforms from day one behind its own design spec (1.11). The binding convention is derived structure, stored identity, position wins. The apply is idempotent on a client `request_id` (BidManager #1676). The CLI carries the read model and the change set over REST as the user; the agent orchestrates and never relays a payload. No hooks: a pack declaration is pure data. The book is a living document: patch in place after every push and refresh, never regenerate. The estimate spec YAML is an authoring input consumed once; no export. |
| D2 | Where development happens | The public `CONTRIBUTING.md` says development moves to `estimating-tools` once the private layer is a plain package installed on top. When: before or after onboarding (Phase 2) ships. **Recommendation:** after Phase 2 and 6.4; the fixture provenance work is the real gate. |
| D3 | Home for bimforge issues | Today every bimforge issue is filed here with the `bimforge` label and the `BIMForge` repo has no issues, though it now has merged PRs (#2, #3). Follows D7. **Recommendation:** issues live wherever D7 puts development. |
| D4 | Python floor | **Decided 2026-11-06.** The floor is 3.11 (0.1.98, bimforge 0.1.108): 3.10 reaches end of life in October 2026 and current dependency fixes (pillow 13, scipy 1.16) need 3.11+. CI runs 3.11 and 3.13; the runtime picks 3.11 to 3.14. The 0.5 segfault was a test bug (#423), not the interpreter. |
| D5 | Navigator store listing | The 2026-10-18 design decided to submit the generic build to Microsoft AppSource at v1 with a sample workbook, an empty state and store pages. Submit now with fieldbook only, or after the adapters read any pack. **Recommendation:** after 1.6, so the first listing reads both reference packs. |
| D7 | Where bimforge is developed | **Decided 2026-11-04: BIMForge is upstream (option b).** Opened 2026-11-04. The export script assumes this repository is upstream and BIMForge a copy, but BIMForge 0.1.96 and 0.1.97 were built and released there, while #400, #402 and #404 were built here. A normal export would have erased the BIMForge work. Options: (a) this repository stays upstream and BIMForge takes no direct commits; (b) BIMForge becomes upstream, this repository bundles its released wheel, `packages/bimforge` and the export script retire, and the release gate stops requiring bimforge's version to equal the plugin's. **Recommendation:** (b). It is the end state the export script's own docstring names, and it is how the work is already happening. |
| D8 | Next version number | Follows D7. The plugin's contour work goes upstream (BIMForge PR #4) and ships as bimforge 0.1.98 on PyPI, since a PyPI version cannot be re-uploaded with other contents. The plugin then drops `packages/bimforge`, depends on `bimforge>=0.1.98`, bundles that released wheel, and its release gate stops checking bimforge's version (all done 2026-11-03: BIMForge #4, bimforge 0.1.98, #433). **Recommendation:** the next plugin tag is v0.1.96, carrying the quote sync, exchange step 1 and the bimforge dependency change. |
| D9 | IFC schema | **Decided 2026-11-11.** IFC4X3 is the target and IFC4 the fallback; Revit does not open IFC4X3, so Revit exchanges on IFC4. IFC2X3 is not supported: bimforge refuses it by name (4.14). `docs/ifc-takeoff-contract.md` said IFC2X3 opens; it never read a classified IFC2X3 element. |
| D10 | buildingSMART Data Dictionary (bSDD) | **Decided 2026-11-11.** The family vocabulary is one dictionary file in bSDD's import format, kept in BIMForge, so bimforge, Revit and Tekla name the same thing the same way (4.13). Publishing to the bSDD service, calling its API and stamping bSDD URIs on classifications are deferred: Caltrans bid items and the org's cost codes are not in bSDD and nothing downstream reads a URI. Reopen when an owner requires it or third-party models arrive classified against bSDD (4.19). |
| D6 | Fixture provenance | #322: three estimate-spec fixtures derive from a real public-works bid and one test reads a local-only path. Rebuild them from a published agency bid tab, or keep them private and excluded from the export. **Recommendation:** rebuild; it is a prerequisite for D2. |

---

## Phase 0 — Field defects

Bugs found on live bids or in CI. Each is independent and small; do them first.

| ID | Item | Where | Size |
|---|---|---|---|
| 0.1 | **Done #443, #445, #448: `estimating_tools.xlcalc` caches values after the fieldbook build, the HeavyBook build and every HeavyBook patch; the Excel pass (#443) is opt-in (`--recalc excel`); the takeoff workbook is BIMForge #11.** ~~#370 Every openpyxl workbook stores formulas without cached values, so Excel Protected View, Google Sheets preview and `data_only` readers show 0. Round-trip through a calculating engine on build, or write cached values. Covers fieldbook, takeoff and HeavyCivil books.~~ | `estimating_tools/estimate_spec`, `heavycivil` | M |
| 0.2 | ~~#376 `apply-takeoff` run per structure model overwrites an item shared by two models instead of merging rows for the same `(schedule, item_number)`.~~ **Done #441.** | `estimating_tools/takeoff` | S |
| 0.3 | #314 `culvert_headwall` wingwall stems batter the creek face instead of the earth face; two further defects stop the wingwalls closing on the panel. | `bimforge/author/families/culvert_headwall.py` | M |
| 0.4 | #399 `est-bim contours` returns geometry outside the page's clip path, which renders invisible; honour the active clip during extraction. | `bimforge/bim/plansheet` | S |
| 0.5 | ~~#407 Intermittent IfcOpenShell segfault in `assign_process` on the Python 3.10 CI job.~~ **Done #423** (tests used entities from a freed model); #407 closed. A run of green 3.10 jobs also settles D4. | `bimforge/bim/tests` | S |
| 0.7 | ~~#427 `packages push` prints a false "overrides BidSheet.ai's pin" notice when the spec re-affirms the pin and the same plan revises that quote.~~ **Done #429.** | `estimating_tools/estimate_spec/bm_sync` | S |
| 0.8 | ~~#428 The sidecar's `plugs_removed` goes stale after a `push-assemblies` re-push and carries no component name.~~ **Done #432.** | `estimating_tools/estimate_spec/bm_sync` | S |
| 0.9 | ~~#421 `push --apply` recorded null package ids for packages BidSheet.ai already had.~~ **Done #422.** | `estimating_tools/estimate_spec/bm_sync` | S |
| 0.6 | ~~#304 Structure-modelling families are invisible at intake and briefing; `build-structure` lists 8 of 14.~~ **Done:** the family table and its guard test (f07abed3); `structures.yaml` takes `family` and `route` (`family`, `federated`, `bespoke`), `est-intake briefing` names unrouted structures and families outside the registry, and intake hands off to `build-structure`. A search path for consumer-repo families in `available()` is BIMForge #12; the `bridge-standard` gaps are BIMForge #13. | `plugins/*/skills`, `estimating_tools/intake` | S |

## Phase 1 — The estimate exchange contract

The contract exists in BidManager and is exercised by two packs; this phase makes it the product (D1).
When the phase is done, a third surface that is not a workbook at all should need nothing beyond 1.1
and BidSheet.ai credentials. The in-flight Navigator work (#411, #412) is the first exercise of the
pack interface and continues unchanged. Closes sub-project 4 of BidManager epic #1486 on the way.

Specs: `2026-10-18-estimate-workbook-read-apply-design.md` (BidManager), `2026-10-24-heavycivil-workbook-readback-design.md`,
`2026-10-26-heavycivil-navigator-design.md`, `2026-10-19-bidmanager-selection-sync-design.md`. The contract document and the
pack interface have their specs: `2026-10-29-estimate-exchange-contract-design.md` (1.1) and
`2026-10-29-exchange-packs-binding-engine-design.md` (1.2, 1.3), PR #415, revised 2026-10-31 with the D1 rulings.

| ID | Item | Where | Size |
|---|---|---|---|
| 1.1 | Publish the contract as a versioned document, the way `docs/ifc-takeoff-contract.md` publishes the IFC one: the read model and its fingerprints, every change-set op with its preconditions, dry run and conflict rules, the binding convention (hidden kind / id / `v` cells, block markers, `tpl.*` prototype rows), and what a pack must provide. Compact copy in the skills; exported to the public repo. | `docs/estimate-exchange-contract.md`, `plugins/estimating-core/skills` | M |
| 1.2 | **Step 1 done #425, review fixes #430; follow-ups #424 and #426 done in PR A of the step 2 plan.** The pack interface, as a Python entry point: detect a book, build a book from the read model, read a book into a change set, name its insert templates. Fieldbook and HeavyBook become the two registered packs; the Navigator and the CLIs discover packs through it and never name one. Includes the REST client (`login`, `fetch`, `apply` with `request_id`) that carries the bytes, and the rename of `heavycivil` to `heavybook`. | `estimating_tools/exchange` (new), `heavycivil`, `estimate_spec` | M |
| 1.3 | **Step 3 done (row writer, generic patch, refresh, est-estimate refresh); step 4 (template fill) next.** Plan `2026-11-04-exchange-step2-declaration-reader.md`: step 2a (declaration schema and loader, HeavyBook's generated declaration, the generic stamp, contract tables) in PR A; step 2b (the generic reader on the declaration, the chain formulas, `heavybook/readback` deleted) in PR B. The declarative binding engine: a YAML pack declares sheets, blocks, columns and their kinds and fields, and the engine implements 1.2 from it. Port HeavyBook read-back onto the engine first, since it is the complete case; fieldbook second (1.11). No hooks: the declaration is pure data, and what it cannot say is a schema change. Includes the XML-level patch writer (ids and `v` written back after a push, refresh with collision reporting) so a book is never regenerated. | `estimating_tools/exchange` | XL |
| 1.4 | **Filed in BidManager: #1676, #1680, #1682, #1701, #1704.** Close the contract's holes on the BidManager side, each as a change-set op with a dry run: create and delete items, elements and crews; sections and bid totals; crew assignment; activities pasted in from another book; `request_id` idempotency (#1676, filed); `contract_version` in the payload; `sort_order` on `step.add` and `resource.create`; a move op for steps and resources. Tracked in BidManager; each op lands in 1.1 the day it ships. | BidManager, `docs/estimate-exchange-contract.md` | L |
| 1.5 | Finish the in-flight Navigator PRs as the first exercise of the interface: ~~PR 1 Python (`_templates`, `hc.tpl.*`, `navigator` CLI, reader changes, insert golden)~~ **done #412**; ~~PR 2 pack adapters in the add-in~~ **done #411**; PR 3 the HeavyBook adapter and tree-capable panes. | `estimating_tools/heavycivil`, `excel-addin` | L |
| 1.6 | Navigator adapters read the pack's declaration (1.3) for detection, panes, checks and insert templates, so a user-built pack appears in the add-in without JavaScript. | `excel-addin` | L |
| 1.7 | Quotes and work packages in the same contract: the read model carries work packages, quotes and the carried selection; the change set carries the pick, so the choice can be made on either surface. Replaces the standalone selection-sync design and, for fieldbook, the sidecar sync of #416. BidManager's carried quote (#1556, PR #1635) and allocations following revisions (#1539) both shipped 2026-10-31. | `estimating_tools/exchange`, `quotes`, BidManager | L |
| 1.8 | Contract tests on both sides: golden change sets per pack checked here, and BidManager's contract test dry-running the same goldens against `apply_estimate_workbook_changes` (the former Navigator PR 4). Both repos fail CI when the contract drifts. | `tests/`, BidManager | M |
| 1.9 | #375 Fieldbook measured takeoff gets a Unit selector per line so SF, LF, LBS, TON and EA items total in their pay unit. Reference-pack maintenance. | `estimating_tools/estimate_spec` (format pack) | S |
| 1.10 | Navigator store listing: sample workbook rebuilt by a test, empty state, privacy, support and terms pages, platform declaration. Waits on D5. | `excel-addin`, anvilrockroad.com | M |
| 1.11 | **Spec merged #418.** Fieldbook on the contract: a design spec that gives tasks identity (a stored id and `v` beside fieldbook's self-healing chain tags) and maps fieldbook's shapes (tasks priced as crew-days from typed rates, lines, notes, unbalance, measured takeoff) onto the read model, deciding what stays local. Prerequisite of the engine's last delivery step; retires fieldbook `read-back` and `bm-sync`. #417 (estimator-added cost codes and trades) folds in. | `docs/superpowers/specs`, `estimating_tools/estimate_spec` | L |

## Phase 2 — Onboarding

The destination sentence fails today at the second step. Spec: `2026-10-17-setup-onboarding-design.md` (draft for user review).

| ID | Item | Where | Size |
|---|---|---|---|
| 2.1 | One setup interview: sign-in, org profile, pack choice, imports (cost codes, rates, assemblies, directory, historicals), each recorded as done, skipped or deferred, with `status` reporting deferred steps until they are done. | `estimating_tools/profiles`, new `setup` skill | L |
| 2.2 | Online-only mode: the same record kept server-side for a user with no project folder. | `estimating_tools/profiles` | M |
| 2.3 | First-run guidance in the plugin: when no profile or pack exists, every estimate skill points at setup instead of failing. | `plugins/estimating-core/skills` | S |

## Phase 3 — Model, estimate and quotes, both directions

Costs flow workbook to IFC and BidManager to IFC. Nothing writes a model-derived cost schedule back, and nothing carries the estimate's cost blocks. Two quote-side items that are not contract work sit here too.

| ID | Item | Where | Size |
|---|---|---|---|
| 3.1 | #205 Extract `derive_costs` into a `costload` helper and add the model to BidManager cost-schedule direction as a thin skill over it. | `estimating_tools/schedule/costload` | M |
| 3.2 | #282 Produce a `CanonicalAssemblyLoad` from an estimate spec's `cost_details`, and carry the blocks through `estimate_spec/sync`. | `estimating_tools/assemblies`, `estimate_spec` | M |
| 3.3 | #206 Contract-versus-estimate reconciliation: a deterministic diff tool (matched, in contract only, in estimate only, margin, effective-markup flags) wrapped in a skill that pulls the estimate live. Thresholds are parameters. | `estimating_tools` | M |
| 3.4 | #153 Survey leftovers: rail runs as a takeoff measure along an edge, several structures in one model sharing an alignment, SOV reconciliation, KML bounds, two-datum handling. Split into issues as each is scheduled. | `bimforge`, `estimating_tools/takeoff` | L |
| 3.5 | Follow BidManager's Structure / Element / Assembly reconciliation (#1486). When that spec lands, `model-elements`, takeoff push and the IFC estimate model adapt to the new owner. | `estimating_tools/takeoff`, `bimforge/bim` | M |
| 3.6 | Repricing an estimate from BidManager's as-of rate query (#1018 shipped there; the plugin side was deferred on 2026-08-03). | `estimating_tools/historicals` | M |
| 3.7 | Gmail MCP intake feeding the same `_intake/` quote inventory as the watched folder. | `estimating_tools/quotes/intake` | M |

## Phase 4 — bimforge: families and exact geometry

Waits on D7 for where these are built and D3 for where they are tracked. BIMForge 0.1.96 and 0.1.97 added work no row named: shared alignments and placement, developed elevations, true arcs and inclined cylinders, lifts, a solid-body gate, section DXF and the Blender station and offset sliders. Order within the phase: the bugs and the barrier work that live bids keep re-implementing, then exactness, then navigability.

| ID | Item | Where | Size |
|---|---|---|---|
| 4.1 | #325 `barrier-b11` family (Type 60, 736, 836; constant section swept along a real alignment). The issue cites an R24 branch with 13 commits and no PR; that branch is not on `origin` or in any local checkout surveyed on 2026-10-28, so recover it or rebuild from the 2026-08-20 spec. | `bimforge/author/families` | L |
| 4.2 | #309 Barrier families accept a per-run explicit section ring for modified barriers, keeping end blocks, rebar and validation. Three bids have each replaced the section a different way. | `bimforge/author/families` | M |
| 4.3 | **Largely delivered in BIMForge 0.1.96 (barrier runs on a project line, station and offset); check against #310 after the reconcile.** #310 Barrier runs placed on a georeferenced alignment with a vertical profile (station range, offset, side) instead of a flat local frame. | `bimforge/author` | L |
| 4.4 | #327 `sheet-pile-wall` family with a PZ catalog and per-sheet Z-section prisms, lifted from two bids' hand-built versions. | `bimforge/author/families` | M |
| 4.5 | #341 Exact sweeps for skewed ends: a `SweptSection` meeting a skewed bent is still an `IfcFacetedBrep`, so none of the shipped bridge example's superstructure volume is exact. | `bimforge/bim/emit_ifc` | L |
| 4.6 | #333 `IfcAdvancedBrep` from the build123d solids `emit_step` already builds, for the seven lofted primitives no sweep can express. | `bimforge/bim/emit_ifc` | L |
| 4.7 | #188 IFC spatial organisation: one `IfcBuildingStorey` per structure, so Bonsai's outliner is navigable. The design (2026-09-04) exists only as an untracked draft in a local checkout; commit it first. | `bimforge/bim/emit_ifc` | M |
| 4.8 | #144 Variable-depth (haunched) box girders on the R13 sweep engine. | `bimforge/author` | L |
| 4.9 | #145 Spiral (clothoid) alignment elements. | `bimforge/geometry/alignment` | M |
| 4.10 | #380 Pay-item / cost-code tinting (`style_by: paycode`). Deferred by the styling design; not scheduled. | `bimforge/bim/styling` | S |
| 4.11 | #321 An end-to-end test for the web KMZ degenerate-ring drop. | `bimforge/bim/tests` | S |
| 4.12 | **Done 2026-11-11: BIMForge #48.** The takeoff contract as IDS 1.0: `takeoff.ids` (a classified element has a quantity to measure, quantities are stored as their own dimension, references carry a code) and the advisory `takeoff-coverage.ids`, generated from `ifc_takeoff`'s tables. Any IDS checker can run them on a Revit or Tekla export. IFC4X3 and IFC4 (D9). | `bimforge/bim/takeoff_ids.py`, `bimforge/bim/contract` | M |
| 4.13 | **Draft done 2026-11-11: BIMForge #48.** A family dictionary in bSDD's import format: Type 842 and 732SW barrier runs, B11-51 handrailing and its parts, the D90 guardrail, the linear-reference properties. Local file; nothing is published and nothing reads it yet (D10). | `bimforge/author/dictionary` | S |
| 4.14 | **Done 2026-11-11: BIMForge #48.** bimforge refuses an IFC2X3 model by name (D9); it used to raise an AttributeError mid-read. | `bimforge/bim/ifc_takeoff.py` | S |
| 4.15 | Families read their type names and standard-plan references from the dictionary, and section size becomes a property instead of part of the type name. | `bimforge/author` | M |
| 4.16 | Type the untyped families (retaining wall, box culvert, headwalls, wingwalls, approach slab, bridge) so the dictionary can cover them. | `bimforge/author/families` | M |
| 4.17 | Revit and Tekla: IFC4 export presets and property mappings generated from the dictionary; run `takeoff.ids` on real exports from both. | `bimforge`, in-house templates | L |
| 4.18 | An `est-bim` subcommand that runs the contract, and a `calc-bim` skill step that runs it before `est-bim takeoff`. | `bimforge/bim/cli.py`, `plugins/calc-bim` | S |
| 4.19 | Deferred (D10): register a bSDD organisation code, publish the dictionary, write bSDD URIs on IfcClassification and its references. | `bimforge/author`, `bimforge/bim` | M |

## Phase 5 — Estimating knowledge

The two gated items of the R11 batch and two R12 hygiene notes. Skills and references, no new tools.

| ID | Item | Where | Size |
|---|---|---|---|
| 5.1 | #147 CIDH pile-foundations estimating reference: casing, slurry versus dry hole, overpour, CSL access and its schedule cost. | `plugins/estimating-core/skills/estimating-reference` | M |
| 5.2 | #148 Buy America / Build America compliance checklist, crossing into `subcontract-risk-review`. | `plugins/estimating-core/skills` | S |
| 5.3 | #151 A `.docx` reader that keeps tracked changes and comments, so redline review sees what the other side changed. | `estimating_tools` | M |
| 5.4 | #152 One IES photometric parser instead of two. | `estimating_tools/lighting` | S |

## Phase 6 — Distribution and the public repositories

| ID | Item | Where | Size |
|---|---|---|---|
| 6.1 | #281 `calc-bim` multi-host adapters for Codex and Gemini, generated from the manifest the way the OpenCode port is. | `manifest/`, `opencode/` pattern | M |
| 6.2 | Export cadence: the `estimating-tools` export PR is merged by hand and lags `main` (PR #13 has been open since 2026-10-25 carrying 0.1.95). Merge it on every release, or let the workflow merge when the public CI is green. | `.github/workflows/export-public.yml` | S |
| 6.3 | `BIMForge` export runs by hand (`scripts/export_bimforge.py`) and overwrites; 0.1.96 and 0.1.97 were made there, so an export would have erased them. ~~Retires with D7 (b).~~ **Done #433:** the export script is gone and the plugin takes bimforge from PyPI. | `.github/workflows`, `scripts/export_bimforge.py` | S |
| 6.4 | #322 Rebuild the three estimate-spec fixtures from a published agency bid tab and drop the local-only path. Waits on D6; gates D2. | `estimating_tools/estimate_spec/tests/fixtures` | M |
| 6.5 | Move development to `estimating-tools` once the private layer is a plain package installed on top. Waits on D2. | whole repo | XL |

---

## How this relates to BidManager

The plugin is a client of BidSheet.ai. These BidManager items gate rows above; they are tracked there, not here.

| BidManager | Gates | State on 2026-11-04 |
|---|---|---|
| #1486 epic, sub-project 4 | 1.5 | Open; read-back delivered, Navigator insertion in flight. |
| Missing change-set ops | 1.4 | Filed: #1676 request_id, #1680 contract_version, #1682 move ops, #1704 member ids, #1701 equipment over time, #1699 markup lines and bond inputs. Items, elements, crews, sections, bid totals and crew assignment still need issues. |
| #1556 carried quote (PR #1635), #1539 allocations follow revisions | 1.7 | Both closed; #1635 merged 2026-10-31 with "award" renamed "carry". #1669 (post-bid award) is a future plan only. |
| #1560 REST parity for the write services, #1564 read scaling | 1.1, 1.4 | Open. A non-workbook client over REST needs 1560. |
| Structure / Element / Assembly reconciliation spec (#1486) | 3.5 | Not started. |
| #1409 activity-code templates in estimate building | 1.5 coordination | Open, dormant. |

## Housekeeping (no product change)

- Delete `feat/heavycivil-readback`: its seven doc commits landed on `main` in revised form through #408 and #409.
- Decide whether `archive/pdf-spec-local-draft` stays as an archive branch or its one spec is committed under `docs/superpowers/specs/` and the branch deleted.
- Commit the untracked `docs/superpowers/specs/2026-09-04-ifc-spatial-organization-design.md` that #188 cites (4.7); delete the untracked, superseded `docs/superpowers/plans/2026-08-31-canonical-cost-codes-phase-a.md`.
- Label the unlabelled issues (#144, #145, #147, #148, #151, #152, #153, #282, #304, #309, #310). Every open issue has a phase milestone as of 2026-10-28.
- Resolve the `barrier-b11` branch location named in #325, or close the branch question in the issue.
- The 2026-08-01 BIM integration roadmap is complete; its status line now points here.
- Prune merged local branches and worktrees (`feat/quote-push-and-assemblies`, `fix/421-sidecar-ids-for-existing-packages`, `feat/sub-spreads`, `feat/quote-intake` and the `release/0.1.7x`-`0.1.8x` branches), checking each for unpushed commits first.
- Update the pinned roadmap issue #414's "Where we are" from this file.

## Keeping this canonical

- Specs and plans describe intent. This file records status.
- A PR that finishes a roadmap row strikes it here in the same PR, with the PR number. Rows are never deleted, so the table is also the history.
- New work gets an ID in a phase before it gets a spec, and a place in Order of work.
- The pinned roadmap issue on GitHub links here and names the current phase; it holds no copy of the plan.
