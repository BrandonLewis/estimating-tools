---
name: audit-quantities
description: Three-way quantity audit — reconcile the takeoff against the IFC model and the BidSheet.ai estimate into an audit.xlsx (Summary / Elements / Exceptions). Read-only against BidSheet.ai; writes a local workbook. Use before push-takeoff (as a gate) and after model or estimate edits.
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

# Audit Quantities

When to use: after `bim-to-takeoff` produces takeoff.json and before/after the
takeoff is pushed — answers "does every priced quantity trace to model
elements, and do takeoff, model, and estimate still agree?"

## Steps

1. **Fetch the BM snapshot** (optional leg — skip for a model-only audit).
   Query the estimate's bid items and structures via the BidSheet.ai MCP and
   write bm_snapshot.json in this exact shape:
   ```json
   {"estimate_ref": "...", "fetched_at": "<iso>", "items": [
     {"schedule": "...", "item_number": "...", "description": "...",
      "unit": "...", "estimate_qty": <number>,
      "structures": [{"structure_id": "...", "sections": []}]}]}
   ```
2. **Run the audit:**
   ```bash
   ~/.estimating/bin/est-takeoff audit --takeoff takeoff.json --ifc model.ifc \
       --bm bm_snapshot.json [--tol-pct 1.0] [--strict]
   ```
3. **Walk the Exceptions tab** with the estimator — every row is a finding
   with a reason; an empty tab is the pass condition. Statuses on Summary:
   OK / VARIANCE / MISSING IN <leg>.

## Notes

- Legs are optional: omit --bm right after a takeoff, omit --ifc when the
  model isn't at hand; missing legs render N/A, never zero.
- The Elements (per-element traceability) tab is populated when the --ifc
  leg is present.
- Takeoffs from est-bim < 0.1.32 lack element global_ids — the audit
  name-joins and flags LEGACY rows; regenerate the takeoff for exact joins.
- Foreign IFCs that entered via the `ifc-to-dxf` skill in the calc-bim
  plugin and `dxf-to-bim` audit like native ones — the audit runs against
  the pipeline-authored IFC, where Qtos and GlobalIds exist by
  construction.
- Use --strict as a pre-push gate before the `push-takeoff` skill.
