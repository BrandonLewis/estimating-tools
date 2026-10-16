# Calculator plugin template

Copy this directory to make your own calculator plugin:

    cp -r templates/calculator-plugin plugins/calc-<yourname>

Then edit `.claude-plugin/plugin.json` (set `name`/`description`), replace
`skills/example-calc/` with your skill, and add an entry to your
`.claude-plugin/marketplace.json`. See `it/rollout.md` for fleet deployment.

Convention: every skill/agent carries a `## Boundaries` block
(✅ Always / ⚠️ Ask first / 🚫 Never) — see `skills/example-calc/SKILL.md`
for the shape, and the `estimator-agent` / `drafting-agent` files for real
examples.
