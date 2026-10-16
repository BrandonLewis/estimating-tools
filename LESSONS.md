# Lessons

What a year of building and using this taught, kept short. Each is a rule the
code or the CI now enforces, with the failure that produced it.

**Takeoff quantities are not bid-item quantities.** A push wrote measured
quantities onto a live bid's official schedule quantities and corrupted the
bid. Now takeoffs land on the estimate layer, the one legacy path that can
write the other way stamps a warning into its own plan, and the skill refuses
it on live bids.

**Render the write plan, then ask.** Every module that talks about the
product is a pure planner. The agent shows the plan and asks before executing.
This is cheaper than any amount of "be careful" in a prompt, and it is what
makes the same planner safe on every agent runtime.

**Ship the wheel inside the plugin.** A plugin is installed as a subtree with
no access to its repository, and a skill that depends on a tool that is not
there fails in the user's session, not in CI. The wheels are committed beside
the skills and a drift guard rebuilds them on every change.

**A SessionStart hook must not be able to fail.** A hook that raised took the
session's start with it. Every exit is 0, exactly one line is printed, and
the worst realistic case (no wheels anywhere) is a test.

**Tests are not shipped surface.** 142 test modules reached every customer's
site-packages because packaging included the package wholesale. A test now
builds a wheel from source and asserts no test module is in it.

**A stale build directory is a packaging input.** Modules deleted from the
source tree kept shipping because `build/lib` still held them and setuptools
reused it. The wheel builder cleans before it builds.

**Guard the guard's inclusion.** 255 tests sat outside CI's pytest selection
for several releases, and one had been failing on a real bug. A test now
asserts that every directory holding tests is in both workflows' selection,
and it lives where it cannot drop out with the directory it guards.

**Fixtures cite a source or derive in-repo.** A test fixture carrying a real
bid number is a provenance leak nobody notices for a year. The scanner refuses
the pattern in every tracked file and inside the wheels, and the private
tokens it also refuses come from a repository secret so the list itself is
not in the tree.

**One manifest, generated clients.** Hand-maintained MCP configurations for
five clients drifted within weeks. One `servers.manifest.yaml` generates all
of them and CI checks the generated files match.

**The same skill text ports.** The Agent Skills format is the same across
Claude Code and OpenWorker; what does not port is the plugin root, the tool
namespacing and the display contract, so a script rewrites exactly those and a
test fails when the port is stale.

**Configuration is data the core resolves.** Branching on an organisation
inside the core would have put that organisation in the public tree. A
profile, a format pack and a style pack are directories or entry points the
core resolves without importing them by name.
