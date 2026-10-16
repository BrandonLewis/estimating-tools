# Profile template

Copy this directory to make your own org or agency profile:

    cp -r templates/profile my-profile

Edit `profile.yaml` (set `kind`, `name`, and your fields), drop in a
`letterhead.docx` if you use one, and adjust `trees/project-tree.yaml`. Then make
it active by adding the directory to `ESTIMATING_PROFILES` (ordered list separated
by your OS path separator, `:` on POSIX / `;` on Windows, e.g. `base:org:agency`),
either directly or via your IT managed-settings — see
`it/profile-managed-settings.snippet.json`. Profiles can also be shipped as
marketplace plugins that append their path to `ESTIMATING_PROFILES`.

Fields are validated per-field: a malformed field is ignored with a warning, the
rest still load. Rates are NOT part of a profile — they come from the BidSheet.ai
MCP.
