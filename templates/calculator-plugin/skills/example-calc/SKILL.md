---
name: example-calc
description: EXAMPLE — replace with a one-line description of when an agent should run your calculation.
---

# Example Calculation

Replace this body with your workflow. A calculator plugin is just:

1. This `plugin.json` (rename `calc-example` → your plugin name).
2. One or more skills describing when/how to run the calc.
3. A deterministic tool the skill calls. You may either:
   - depend on the shared `estimating-tools` package (`python -m estimating_tools.<x>`
     / the `est-*` console scripts), or
   - ship your own script under this plugin and call it via `${CLAUDE_PLUGIN_ROOT}`.

Then list your plugin in your marketplace's `marketplace.json` and enable it via
managed settings (see `it/rollout.md`).

## Boundaries

The repo convention for skills and agents — keep the three-tier block,
replace the examples:

- ✅ **Always:** run the deterministic tool for the math; show inputs and
  outputs; state units.
- ⚠️ **Ask first:** overwriting a previously delivered result; deviating
  from the documented method.
- 🚫 **Never:** invent an input value; present an unverified number as
  final.
