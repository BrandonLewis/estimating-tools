# estimating-tools

Construction estimating for agents and the people who work with them: an open
data model, deterministic tools, and the workflow knowledge to use them, packaged
so that Claude Code, Cowork, OpenWorker, OpenCode, Codex, Gemini CLI and Cursor can all drive
the same estimating stack.

- **`estimating_tools`** (Python, PyPI): the open canonical models for estimates,
  assemblies, rates, quotes, takeoffs, directories and cost codes; importers that free
  legacy data into them; twenty `est-*` command-line tools; and pure "planners" that
  turn a model into the operations an agent executes against BidSheet.ai.
- **Two Claude Code plugins** with bundled wheels: `estimating-core` (the estimating
  workflows and the estimator agent) and `calc-bim` (DXF to IFC authoring and IFC to
  takeoff, over the [`bimforge`](https://github.com/BrandonLewis/BIMForge) package).
- **54 skills** in the open Agent Skills format, each with a stated boundary of what it
  does unasked, what it asks first, and what it never does.
- **One MCP server manifest** that generates every client's configuration, plus the
  templates an IT team needs to roll the whole thing out with managed settings.

Everything a skill does, a person can do from a shell, and an agent on any runtime can
do through the MCP servers. The skills carry the "how"; the tools carry the arithmetic.

## The same task three ways

Level a work package's subcontractor quotes into a spread with the best price per item.

**From a shell** (the deterministic core; no account needed):

```bash
pip install 'estimating_tools[all]'
est-quotespace --help          # the quote board and leveling tools
est-quotes --help              # quote documents in a folder -> vendor quote files
```

**As an MCP tool call** from any agent runtime connected to BidSheet.ai:

```
compare_work_package_quotes(work_package_id=42)
```

**As a skill** in Claude Code, Cowork or OpenWorker:

> "Compare the quotes on the drainage work package."

The `compare-quotes` skill fetches the quotes through the MCP, runs the leveling core,
renders the spread, and stops: it is read-only. Awarding a quote is a different skill
(`apply-quotes`) that shows its write plan and asks before posting.

## Install

**Claude Code**

```
/plugin marketplace add BrandonLewis/estimating-tools
/plugin install estimating-core@estimating-platform
/plugin install calc-bim@estimating-platform
```

Each plugin's SessionStart hook installs its bundled wheels into a private runtime, so a
session needs no checkout of this repository. Both MCP servers (BidSheet.ai and
conformed.ai) authenticate with per-user OAuth 2.1; sign in at first use.

**Cowork and Claude web/desktop chat**: install the plugin from the marketplace
(Customize, Plugins, Add marketplace). Organisation owners register the connectors
once in `it/cowork-connector.md`.

**OpenWorker**: `python openworker/install.py` copies the ported skills, merges the MCP
servers, installs the personas and pip-installs the wheel. See `openworker/README.md`.

**OpenCode**: `python opencode/install.py` builds the same `~/.estimating` runtime the Claude
Code plugin uses, installs the skills with OpenCode's tool names and merges the MCP servers into
`opencode.json` (`--project DIR`, `--dry-run`; re-run to upgrade). See `opencode/README.md`.

**Codex CLI, Gemini CLI, Cursor**: generate the client's MCP configuration from the one
manifest and apply it:

```bash
python manifest/generate.py --client codex     # or: gemini | cursor
```

**Just the tools**:

```bash
pip install 'estimating_tools[all]'
```

Headless and CI runs mint a short-lived bearer token with `m2m-token --server bidmanager`
(OAuth client credentials from the runner's secret store; see `it/rollout.md`).

## What is here

```
packages/estimating-tools/   the Python package and its tests
plugins/estimating-core/     skills, estimator agent, hooks, bundled wheels, artifact-editor MCP server
plugins/calc-bim/            DXF → BIM → takeoff skills over bimforge, bundled wheel
openworker/                  the OpenWorker port (generated from plugins/, drift-guarded)
opencode/                    the OpenCode installer (runtime, ported skills, MCP config)
manifest/                    servers.manifest.yaml and the per-client config generator
it/                          managed-settings templates and the rollout runbook
templates/                   starting points: an org profile, a calculator plugin, an importer
data/caltrans-2025/          transcribed Caltrans 2025 standard-plan tables (public-agency source)
scripts/                     wheel bundling, drift guards, the provenance scanner, Caltrans tooling
tests/                       repository-level guards
docs/tutorials/              worked examples, start to finish
```

`ARCHITECTURE.md` explains the layers and why the boundaries sit where they do.
`LESSONS.md` is what building it taught.

## Workflows

A bid runs through the skills roughly in this order; every one is also a CLI.

| stage | skills | tools |
|---|---|---|
| start | `intake-project`, `project-briefing`, `scaffold-project` | `est-intake`, `est-scaffold` |
| quantities | `quantity-takeoff`, `measure-plans`, `read-station-plans`, `earthwork-takeoff`, `rebar-schedule`, `dxf-to-bim`, `bim-to-takeoff`, `audit-quantities`, `push-takeoff` | `est-takeoff`, `est-rebar`, `est-bim` |
| estimate | `estimate-project`, `build-estimate-workbook`, `build-assemblies`, `price-estimate`, `bm-sync`, `save-scaffolds`, `estimate-template` | `est-estimate`, `est-hist` |
| quotes | `solicit-quotes`, `capture-quote`, `compare-quotes`, `compare-item-quotes`, `quote-coverage`, `apply-quotes`, `manage-work-packages` | `est-quotespace`, `est-quotes` |
| schedule | `schedule-export`, `cost-load-schedule`, `stage-model` | `est-schedule`, `est-gantt` |
| documents | `draft-an-rfi`, `subcontract-risk-review`, `pdf-extraction`, `excel-automation` | `est-letterhead` |
| onboarding | `import-estimate`, `import-assemblies`, `import-rates`, `import-cost-codes`, `import-directory`, `import-historicals`, `create-assemblies`, `create-org-profile`, `sync-directory` | `est-import`, `asm-import`, `rate-import`, `costcode-import`, `dir-import`, `dir-sync`, `profile-init` |

`estimating-reference` is the vocabulary the others assume: the domain model, the MCP
tools, agency bid-schedule semantics, and the conflict ledger for when documents
disagree.

For a worked example of the BIM leg — a plan DXF to an IFC model to a takeoff,
checked by hand in Blender with Bonsai, then out to a spreadsheet — see
[`docs/tutorials/model-to-takeoff.md`](docs/tutorials/model-to-takeoff.md).

## Importers: data liberation

Point `est-import` at a legacy export and get an open `CanonicalEstimate` you own:

```bash
est-import path/to/heavybid-export.xlsx -o estimate.canonical.json
```

The first adapter reads HCSS HeavyBid Excel exports; `templates/importer/` is the
starting point for yours. The same pattern covers assembly libraries, rate libraries,
cost-code systems and vendor directories: a spreadsheet in, an open JSON model out, and a
skill that proposes the column mapping and pushes the result to BidSheet.ai without
duplicating what is already there.

## Profiles

A profile tailors the agnostic core to an organisation (letterhead, folder conventions,
argot) or an agency (spec citations, standard details) without code changes. It is a
directory with a `profile.yaml`; set an ordered list of them in `ESTIMATING_PROFILES`.
`templates/profile/` is a complete fictional example, Anvil Rock Road Constructors, to
copy from, and `create-org-profile` interviews for a new one. Rates are not profile
data: they come from BidSheet.ai.

A workbook format is a format pack, chosen by the profile or by `--format`; the demo
pack ships, and the `est-estimate` verbs that write a spec refuse to shape your file like
another organisation's unless you name a pack.

## Provenance

Fixtures cite a public source or derive their quantities in the repository. The Caltrans
tables record which sheets they came from and their checksums. CI refuses machine
paths, credential-shaped strings and real bid numbers in every tracked file and inside
every bundled wheel, runs gitleaks over the full history, and audits the resolved
dependencies. The repository history starts at the first public release.

## Contributing, security, license

`CONTRIBUTING.md` covers development and what regenerates from what. Report
vulnerabilities privately as `SECURITY.md` describes. Apache-2.0; attributions in
`NOTICE`.
