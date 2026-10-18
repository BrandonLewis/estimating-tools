# IT rollout runbook

This deploys the estimating platform to a whole team. The admin acts once; users
just sign in (SSO).

## Claude Code

Choose one:

- **Server-managed (BYOD, Team/Enterprise):** Claude.ai → Admin Settings → Claude
  Code → Managed settings. Paste `managed-settings.snippet.json`. Clients fetch it
  at startup (hourly poll).
- **Endpoint-managed (MDM, strongest):** deploy `managed-mcp.json.tmpl` (rename to
  `managed-mcp.json`) to the OS system path via Jamf/Intune/GPO to force a fixed
  server set, and merge `managed-settings.snippet.json` into `managed-settings.json`.

Do **not** put API keys or M2M secrets in these files. Auth is per-user OAuth (each
server returns its OAuth metadata; users complete the `/mcp` sign-in). Headless runs use
OAuth `client_credentials` with secrets kept in the runner's secret store — see below.

### Headless / CI (automated, no browser)

Interactive clients (developers, Cowork) use per-user OAuth. Automated runs that cannot
open a browser use the OAuth **`client_credentials`** machine-to-machine grant (live on
both servers — BidManager #604, conformed.ai #204):

1. Put the client credentials in the runner's secret store —
   `BIDMANAGER_CLIENT_ID` / `BIDMANAGER_CLIENT_SECRET` (and `CONFORMED_CLIENT_ID` /
   `CONFORMED_CLIENT_SECRET`). **Never commit them.**
2. Mint a short-lived bearer token: `TOKEN=$(m2m-token --server bidmanager)` — or
   `m2m-token --server bidmanager --header` to emit the full `Authorization: Bearer
   <token>` line. The helper reads the secrets from the environment only, requests
   `scope=mcp` over TLS, and prints nothing else.
3. Inject `Authorization: Bearer $TOKEN` for that server via your env/managed override
   (the same mechanism used for any header) — **never commit the token**.

Tokens are short-lived: mint per run and re-run `m2m-token` when one expires. Enable your
runner's secret-masking on the token output. The credentials and token never touch a
committed file.

## Cowork

Follow `cowork-connector.md` to register each server as an org Custom Connector;
members click Connect and sign in.

## Other clients (Codex / Gemini CLI / Cursor / OpenCode)

The same two MCP servers work in other agent clients. Generate each client's config from the
manifest — `python manifest/generate.py --client {gemini,cursor,codex,opencode}` writes the snippet
under `it/` — then apply it:

- **Gemini CLI** — merge `it/gemini-settings.snippet.json` into `~/.gemini/settings.json`.
  Interactive: the `oauth.authProviderType: dynamic_discovery` entries auto-discover each
  server's OAuth metadata and sign in on first use (tokens cached in
  `~/.gemini/mcp-oauth-tokens.json`).
- **Cursor** — copy `it/cursor-mcp.json` to `.cursor/mcp.json` (project) or `~/.cursor/mcp.json`
  (global). Interactive: Cursor runs the OAuth 2.1 flow on first connect from the `url` alone.
- **Codex CLI** — merge `it/codex-config.toml.snippet` into `~/.codex/config.toml`. Each server
  uses `bearer_token_env_var`; set that env var to a token (see Headless below). Codex's native
  OAuth (`codex mcp login`) currently has tool-import / bearer-auth issues (openai/codex
  #20009, #26760), so the Bearer-token path is recommended.
- **OpenCode** — merge `it/opencode.json`'s `mcp` block into `opencode.json` (project root) or
  `~/.config/opencode/opencode.json` (global). Interactive: the remote entries are url-only, so
  OpenCode runs each server's OAuth flow on first connect (`opencode mcp auth bidmanager` signs
  in ahead of time). `python opencode/install.py` does this merge for you, along with the
  skills and CLIs (see "The CLIs and skills (OpenCode)" below).

**Headless / CI (all four):** mint a short-lived token with `m2m-token` and supply it as a
Bearer — never commit it:

    export BIDMANAGER_BEARER="$(m2m-token --server bidmanager)"
    export CONFORMED_BEARER="$(m2m-token --server conformed)"

- **Codex** reads these via the snippet's `bearer_token_env_var` (already set).
- **Cursor/Gemini:** replace the server's `oauth`/url-only auth with a header — Cursor resolves
  `"headers": {"Authorization": "Bearer ${env:BIDMANAGER_BEARER}"}`; for Gemini, set the resolved
  `Authorization` header value; OpenCode expands `{env:...}` in a header:
  `"headers": {"Authorization": "Bearer {env:BIDMANAGER_BEARER}"}`.

To point at a different endpoint, edit the URL in the snippet (env-substitution syntax differs
per client, so the snippets ship concrete URLs).

**The CLIs and skills (OpenCode).** Outside the Claude plugin nothing installs the `est-*` tools
or the skills for you, so run the installer from a checkout of this repository:

    python opencode/install.py                        # global: ~/.config/opencode
    python opencode/install.py --project ~/bids/hwy-41  # per project: .opencode/skills + opencode.json
    python opencode/install.py --dry-run              # print every action, write nothing

It does three things, each idempotent. It builds the same shared runtime the Claude plugin's
SessionStart hook builds (`~/.estimating`, from the wheels bundled in
`plugins/estimating-core/dist`), so the skills keep their literal `~/.estimating/bin/est-*` paths
and nothing has to be on `PATH` or in an activated venv. It writes the skills with OpenCode's
tool names (`bidmanager_<tool>`, `artifact-editor_<tool>`) into `~/.config/opencode/skills`
(`$XDG_CONFIG_HOME/opencode` if set), and removes ones it wrote earlier that a release dropped.
Skill folders it did not write are never touched. Finally it merges `bidmanager`, `conformed`
(from `it/opencode.json`) and a local `artifact-editor` server that runs the runtime's
`est-artifact-app` shim into `opencode.json`. Entries it wrote earlier are upgraded when a
release changes them. An entry you wrote or edited is kept, and a diff is printed. Other
settings are never touched. A JSONC config with comments is refused untouched, with the entries
to paste by hand. If the runtime build fails, it exits 1 before changing skills or config. It
will not downgrade a runtime the Claude plugin has already moved to a newer release unless
given `--force`.
Restart OpenCode afterwards. To upgrade, pull and re-run; an unchanged install reports
"up to date". Do not copy `openworker/skills/` instead: that port names MCP tools
`mcp__bidmanager__<tool>`, OpenWorker's form, which OpenCode never registers.

## Adding your own plugins

Fork this repo (or run your own marketplace repo), add your plugin under
`plugins/` (see `templates/calculator-plugin/`), list it in `marketplace.json`,
and add it to `enabledPlugins`.
