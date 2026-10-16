# Recurring estimating work on OpenWorker

OpenWorker's mechanism for repeating work is the **automation** — a `ScheduledTask`
(`coworker/automation/models.py`): a title, a block of `instructions` handed verbatim
to the agent on every fire, a cron or one-time schedule, a workspace, a persona, and
an optional set of standing tool grants. A scheduler tick runs due tasks; each fire is
a `TaskRun` with its own conversation thread (`__run__<run_id>`) and its own transcript,
and the artifacts it produces are real files in the task's workspace.

There is no separate workflow-definition format. **An automation's "workflow" is a
prompt** — so the reusable logic belongs in a skill, and the automation's instructions
should be short and point at the skill by name. That keeps the workflow versioned in
this repo instead of frozen inside a task record.

## Create them from an Estimator session, not the GUI form

This matters and is easy to get wrong.

| Path | Persona it runs as | Workspace |
|---|---|---|
| `create_scheduled_task` tool, called inside a session | the session's persona (`origin["agent"]`) | the session's workspace |
| `POST /v1/automations` / the GUI "New automation" form | **always `cowork`** (hardcoded) | a fresh per-task scratch folder |

Source: `coworker/automation/tools.py::scheduling_tools` binds `agent=origin.get("agent")`,
while `coworker/server/manager.py::create_automation` passes `agent="cowork"`.

So to get an automation that runs **as the Estimator, in your bid folder**, open an
Estimator session in that folder and ask for it in chat. The `create_scheduled_task`
call is approval-gated, so you will see a consent card before anything is created.

Note that automations are only offered to `family: knowledge` personas with a workspace
(`coworker/agent.py`), which the Estimator persona is.

## Recipes

Paste any of these into an Estimator session rooted in the relevant bid folder.

### Bid-day quote sweep

> Every 20 minutes between 8am and 11am on weekdays, start with the quote-space board:
> load the `quote-coverage` skill, run it, write the board to `quotes/coverage.md`, and
> lead your summary with any zero-coverage gap items. Then re-level the vendor quotes:
> load the `compare-quotes` skill, run it for each work package with quotes, and write
> each spread to `quotes/spread-<package>.md`, passing the leveled package names back
> into the coverage run's `--leveled` list. If a package's low vendor changed since the
> previous run, say so at the top of your summary. Don't award anything.

Cron: `*/20 8-10 * * 1-5`. Read-only against BidSheet.ai, so no standing write grants —
which is what you want on bid day.

### Morning estimate rollup

> Every weekday at 6:30am, load the `price-estimate` skill's reference section, pull the
> current estimate summary for this project, and write `reports/rollup-<date>.md` with
> the total, the delta from yesterday's rollup, and every item still unpriced.

Cron: `30 6 * * 1-5`.

### Weekly rate-library drift check

> Every Monday at 7am, load `estimating-reference`, list the org's labor and equipment
> rates, and compare them to `rates/baseline.json`. Write `reports/rate-drift-<date>.md`
> listing anything that moved more than 3%, and leave the baseline file alone.

Cron: `0 7 * * 1`.

### Post-award conformance watch

> Every day at 5pm, check the project's plans and specs against their addenda using the
> conformed MCP, and write `conformance/<date>.md` with anything newly non-conforming.
> If nothing changed, write a one-line file saying so.

Cron: `0 17 * * *`.

## Standing grants

If an automation should message someone without asking every run, propose the grant when
you create it — `permissions: [{tool: "send_message", target: "slack:T…/C…", access: "write"}]`.
Only **target-bound write** grants survive validation (`automation/models.py::grant_entries`);
bare tool names, wildcards, and exec tools are dropped fail-closed. Grants live on the task
record, so deleting the automation revokes them.

Unattended runs park anything they can't do on their own in the **Inbox** rather than acting
(`coworker/unattended.py`) — an automation that hits an unapproved BidSheet.ai write will wait
there for you, not guess.

## REST payloads

`payloads/` holds the same recipes as `POST /v1/automations` bodies, for scripted setup.
They carry the `agent="cowork"` + scratch-workspace caveat above, so prefer the chat path
unless you are provisioning a machine non-interactively.
