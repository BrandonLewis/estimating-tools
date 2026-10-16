---
name: scaffold-project
description: Create a new project's folder structure from the active org profile's folder conventions — one command, agnostic when no profile is set.
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Scaffold a Project

Use this when asked to set up a new project's folder structure.

## Workflow
1. Confirm the project name.
2. Create the tree:
   ```bash
   est-scaffold "<Project-Name>" --parent <dir>
   ```
   The folders come from the active profile's `folder_conventions.tree` (the org
   profile on `ESTIMATING_PROFILES`). With no profile set, it just creates the
   project directory — no error.
3. Confirm the expected folders were created.

## Stale-scaffold guard — fresh scaffolds must be empty of prior-project content

Five confirmed instances in the archive of record: scaffolded takeoff /
bid-item workbooks carried a PREVIOUS bid's content (another job's
structures, quantities, even its bid number in the filename) into a new
project, uncleared — a silent wrong-number risk, since stale prior-job
rows in a takeoff read exactly like real ones. `est-scaffold` itself only
creates empty folders, but template-seeding steps (e.g. the Work repo's
`work project new` / `work bid new` xlsx templates during intake) are
where this bites. After any scaffold-plus-seed:

- open each seeded workbook/template and assert it carries no
  prior-project content (names, structures, quantities, bid items);
- if it does, clear it NOW — or, if it must wait, mark it loudly
  ("UNCLEARED TEMPLATE — do not price from this") in the file and the
  project README before doing anything else.

## Notes
- Folder conventions are org-specific data supplied by a profile, not hardcoded
  here. See the profile system design for how a profile is delivered.
- Deterministic; the only judgment is the project name and parent location.
