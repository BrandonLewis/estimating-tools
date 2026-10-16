# The estimating platform on OpenWorker

This directory is the [OpenWorker](https://github.com/andrewyng/openworker) build of this
repo. It carries the same skills, the same MCP servers, and the same workflows as the
Claude Code plugin under `plugins/`, reshaped for OpenWorker's extension surfaces.

Everything here is generated from or consistent with the plugin sources —
`port_skills.py` regenerates `skills/`, and `tests/test_openworker_port.py` fails if the
two drift apart.

---

## Part 1 — How OpenWorker's extensibility actually works

Verified against `andrewyng/openworker` @ `db93d75`. There is **no plugin bundle format**
and no `plugin.json` equivalent. Instead there are three independent extension surfaces,
plus one mechanism for recurring work.

### 1. Skills — Anthropic `SKILL.md`, loaded from the filesystem

`coworker/skills/base.py`, wired in `coworker/agent.py::build_engine`.

A skill is a folder containing `SKILL.md`: YAML-ish frontmatter (`name`, `description`,
optional `allowed-tools`) plus a markdown body. Discovery scans two directories
(`coworker/agent.py::_skill_dirs`):

```
<state-dir>/skills/<name>/SKILL.md            # global
<workspace>/.coworker/skills/<name>/SKILL.md  # per-workspace
```

`<state-dir>` is `$COWORKER_STATE_DIR`, else `%APPDATA%\coworker` on Windows, else
`~/.config/coworker` (`coworker/secrets.py::state_dir`).

It works by **progressive disclosure**: at session start only the catalog (one
`- name: description` line per skill) is appended to the system prompt, and a `load_skill`
tool is registered. When a skill is relevant the model calls `load_skill(name)` and gets
back `{name, instructions, resources_path}` — the full body plus the on-disk path to the
skill's own folder, which is how a skill ships scripts and data alongside its prose.

Four things are worth knowing before you write one:

- **The frontmatter parser is not YAML.** `_parse_skill` splits each line on the first
  `:` and ignores lines without one. A folded or multi-line `description:` silently loses
  everything after its first line, and any nested block whose keys happen to be `name` or
  `description` will overwrite the real ones. Keep frontmatter to flat, single-line values.
- **`allowed-tools` is parsed but never enforced.** Nothing in the codebase reads
  `Skill.allowed_tools`. It is documentation, not a sandbox.
- **Skills are global to every persona.** `build_engine` constructs one `SkillLoader` from
  the two directories regardless of which persona the session was born from. A persona's
  `skills:` list does not filter the catalog (see below).
- **Names are the primary key.** `SkillLoader` stores skills in one flat `dict` keyed by
  frontmatter `name`, so two skills sharing a name silently collide, last one wins.

There is no UI for installing skills — the only read path is `GET /v1/skills`, which
lists the global directory. Installing means copying folders.

### 2. Personas — installable markdown manifests

`coworker/personas/{manifest,registry,loading}.py`, REST at `POST /v1/personas/install`.

A persona is the closest thing OpenWorker has to a "plugin": a single markdown file whose
YAML frontmatter declares identity and capabilities and whose body **is the system prompt**.
It is what appears in the new-session picker.

Install accepts three sources (`coworker/server/app.py`):

| Body | Behavior |
|---|---|
| `{"dir": "/path"}` | globs `*.md` in that directory, validates, snapshots each |
| `{"git_url": "..."}` | shallow-clones, then runs the `dir` path against the **clone root** |
| `{"gallery_slug": "..."}` | fetches the manifest from OpenWorker Cloud, verifies its sha256, then the same parser |

All three converge on `install_from_dir`, which **snapshots** each manifest into
`<state-dir>/personas-installed/<id>/manifest.md` so the definition is stable, and lands
it **disabled + unsurfaced pending consent**. The caller shows the returned consent
summary (tools, risk classes, connectors, MCP, messaging, recommended mode) and only then
`POST /v1/personas/{id} {"enabled": true, "surfaced": true}`.

The trust model is the point: **a persona ships no executable code.** It can only
reference capabilities that are already vetted.

That vetting is `coworker/catalog.py`, and it is explicitly **closed**:

```python
CATALOG = {"code_files", "files", "git", "search", "shell", "todo"}
```

A persona's `tools:` list may contain nothing else — `_validate_tools` raises
`ManifestError` and the install fails. The module comment states the intent plainly:
third parties get breadth "from us adding vetted capabilities here and from MCP, never
by adding entries." **There is no way to contribute a Python tool to OpenWorker from
outside the repo.** MCP is the only escape hatch.

Other frontmatter: `family` (`code` | `knowledge` — this drives a lot, see below),
`messaging`, `connectors`, `default_permission_mode`, `recommended_models`, and
`recommends:` (a list of `connector:`/`mcp:` refs with a reason and a `core`/`optional`
tier, surfaced in the session connections drawer).

Two fields are **parsed and shown at consent but never enforced at runtime**: `skills:`
and `mcp:`. Nothing reads `PersonaManifest.skills`; `mcp` appears only in the consent
summary. Treat both as declarations of intent.

`family` is load-bearing in `build_engine`:

| | `knowledge` | `code` |
|---|---|---|
| workspace | `deliverable` | `git` |
| scheduling tools (automations) | yes | no |
| self-wake tools | yes | no |
| `request_directory` | yes | no |
| explorer subagents | no | yes |

So a persona that needs to create its own recurring work must be `family: knowledge`.

### 3. MCP servers — the real extension point for tools

`coworker/mcp/{config,client,tools,oauth}.py`, REST at `/v1/mcp`.

Standard `mcpServers` JSON, paste-compatible with Claude Desktop / Cursor / Codex, layered
global (`<state-dir>/mcp.json`) then per-workspace (`<workspace>/.coworker/mcp.json`, which
wins on a name clash). Supports stdio and HTTP, `${VAR}` interpolation resolved through the
`SecretStore`, `include_tools` / `exclude_tools` filtering, a per-server `requires_approval`
flag that feeds the permission engine, and `auth: "oauth"` for browser OAuth 2.1 + PKCE with
Dynamic Client Registration (tokens go to the secret store, never the config file).

The critical detail for porting: **OpenWorker namespaces every MCP tool** as
`mcp__<server>__<tool>`, sanitized to `[A-Za-z0-9_-]{1,64}` (`coworker/mcp/tools.py::tool_name`).
The prefix comes from the **config key**, not from anything the server reports. A skill that
says `list_bid_items` refers to a tool that does not exist.

Also: OpenWorker's MCP client only implements `list_tools` and `call_tool`
(`coworker/mcp/client.py`). **No resources, no prompts, no MCP Apps** — which matters here,
see the artifact-editor note below.

### 4. Repeating workflows — automations

`coworker/automation/`, REST at `/v1/automations`.

A `ScheduledTask` holds a title, `instructions` handed **verbatim** to the agent every run,
a cron or one-time schedule, a workspace, a persona, and standing tool grants. The scheduler
fires due tasks; each fire is a `TaskRun` with its own conversation thread and transcript,
writing real files into the task's workspace.

There is no declarative workflow language — an automation's workflow *is* a prompt. The
reusable logic belongs in a skill; the automation should be a short prompt that names it.

The two creation paths are **not** equivalent, and this is easy to get wrong:

| Path | Runs as | Workspace |
|---|---|---|
| `create_scheduled_task` tool, from inside a session | that session's persona | that session's workspace |
| `POST /v1/automations` / GUI form | **always `cowork`** (hardcoded) | fresh scratch folder |

Standing grants are validated fail-closed (`automation/models.py::grant_entries`): only
`access: "write"` items whose tool declares a target argument and whose target is non-empty
become rules, which structurally excludes exec and destructive tools. Grants live on the task
record, so deleting the automation revokes them. Unattended runs park anything they cannot do
on their own in the **Inbox** rather than acting (`coworker/unattended.py`).

Related: `selfwake.py` lets a knowledge persona suspend itself and schedule its own
resumption (timer / on-completion / on-event), and `subscriptions.py` lets it listen to a
Slack channel.

### 5. Two smaller surfaces

- **`AGENTS.md`** in a workspace root is appended to the system prompt (`coworker/project.py`).
- **`config.toml`**, layered global then per-workspace, sets model, permission mode,
  `max_iterations`, `allowed_commands`, and `auto_allow`. Workspace command allowances only
  apply after the user trusts that exact path (`coworker/workspace_trust.py`).

### What does *not* exist

No hooks (nothing like `SessionStart`), no slash commands, no user-defined subagents (the
explorer subagent is built in and code-family only), no plugin marketplace format, no way to
register a Python tool, and no `${CLAUDE_PLUGIN_ROOT}`.

---

## Part 2 — What this directory contains

```
openworker/
  skills/              30 ported SKILL.md folders + _dist/ (the estimating_tools wheel)
  personas/            estimator.md
  mcp/mcpServers.json  bidmanager + conformed, merged into <state-dir>/mcp.json
  automations/         recipes.md (chat prompts) + payloads/ (REST bodies)
  install.py           does all of the above
  port_skills.py       regenerates skills/ from plugins/*/skills/
  tests/               contract tests against OpenWorker's parsing rules
```

### Install

```bash
# Local files only: skills + MCP config + pip install the bundled wheel.
python openworker/install.py

# Also install the Estimator persona (needs the server running).
python openworker/install.py --server http://127.0.0.1:8765

# Per-project instead of global.
python openworker/install.py --workspace ~/bids/hwy-41
```

Then restart the server (skills and `mcp.json` are read at engine build), connect
`bidmanager` under Settings > Connectors > MCP to run its OAuth sign-in, and start a session
with the Estimator persona.

`install.py --dry-run` reports what would change. The MCP merge is non-destructive: an
existing server under the same key is left alone, so a re-run never resets a staging URL or
a completed OAuth handshake.

**Do not install these personas with `git_url`.** That path clones the repo and runs
`install_from_dir` against the **clone root**, which globs `*.md` — and the first file it
hits, `README.md`, is not a manifest, so `ManifestError` fails the entire install. Verified
directly against upstream. Use `--server` (which posts `{"dir": ".../openworker/personas"}`)
or pass that directory yourself.

### What the port changes, and why

`port_skills.py` applies four transforms; run it after editing anything under
`plugins/*/skills/`.

1. **Setup line.** The plugin's `${CLAUDE_PLUGIN_ROOT}/dist/*.whl` has no meaning here, and
   OpenWorker has no `SessionStart` hook to pre-install the wheel. `install.py` pip-installs
   it up front; the rewritten fallback points at `<resources_path>/../_dist/`, reachable from
   the `resources_path` that `load_skill` returns.
2. **MCP tool namespacing.** 60 known BidSheet.ai tool names are rewritten to
   `mcp__bidmanager__<tool>` (~240 substitutions across the library). The transform is
   idempotent and word-boundary anchored.
3. **Display-contract note.** Skills that render tables are told, up front, that the
   artifact editor is unavailable and to go straight to the `to_editable_html` page path.
4. **Wheel bundling.** `plugins/estimating-core/dist/*.whl` is copied to `skills/_dist/`.

### The artifact-editor server is deliberately not shipped

The plugin's third MCP server exposes `open_artifact_editor` as an **MCP App**
(`io.modelcontextprotocol/ui`) on Apps-declaring hosts. Historically its `list_tools`
returned `[]` for everyone else, so shipping it under OpenWorker's tools-only MCP client
would have spawned a stdio process contributing nothing — that was this section's original
rationale.

**Since estimating_tools 0.1.8 that rationale is obsolete:** the server now exposes a
**browser mode** to non-Apps hosts — `open_artifact_editor` serves the editable grid over
loopback HTTP into the user's browser, long-polls for Save, and returns the edited block
as the tool result (`collect_artifact_edits` covers the timeout path). OpenWorker runs on
the user's machine, so this would work there. Shipping the server in this build is a
viable follow-up; it stays un-shipped pending that decision, and the ported skills'
display note says so.

Until then the skills' documented fallback covers it: build the page with
`estimating_tools.artifacts_html.to_editable_html` and write it as `<slug>.artifact.html`.
On a messaging persona (Estimator is one) `send_file` can hand that page straight to the
user in chat.

### Known gaps versus the Claude Code plugin

Honest accounting of what does not survive the port:

| Plugin feature | On OpenWorker |
|---|---|
| `hooks/hooks.json` SessionStart wheel install | No hook system. `install.py` does it once; skills keep a manual fallback. |
| `open_artifact_editor` inline editable grid | No MCP Apps support. Falls back to a written HTML page. |
| `agents/estimator-agent.md` subagent | No user-defined subagents. Folded into the Estimator persona's prompt. |
| `.claude-plugin/marketplace.json` (2 plugins) | No marketplace format. One persona + one flat skill library. |
| `plugin:skill` namespacing | Skills live in one flat global namespace keyed by `name`. |
| Per-plugin enable/disable | Personas toggle; skills are all-or-nothing per directory. |

### Tests

```bash
python -m pytest openworker/tests/ -q     # 138 tests
python openworker/port_skills.py --check  # is the committed port current?
```

The tests reimplement OpenWorker's parsing rules from the named upstream sources rather than
importing it (it is not a dependency), so drift surfaces as a failure here. They cover: every
skill parses under the line-based frontmatter parser, directory names match frontmatter
names, no name collisions, no `${CLAUDE_PLUGIN_ROOT}` survivors, no un-namespaced MCP tool
names, the persona validates against the closed catalog and the id/family/mode enums, every
skill a persona lists exists, MCP keys survive `tool_name()` sanitization unchanged, and the
automation payloads are shaped the way `create_automation` and `grant_entries` expect.
