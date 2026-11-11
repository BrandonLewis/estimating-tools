# Changelog

One version for the whole repository (see `RELEASING.md`). Newest first.

## Unreleased

### Added

- **IFC Navigator**, a prototype second pane in `excel-addin/` (`panes/ifc/`, manifest
  `manifests/ifc-navigator.xml`): loads a bimforge *sheet bundle* (`est-bim sheet-bundle`) into
  `IFC Elements` / `IFC Properties` / `IFC Types` / `IFC Quantities` sheets one chunk at a time,
  inspects the selected element, measures on the chunk's geometry in a three.js viewer (distance
  with vertex snap, coplanar face area, element box dims) with results sent to a cell or logged,
  and diffs the sheets against the loaded origin into a `bimforge-changes/1` change-set for
  `est-bim apply-changes`. Pure core under `core/ifc/` with `node --test` coverage.
- `est-addin manifest --pane` (and `render_manifest(pane=...)`): a manifest for another pane in
  the same build, with its own add-in id. `package.py` writes `ifc-manifest.xml` beside
  `manifest.xml`.

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
