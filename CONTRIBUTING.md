# Contributing

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e 'packages/estimating-tools[all]'      # bimforge resolves from PyPI
python -m pytest packages/estimating-tools/estimating_tools manifest tests openworker/tests -q
```

Tests live next to the code (`estimating_tools/<subpackage>/tests/`) plus the
repo-level guards in `tests/`. The suite needs no account and no network:
every module that talks about BidSheet.ai is a pure planner that emits
operations for an agent to execute, never a client.

## What changes together

Some things are generated from a source of truth and guarded in CI; change
the source and regenerate, never the copy:

| source | generated | regenerate | guard |
|---|---|---|---|
| `packages/estimating-tools/` | `plugins/estimating-core/dist/estimating_tools-*.whl`, `openworker/skills/_dist/` | `python scripts/build_plugin_wheel.py plugins/estimating-core` then `python openworker/port_skills.py` | wheel drift, OpenWorker port drift |
| `scripts/plugin_runtime.py` | each plugin's `scripts/plugin_runtime.py` | `python scripts/vendor_runtime.py` | vendored runtime drift |
| `manifest/servers.manifest.yaml` | `plugins/*/.mcp.json`, `it/*.snippet*`, `openworker/mcp/mcpServers.json` | `python manifest/generate.py` | manifest drift |
| `plugins/*/skills/*/SKILL.md` | `openworker/skills/*/SKILL.md` | `python openworker/port_skills.py` | OpenWorker port drift |

The bundled `bimforge` wheel is the PyPI release of
[BrandonLewis/BIMForge](https://github.com/BrandonLewis/BIMForge); bump the
floor in `packages/estimating-tools/pyproject.toml` and replace the wheel
together (`tests/test_bimforge_floor.py` pins them to each other).

## Rules the CI gate enforces

- **Fixture provenance.** A fixture cites a public source or derives its
  quantities in-repo. Never a real bid number, a project working directory,
  or a person's attribution. `scripts/deorg_scan.py` refuses bid numbers
  (`B2xxx`), machine paths and credential-shaped strings in every tracked
  file and inside every bundled wheel; the maintainer adds project-specific
  tokens through the `DEORG_EXTRA_PATTERNS` repository secret.
- **No secrets, ever,** including in history — gitleaks runs over the full
  history on every push.
- **Dependencies audited** — pip-audit runs against the resolved `[all]` set.
- **The bundled wheels install clean** in a fresh venv, every module a skill
  imports loads, and the CLIs respond.
- **Skills name their tools by shim path** (`~/.estimating/bin/...`): the
  tools are not on PATH in a session.
- **Every test directory is in CI's selection** (`tests/test_ci_test_selection.py`).

## Skills

A skill is a `SKILL.md` in the open Agent Skills format with a `## Boundaries`
block (Always / Ask first / Never). Any BidSheet.ai write is "ask first" and
renders its plan before executing. Takeoff quantities never land on official
bid-item quantities. The `estimating-reference` skill is the vocabulary every
other skill assumes; read it before writing one.

## Where development happens

This repository is produced from the maintainer's private monorepo by an
export (`scripts/export_public.py` there), which excludes the organisation
profile and bid documents the tools were first built against. Pull requests
here are welcome and are ported back; the plan is for development to move here
outright once the private layer is a plain package installed on top.

## Releasing

See `RELEASING.md`. Security reports: see `SECURITY.md`.
