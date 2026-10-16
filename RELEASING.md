# Releasing

One version for the whole repository. Two artifacts come out of a release:

- **the plugin marketplace**, which Claude Code installs from the `vX.Y.Z`
  tag of this repository (`.claude-plugin/marketplace.json`, the two plugins
  with their bundled wheels);
- **`estimating_tools` on PyPI**, built from `packages/estimating-tools` and
  published through trusted publishing.

`bimforge` has its own release line from
[BrandonLewis/BIMForge](https://github.com/BrandonLewis/BIMForge); this
repository pins a floor and bundles that release's wheel.

To cut `vX.Y.Z`:

1. **Write the changelog entry** in `CHANGELOG.md`. The generated GitHub
   notes are a commit list, not an upgrade note.
2. **Bump the version** in the four version files, in one PR:
   `packages/estimating-tools/pyproject.toml`,
   `plugins/estimating-core/.claude-plugin/plugin.json`,
   `plugins/calc-bim/.claude-plugin/plugin.json`, and the `bimforge` floor
   if the bundled wheel changes.
3. **Regenerate** the bundled wheel and the OpenWorker copies:
   `python scripts/build_plugin_wheel.py plugins/estimating-core` and
   `python openworker/port_skills.py`. CI's drift guards fail the PR if either
   is skipped.
4. **Release:** push the tag `vX.Y.Z` (the workflow refuses a tag that does
   not equal every committed version), or run **Release** from the Actions
   tab on `main`: the run tags that commit itself and refuses a version that
   is already tagged. `release.yml` tests, builds the sdist and wheel,
   publishes to PyPI (trusted publishing, environment `pypi`) and creates the
   GitHub release with the wheels attached.

Already-provisioned sessions pick up a new version only when the version
changes: the SessionStart hook installs the bundled wheel by version, so a
code change that must reach existing machines needs a bump.
