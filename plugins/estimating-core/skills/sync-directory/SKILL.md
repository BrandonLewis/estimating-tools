---
name: sync-directory
description: Two-way vendor/contacts sync between a local canonical directory and BidSheet.ai — export BM, diff with dir-sync into a reviewable plan (creates / updates / pulls / ambiguous, never deletes), apply the creates, updates, and pulls directly (updates are un-gated since BidManager#1021), and report. Via the BidSheet.ai MCP. Writes.
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

# Sync the Vendor Directory with BidSheet.ai

Use this when the org's local directory (a `dir-import` canonical JSON) and
BidSheet.ai have drifted. The plan is reviewed BEFORE anything is applied.

## Workflow
1. **Export BM.** `list_organizations` (all orgs) and `list_people` /
   org contacts → write a CanonicalDirectory-shaped JSON
   (`{"organizations": [{..., "contacts": [...]}]}`) as `remote.json`.
   Map BM fields onto the canonical field names used by dir-import.
2. **Plan:** `~/.estimating/bin/dir-sync plan local.json remote.json` → present the markdown
   plan verbatim. `--json` for the machine-readable plan you execute from.
3. **Review gate.** The user approves the plan (or strikes items) before ANY
   write. Ambiguous entries (same email, different org) are never applied —
   list them for hand resolution.
4. **Apply creates** (open to all users): `create_organization` per
   org-create, `create_person` + `add_person_to_organization` per
   person-create (role only if in the valid set — see import-directory).
   For an org-create entry, after `create_organization` also
   `create_person` + `add_person_to_organization` for EACH contact in its
   `data.contacts` — nested contacts are part of the create.
   A person appearing under two local orgs relies on BM's
   find-or-create-by-email: no duplicate person is created.
5. **Apply updates.** For each org/person update entry in the
   approved plan, call `update_organization(organization_id, <changed fields>)`
   / `update_person(person_id, <changed fields>)`. Since BidManager#1021 these
   are open to any member with edit access in the owning org — no staff gate —
   so they apply directly; there is no "skipped" bucket to report anymore. If a
   call still returns a permission error, surface it verbatim (it means the
   account lacks edit access to that org), but do not treat it as the expected
   path.
6. **Provenance (informational).** BidSheet.ai stamps an organization's `source`
   field automatically based on how the row was created (BidManager#1021/#1034)
   — it is NOT a parameter of `create_organization`/`update_organization`, so
   you do not set it. `get_organization` returns it; use it only to tell
   import-authored rows from hand-entered ones when reviewing.
7. **Apply pulls locally.** Add pull_org/pull_person entries into the local
   canonical JSON (append to `organizations` / the org's `contacts`) and
   save. Never delete local entries.
8. **Report:** applied creates, applied updates, pulls applied locally,
   ambiguous left for review.

## Notes
- No deletes in either direction, ever.
- Idempotent: re-running after a partial apply plans only the remainder.
