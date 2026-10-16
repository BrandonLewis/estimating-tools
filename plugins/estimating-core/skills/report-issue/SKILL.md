---
name: report-issue
description: Report a bug or request a feature for the estimating plugin (or BidSheet.ai) from inside the session — gather the report, auto-capture context (plugin version, failing command, error excerpt), show the exact payload for consent, then file it as a BidSheet.ai FeedbackReport via the MCP. Also answers "what happened to my report?" by reading status back. Writes to BidSheet.ai only after explicit approval; nothing leaves the machine unseen.
---

# Report an Issue / Request a Feature

Use this when the user hits a bug, wants a feature, or asks what became of
an earlier report. Reports land in BidSheet.ai as FeedbackReport records; the
maintainer triages them from there (the user never needs GitHub).

## Filing a report

1. **Kind and product.** Bug or feature request? About the estimating
   plugin (default) or BidSheet.ai itself (`product: "bidmanager"`)?
2. **Interview — keep it short.**
   - Title: one line, the user's words.
   - Body: what happened / what they want. For bugs: what they ran or which
     skill was in play, expected vs. actual.
3. **Auto-capture context** (build a `context` JSON object):
   - `plugin_version`: the `version` field of the plugin's
     `.claude-plugin/plugin.json` (this skill's directory's grandparent).
   - `os`: platform (e.g. "Windows 11", "macOS 15").
   - `cli_command` / `skill`: the failing command line or skill name, when
     the report is about one.
   - `error_excerpt`: the relevant error output, TRIMMED to the meaningful
     lines and SCRUBBED — remove user paths (`C:\Users\<name>\...`, home
     dirs), tokens, and anything project-confidential. When in doubt, leave
     it out; the body can describe the error instead.
4. **Consent — blocking.** Show the COMPLETE payload (title, body, kind,
   product, the full context object) exactly as it will be sent. Say
   plainly: "this will be sent to BidSheet.ai." Let the user edit or remove
   any field. Do not send until they approve.
5. **File it:** `create_feedback_report(product=<...>, kind=<...>,
   title=<...>, body=<...>, context=<...>)`. Confirm with the returned id:
   "filed — reference #<id>; ask me 'what happened to my report?' anytime."

### If the tool is unavailable

If `create_feedback_report` is not on the MCP surface (server not yet
upgraded with FeedbackReport support) or BidSheet.ai is not connected: save
the approved payload locally as `feedback-draft-<YYYY-MM-DD>.json` (in the
bid working dir if the project is intaken, else the current directory),
tell the user nothing was sent and why, and that re-running this skill
once the server supports it (or the connection returns) will pick the
draft up. On every run, check for such drafts first and offer to send them.

## Checking on a report

"What happened to my report?" → `list_feedback_reports(mine=true)` (filter
by `product`/`status` if asked) and show a short table: id, kind, title,
status, resolution_note. Translate statuses for the user: `new` = received,
`acknowledged` = maintainer has seen it and it's tracked, `planned` = on
the roadmap, `fixed` = done (resolution_note says which release),
`declined` = won't be done (resolution_note says why).

## Notes

- Never send anything the user has not seen in full. Consent is per-report,
  not per-session.
- One report per problem — if the user has three complaints, that's three
  records (each gets its own lifecycle).
- This skill never touches GitHub and never needs to.
