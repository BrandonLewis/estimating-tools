---
name: report-issue
description: Report a bug or request a feature for the estimating plugin (or BidSheet.ai) from inside the session — gather the report, auto-capture context (plugin version, failing command, error excerpt), build the payload with est-feedback so it is Markdown-only and scrubbed of paths and secrets, show it for consent, then file it as a BidSheet.ai FeedbackReport via the MCP. Also answers "what happened to my report?" by reading status back. Writes to BidSheet.ai only after explicit approval; nothing leaves the machine unseen.
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

# Report an Issue / Request a Feature

Use this when the user hits a bug, wants a feature, or asks what became of
an earlier report. Reports land in BidSheet.ai as FeedbackReport records; the
maintainer triages them from there (the user never needs GitHub). The user
can also follow their reports in BidSheet.ai under their account menu, **My
Feedback**.

## Filing a report

1. **Kind and product.** Bug or feature request? About the estimating
   plugin (default) or BidSheet.ai itself (`--product bidmanager`)?
2. **Interview — keep it short.**
   - Title: one line, the user's words.
   - Body: what happened / what they want, in plain Markdown. For bugs: what
     they ran or which skill was in play, expected vs. actual. Write the body
     to a scratch file (`feedback-body.md`) when it is more than a sentence.
3. **Build the payload with `est-feedback` — never by hand.** The tool is what
   makes the payload safe to send: every field becomes Markdown-only
   (raw HTML, control and invisible characters stripped; title ≤ 255 chars,
   body ≤ 20,000), and home-directory paths, email addresses and token
   shapes are replaced with placeholders in the body and in every context
   string. Capture context through its flags rather than typing it:
   - `--plugin-version`: the `version` field of the plugin's
     `.claude-plugin/plugin.json` (this skill's directory's grandparent).
   - `--os`: platform (e.g. "Windows 11", "macOS 15").
   - `--cli-command` / `--skill`: the failing command line or skill name,
     when the report is about one.
   - `--error-file`: the raw error output saved to a file. The tool keeps
     the last 40 lines and scrubs them; do not paste the error into
     `--body`.
   - `--context key=value` for anything else small.

   ```bash
   ~/.estimating/bin/est-feedback build --product estimating-plugin --kind bug \
     --title "push-takeoff duplicates assemblies on re-push" \
     --body-file feedback-body.md \
     --plugin-version 0.1.88 --os "macOS 15" --skill push-takeoff \
     --error-file push-error.txt \
     --out feedback-draft-$(date +%F-%H%M%S).json
   ```

   A non-zero exit names the field that cannot be made valid (too long,
   empty, unknown product/kind, non-finite context number); fix the input and
   rebuild. `--out` never overwrites an existing file: choose a new filename
   for each report and each rebuild so queued reports stay intact. Do not edit the
   JSON by hand: `~/.estimating/bin/est-feedback check <file>` must print
   `OK` before anything is sent, and it fails a payload that rebuilding would
   change.
4. **Consent — blocking.** Show the COMPLETE payload file (title, body, kind,
   product, the full context object) exactly as built. Say plainly: "this
   will be sent to BidSheet.ai." If the user wants a field changed, change
   the input and rebuild — the file that is sent is always one the tool
   wrote. If something confidential survived scrubbing, remove it from the
   input; when in doubt, leave the error excerpt out and describe it in the
   body instead. Do not send until they approve.
5. **File it** with the payload's fields verbatim:
   `create_feedback_report(product=<...>, kind=<...>, title=<...>,
   body=<...>, context=<...>)`. The server applies the same Markdown rules,
   so a built payload is stored unchanged. Confirm with the returned id:
   "filed — reference #<id>; ask me 'what happened to my report?' anytime, or
   open My Feedback in BidSheet.ai." Then delete the draft file.

### If the tool is unavailable

If `create_feedback_report` is not on the MCP surface (server not yet
upgraded with FeedbackReport support) or BidSheet.ai is not connected: keep
the approved payload where `--out` put it, `feedback-draft-<YYYY-MM-DD-HHMMSS>.json`
(in the bid working dir if the project is intaken, else the current
directory), tell the user nothing was sent and why, and that re-running this
skill once the server supports it (or the connection returns) will pick the
draft up. On every run, `~/.estimating/bin/est-feedback drafts` lists the
drafts in the current directory with each one's check result; offer to send
the ready ones (after showing them again) and rebuild any that need it.

## Checking on a report

"What happened to my report?" → `list_feedback_reports(mine=true)` (filter
by `product`/`status` if asked) and show a short table: id, kind, title,
status, resolution_note. Translate statuses for the user: `new` = received,
`acknowledged` = maintainer has seen it and it's tracked, `planned` = on
the roadmap, `fixed` = done (resolution_note says which release),
`declined` = won't be done (resolution_note says why). The same list, with
the maintainer's notes rendered, is at **My Feedback** in BidSheet.ai; the
maintainer also receives a daily digest of new and changed reports.

## Notes

- Never send anything the user has not seen in full. Consent is per-report,
  not per-session.
- Never send a payload `est-feedback` did not build. The Markdown-only and
  scrubbing rules live in the tool, not in this text.
- One report per problem — if the user has three complaints, that's three
  records (each gets its own lifecycle).
- This skill never touches GitHub and never needs to.
