# Changelog

One version for the whole repository (see `RELEASING.md`). Newest first.

## 0.1.87 — first public release

The estimating platform moves to a public repository with a fresh history.
It grew up for a year inside a private monorepo alongside the organisation
profile and bid documents it was first used with; those stay private, and the
tree here is produced from that repository by an export that excludes them,
gated by a provenance scanner, gitleaks and a dependency audit on every push.

What ships: the `estimating_tools` package (open canonical models, importers,
the `est-*` CLIs, the pure push/sync planners), two Claude Code plugins
(`estimating-core`, `calc-bim`) with their bundled wheels, the agent skills in
the open Agent Skills format, the OpenWorker port, the single MCP server
manifest with per-client adapters and IT templates, the fictional example
organisation profile, and the transcribed Caltrans 2025 standard-plan tables.
BIM and CAD live in the `bimforge` package on PyPI, released from
BrandonLewis/BIMForge.
