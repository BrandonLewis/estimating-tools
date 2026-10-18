# The estimating platform on OpenCode

[OpenCode](https://opencode.ai) has no plugin bundle and no SessionStart hook, so
`install.py` does by hand what the Claude Code plugin does for itself. Run it from a checkout
of this repository:

```bash
python opencode/install.py                          # global: ~/.config/opencode
python opencode/install.py --project ~/bids/hwy-41  # per project: .opencode/skills + opencode.json
python opencode/install.py --dry-run                # print every action, write nothing
```

It is stdlib-only, so any Python 3.10 or newer can run it. Re-run it after pulling a new
release to upgrade. An unchanged install reports "up to date".

## What it does

1. **Runtime.** It calls the plugin's own `plugins/estimating-core/scripts/plugin_runtime.py`
   on the wheels bundled in `plugins/estimating-core/dist`. That builds or refreshes the shared
   runtime at `~/.estimating`: one venv holding `estimating_tools` and `bimforge`, plus the
   `~/.estimating/bin/est-*` shims. It is the same runtime the Claude Code plugin uses, so a
   machine with both shares one copy. If the runtime already holds a NEWER release (the Claude
   plugin updated first), the installer stops rather than downgrade it; pull this checkout to
   that release, or pass `--force`. If the build fails, it exits 1 before touching the skills
   or `opencode.json`, so they never point at tools from a release that is not installed.
   `ESTIMATING_RUNTIME_HOME` relocates the runtime, but the skill text then no longer names
   the right path.
2. **Skills.** Every plugin `SKILL.md` is ported with `openworker/port_skills.py`'s OpenCode
   body (a library function; this installer is the only supported way to write the OpenCode
   skills) and written to `~/.config/opencode/skills/<name>/`, or
   `<project>/.opencode/skills/<name>/` with `--project`. `$XDG_CONFIG_HOME/opencode` is used
   in place of `~/.config/opencode` when that variable is set. The port gives MCP tools
   OpenCode's names (`bidmanager_get_project`, `artifact-editor_open_artifact_editor`) and
   keeps the literal `~/.estimating/bin/...` paths, which step 1 makes real. Each folder it
   writes carries a `.installed-by-estimating-opencode` marker. Only marked folders are ever
   updated or removed, so your own skills are left alone, including one that shares a name
   with ours. Each folder is staged beside its target and swapped in, so an interrupted run
   never leaves a half-written skill.
3. **MCP.** `bidmanager` and `conformed` come from `it/opencode.json`, which is generated from
   the server manifest. A local `artifact-editor` server runs the runtime's `est-artifact-app`
   shim (under `cmd.exe /d /c` on Windows). All three are merged into the highest-priority
   existing config (`opencode.jsonc` before `opencode.json`), and every other setting is left
   alone. Existing server entries are read using OpenCode's merge order: global `config.json`,
   then `opencode.json`, then `opencode.jsonc`. Entries from lower-priority files are preserved
   there, rather than copied into the writable file and shadowing future edits. The installer
   records a hash of each entry it writes in
   `.estimating-opencode-mcp.json` beside the config. On a re-run, an entry that still matches
   its hash is upgraded to this release's (a changed URL reaches you). An entry you wrote or
   edited is kept, and the installer prints a diff against this release's entry so you can
   take it by hand. If any contributing file is JSONC
   with comments or trailing commas, the installer stops before writing anything and prints
   the entries to paste by hand. Re-run with `--no-mcp` after pasting them.

`--no-runtime` and `--no-mcp` skip those steps. `--force` allows the runtime downgrade.

## After installing

Restart OpenCode. The first use of `bidmanager` prompts a sign-in, or you can sign in ahead of
time with `opencode mcp auth bidmanager` (and `conformed`). Headless runs use a Bearer header
instead; see `it/rollout.md`, "Other clients".
