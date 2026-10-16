# Architecture

Six layers, bottom up. Each depends only on the open interfaces of the layer
below it, and the boundary between "ours" and "yours" is drawn so that an
organisation's private material never has to live in the public tree.

| layer | what | where |
|---|---|---|
| L0 open data model | projects, bid items, assemblies, quotes, rates, work packages; plans, specs, conformance | BidSheet.ai and conformed.ai, and the canonical models in `estimating_tools` |
| L1 open access | MCP servers over OAuth 2.1, REST APIs | the two products; `manifest/servers.manifest.yaml` describes them once |
| L2 data liberation | importers from legacy tools and spreadsheets into the open model, and planners back out | `estimating_tools.importers`, `.assemblies`, `.rates`, `.costcodes`, `.directory`, `.historicals` |
| L3 capabilities | skills (workflows), deterministic tools, agents | `plugins/*/skills`, the `est-*` CLIs, `plugins/estimating-core/agents` |
| L4 configurability | organisation and agency profiles, workbook format packs, CAD style packs | `estimating_tools.profiles`, format packs, the `bimforge.style_packs` entry point |
| L5 distribution | one manifest, per-client adapters, plugin marketplace, IT templates | `manifest/`, `.claude-plugin/`, `plugins/`, `openworker/`, `it/` |

## Three rules that shape the code

**Planners, not clients.** No module in `estimating_tools` opens a connection to
BidSheet.ai. A module such as `importers.push`, `takeoff.push`, `assemblies.plan`
or `estimate_spec.sync` takes a canonical model and returns a plan: a list of
operation records whose fields match the MCP tools. The skill renders the plan,
asks, and executes it through the MCP. This keeps the Python pure and testable,
keeps every write visible to the user before it happens, and means the same
planner serves any agent runtime that can call the MCP.

**Takeoff never lands on the official quantity.** A bid item's quantity is the
agency's schedule quantity. Measured quantities go to the estimate layer as
structure sections, and the push planner stamps a warning on the one legacy path
that can still write the other way. This rule came from a live bid.

**Configuration is data the core resolves, not branches in the core.** A profile
is a directory. A format pack is a directory. A CAD style pack is an entry point.
The core resolves explicit argument, then registered provider, then built-in
default, and never imports a provider's package by name. A private organisation
layer is therefore a plain `pip install` and an environment variable on top of
this repository, which is how the maintainer's own stays out of it.

## How a session gets its tools

A plugin is installed as its own subtree, so it cannot import a sibling or the
repository root. Each plugin bundles the wheels it needs under `dist/`, and its
SessionStart hook (`scripts/ensure_tools.py`, with `plugin_runtime.py` vendored
beside it) installs them into a per-version runtime under `~/.estimating/` and
exposes the CLIs through shims under `~/.estimating/bin/`. Skills name their
tools by that shim path because the tools are not on `PATH`. The hook never
fails a session: every exit is 0 and exactly one line reaches the user.

The runtime is the union across installed plugins, so `calc-bim`'s hook sees
`estimating-core`'s wheel and vice versa.

## Generated, and guarded

Several trees are generated from a source of truth and CI fails if they drift:
the bundled wheels from the packages, each plugin's `plugin_runtime.py` from the
root copy, every client's MCP configuration from the manifest, and the OpenWorker
skills from the plugin skills. `CONTRIBUTING.md` has the table.

## What stays out

The design documents and plans the code was built from, the organisation profile
and bid documents it was first used against, and the bimforge source (released
separately on PyPI) stay in the maintainer's private repository. This tree is an
export of that repository with those paths removed and fresh repository files
added; a drift check keeps the two aligned.
