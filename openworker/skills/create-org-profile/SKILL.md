---
name: create-org-profile
description: Stand up a new organization's profile — interview for the org's letterhead, folder conventions, argot, and naming, then scaffold a schema-valid profile directory (profile.yaml + tree.yaml + letterhead.md) the customer adds to ESTIMATING_PROFILES. Local files; the profile cascades into every consumer (scaffold-project, docgen).
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Create an Org Profile

Use this to onboard a new organization's profile — the small bundle of org-specific
conventions the plugin reads (letterhead, folder conventions, argot, naming). You interview
the org, scaffold a profile directory, and the customer adds it to `ESTIMATING_PROFILES`.
This is **local file scaffolding** — no BidSheet.ai / MCP.

## Inputs
- A target directory to create the profile in.
- The org's details (gathered in the interview below).

## Workflow
1. **Interview** the org for the core fields:
   - `name` — the organization name (required).
   - `company_name`, `address` — for the letterhead; an optional `logo` filename the org
     will drop into the directory.
   - `folder_conventions` — propose a sensible default project folder tree (a YAML list,
     e.g. `Bid Data`, `Correspondence` → `Owner`/`Subcontractors`, `Estimates`,
     `Plans and Specs`, `Quotes`, `Submittals`) and let the user edit it.
   - `letterhead` — a starter letterhead template (markdown) the org edits.
   - `argot` — `compliance_label` (e.g. "DBE Goal") and `spec_note` (e.g. the std-specs
     reference); optional `naming` conventions.
   - `house_rules` — the org's standing estimating judgment calls, each a
     `{name, rule, exceptions}` entry. Ask: "when a vendor's quote math doesn't add up,
     or a takeoff disagrees with the bid schedule, what's your standing call?" Seed the
     conversation with these two examples (two rules from a real contractor):
     - **Unit price governs** — a vendor's printed unit price holds; recompute the
       extension as qty × unit; never back-solve a unit price from a stated extension.
       *Exception:* when the vendor's unit column is display-rounded and their
       extensions reconcile to their own stated total, the extensions govern. The
       test: does the vendor's total reconcile to the extensions, or to qty × printed
       unit? (E.g. a vendor quotes 84 SQYD × $160 against a 51 SQYD bid item → carry
       $160 × 51 = $8,160; a vendor states "54,500 Lbs @ $2.25 = $121,535" — a
       mis-extension → carry $2.25 × 54,500 = $122,625.)
     - **Cost-vs-pay quantity** — when the measured (cost) quantity differs from the
       bid-schedule (pay) quantity, bid unit price = total cost ÷ pay quantity (the
       schedule quantity is never edited).
   - `estimating_format` — the org's **estimate workbook format pack**: the directory
     holding its `format.yaml` (relative paths resolve against this profile directory,
     so `format/` for a pack kept alongside the profile). This becomes the profile's
     `estimating.format`, which every `est-estimate` verb resolves the pack from.

     Ask for it, and say what is lost without it: with no pack named, `est-estimate`
     falls to the **bundled fieldbook pack** — a complete, generic format (costs by type,
     cost codes, live checks, an Excel round trip) but not the org's own: generic trade
     names and cost codes, and no `supports:` (so `summarize` and the inline item editor
     refuse it) — and `scaffold`, which writes a file, refuses a pack nothing named. An org
     that is happy with fieldbook names it here anyway (`<estimate_spec>/packs/fieldbook`),
     or better, a copy of it with the org's own trades in `vocabulary.yaml` and its
     rate-table trades and cost-code list in `seed.yaml` — every scaffold then starts from
     the org's codes. A format pack is data: `format.yaml`
     plus `units.yaml`, `tokens.yaml`, `recipes.yaml`, `vocabulary.yaml` and `seed.yaml`.
     If the org has no pack yet, leave the field blank, say the estimate workbook is not
     wired up, and point them at `build-estimate-workbook`'s `## Inputs` section and
     `packs/README.md` (shipped beside the fieldbook pack) for what a pack must contain.
2. **Confirm** the proposed values — especially the folder tree and the letterhead.
3. **Scaffold** the directory:
   `estimating_tools.profiles.build_profile_dir(ProfileInputs(name=…, company_name=…,
   address=…, logo=…, tree=…, letterhead=…, compliance_label=…, spec_note=…, naming=…,
   house_rules=[{"name": …, "rule": …, "exceptions": …}, …], estimating_format=…))`
   returns a `{filename: content}` map (`profile.yaml` + `tree.yaml` + `letterhead.md`);
   write each file into the target directory. (For a headless run, the `profile-init
   <dir> --name … --fields fields.json` CLI does the same.) If a logo was named, remind the
   user to place that image file in the directory. If `build_profile_dir` raises (a blank name, a
   schema violation), surface the message and fix the input.
4. **Activate** — tell the user to add the directory to `ESTIMATING_PROFILES` (an
   `os.pathsep` cascade) and verify: `est-scaffold "<Project>"` now builds the org's folder
   tree, and the letterhead/argot are available to docgen. Org-level profile first, then any
   agency overlay later.

   If `estimating.format` was set, verify the pack too: `est-estimate build <a spec> -o
   <out.xlsx>` must render through it, and the workbook's `estimate_format` custom document
   property must read `<pack name> <version>`. A pack the profile names but that is missing
   or invalid is an **error**, never a silent fall back to the bundled one — so a failure
   here means the path is wrong, not that the pack was ignored.

## Rendered letterhead (`letterhead.template`)

Setting `letterhead.template` to a `.docx` file in the profile directory
enables rendered letterhead documents: `est-letterhead <draft.md>` (and the
`draft-an-rfi` skill's step 7) render markdown drafts onto that template,
merging the profile's other letterhead fields (`company_name`, `address`,
...) under each draft's own frontmatter. **The org supplies the `.docx`
template** — authoring it (styles, logo placement, `{{ }}` placeholders and
the run-level `{{r body }}` slot) stays with the org; this skill only wires
the profile field to the file. Without it, markdown drafts remain the
deliverable (agnostic fallback).

## Notes
- The profile is **local files**, not BidSheet.ai data — IT provisions `ESTIMATING_PROFILES`
  per the enterprise model. This skill makes no MCP calls.
- `tree.yaml` is the folder convention `est-scaffold` reads (a YAML list; nest with `Name:`
  + indented children). `letterhead.md` is the template docgen renders. The `logo` is
  referenced only if the org provides a file — never invented.
- This cycle scaffolds the core sections (name, letterhead, folder_conventions, argot,
  naming, house_rules). The `terminology`/`standard_details` sections and agency-kind
  profiles can be added by editing `profile.yaml` later (they're in the schema).
- `house_rules` are consulted by the quote skills (`capture-quote`, `compare-quotes`):
  when a rule adjusts quote math, the skill surfaces which rule was applied — so word
  each rule (and its exceptions) the way the org would defend it on bid day.
- The build is deterministic and schema-validated (`estimating_tools.profiles`); the
  judgment is the interview and confirming the tree/letterhead.
