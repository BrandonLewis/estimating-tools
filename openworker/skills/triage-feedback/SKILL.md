---
name: triage-feedback
description: Maintainer-side triage of user FeedbackReport records — list new reports from BidSheet.ai via the MCP, dedupe, create GitHub issues in the plugin repo (label from-field), write back external_ref + status so reporters see progress, and on releases sync closed issues to status=fixed. Writes to BidSheet.ai and GitHub; for the plugin maintainer, not end users.
---

# Triage User Feedback into GitHub Issues

Maintainer workflow: user reports arrive as BidSheet.ai FeedbackReport
records (filed by the `report-issue` skill); development is tracked in the
plugin repo's GitHub issues. This skill is the bridge — run it periodically
and after releases. GitHub credentials stay on the maintainer's machine;
BidSheet.ai only ever sees an opaque `external_ref`.

## Triage pass

1. **Pull the queue:** `mcp__bidmanager__list_feedback_reports(status="new")`. Present a
   board: id, product, kind, title, reporter/org, created date.
2. **Route by product.** `product="bidmanager"` records are not this repo's
   — offer to file them in the BidSheet.ai repo instead (same steps, that
   repo), or leave for the BM team; either way update the record so it
   leaves the `new` queue.
3. **Dedupe before filing.** For each record:
   - Same underlying problem as another record in the queue → file ONE
     issue, write the same `external_ref` to every duplicate record.
   - Already tracked → search existing issues (`gh issue list --state all
     --search "<keywords>"` — `--state all` matters: the default searches
     open only and would miss closed duplicates) and reuse that issue
     number.
   - **A record whose `external_ref` is already set is never re-filed** —
     that is the idempotency rule; skip it (it belongs to a prior pass).
4. **File accepted reports:** one GitHub issue per distinct problem, in
   this repo, label `from-field` (create the label once if absent):
   title = the record's title (edited for clarity as needed); body = the
   user's body quoted, then the `context` JSON in a code block, then a
   `BM-FEEDBACK-ID: <id>` line (machine-findable back-reference; list every
   duplicate record's id when several fold into one issue).
5. **Write back — this is what the reporter sees:**
   `mcp__bidmanager__update_feedback_report(id, status="acknowledged",
   external_ref="GH#<n>")` for each record covered by the issue.
6. **Declines:** for reports that won't be pursued,
   `mcp__bidmanager__update_feedback_report(id, status="declined", resolution_note=<one
   honest sentence why>)` — a reasoned no beats a silent queue.
7. When a triaged issue is scheduled into planned work, upgrade the
   record: `status="planned"`.

## Release sync (run after tagging a release)

1. `mcp__bidmanager__list_feedback_reports(status="acknowledged")` and `status="planned"` —
   collect records with an `external_ref`.
2. For each, check the linked issue: `gh issue view <n> --json
   state,stateReason`.
   - Closed as completed → `mcp__bidmanager__update_feedback_report(id, status="fixed",
     resolution_note="fixed in <release version>")`.
   - Closed as not-planned → `status="declined"` with a reason.
   - Still open → leave it.
3. Report the sync: how many records moved, any external_refs whose issue
   no longer exists (fix by hand).

## Notes

- Never delete FeedbackReport records; the status lifecycle is the record.
- The `from-field` label is what separates user-reported issues from
  maintainer-filed ones in the tracker.
- If `mcp__bidmanager__list_feedback_reports` is not on the MCP surface, the server predates
  FeedbackReport support (BidManager#1116) — there is nothing to triage
  this way yet.
