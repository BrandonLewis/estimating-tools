# estimating_tools

Deterministic construction-estimating tools: the open canonical models
(estimates, assemblies, rates, quotes, takeoffs, directories, cost codes),
the importers that free legacy data into them, the `est-*` command-line tools,
and the pure "plan" modules that turn those models into operations an agent
executes against BidSheet.ai through its MCP server. The library itself opens
no network connection: the only exceptions are `m2m-token`, which requests a
bearer token from the OAuth server named in a manifest, and the artifact editor,
which serves its page on a loopback port for the local browser. BIM and CAD live
in the separate `bimforge` package.

```bash
pip install 'estimating_tools[all]'
est-import --help
```

Source, documentation and the agent skills that drive these tools:
<https://github.com/BrandonLewis/estimating-tools>. Apache-2.0.
