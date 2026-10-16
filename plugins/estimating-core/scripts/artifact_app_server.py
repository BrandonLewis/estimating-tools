"""Launch the artifact-editor MCP server on the plugins' shared runtime.

`scripts/launch` reaches this through `plugin_runtime.py serve`, which has
already made the runtime current and exec'd the runtime's own interpreter --  so
by the time this file runs, `estimating_tools` is importable and there is
nothing left to install. It used to call `ensure_tools.main()` itself, racing
the SessionStart hook's pip on a version-skewed start; the runtime resolver
removes that race rather than documenting it -- one builder wins a `mkdir`
claim on the runtime directory and the losers wait for its `.ready` marker.

The venv is built IN PLACE under that claim and is never swapped in by
renaming: pip bakes the build-time absolute path into every console script's
shebang, so a renamed venv yields `exec: .../.tmp-XXXX/v/bin/python: not
found` on the first `est-*` call. `os.replace` publishes only the marker, the
shims and state.json. Do not reintroduce the renamed-venv design.

stdout is reserved for the MCP stdio protocol; all diagnostics go to stderr.
"""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from estimating_tools.artifact_app.server import main as server_main
    except ImportError as exc:
        print(
            f"estimating-core: artifact-editor server unavailable ({exc}); "
            "sessions fall back to the artifact/file display path",
            file=sys.stderr,
        )
        return 1
    # Forward our argv so launcher flags (e.g. --version) reach the server.
    return server_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
